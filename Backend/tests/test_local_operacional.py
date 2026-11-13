"""O modo operacional não abre conexão real nem concede acesso fora do loopback."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from io import BytesIO
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED
from zipfile import ZipInfo
from stat import S_IFLNK
from hashlib import sha256
import json

import pymupdf
import cv2

import pytest
from fastapi.testclient import TestClient

from app.main import criar_app
from app.routes import interface
from app.seguranca import LIMITE_CORPO_UPLOAD
from app.seguranca import LIMITE_CORPO_LOTE


@pytest.fixture
def configuracao(monkeypatch, tmp_path):
    caminho = tmp_path / "credencial-ficticia.json"
    caminho.write_text("{}", encoding="utf-8")
    valores = {
        "APP_AMBIENTE": "local_operacional",
        "LOCAL_OPERACIONAL_HOST": "127.0.0.1",
        "FIRESTORE_MODO": "real",
        "FIREBASE_PROJECT_ID": "projeto-operacional-teste",
        "GOOGLE_APPLICATION_CREDENTIALS": str(caminho),
        "INTEGRIDADE_CHAVE": "0123456789abcdef" * 4,
        "SERVIR_FRONTEND": "true",
    }
    for nome, valor in valores.items():
        monkeypatch.setenv(nome, valor)
    for nome in ("CORS_ORIGINS", "FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST",
                 "FORWARDED_ALLOW_IPS", "RENDER_SERVICE_ID", "RENDER_EXTERNAL_URL",
                 "RENDER_INSTANCE_ID", "RENDER_EXTERNAL_HOSTNAME", "PORT", "VERCEL", "K_SERVICE"):
        monkeypatch.delenv(nome, raising=False)
    from firebase_admin import credentials
    certificado = Mock(return_value=SimpleNamespace(project_id="projeto-operacional-teste"))
    monkeypatch.setattr(credentials, "Certificate", certificado)
    return certificado


@pytest.fixture
def servidor(configuracao, monkeypatch):
    from app import autenticacao
    from app.routes import lotes
    from app.services.lotes_zip import LotesZIP
    verificar = Mock(side_effect=AssertionError("Firebase Authentication não deve ser usado"))
    monkeypatch.setattr(autenticacao, "verificar_token", verificar)
    monkeypatch.setattr(autenticacao, "_app_auth", verificar)
    isolado = LotesZIP()
    monkeypatch.setattr(lotes, "lotes_zip", isolado)
    api = criar_app()
    repo = Mock()
    repo.listar_provas.return_value = []
    repo.listar_alunos.return_value = []
    api.dependency_overrides[interface.obter_persistencia] = lambda: repo
    with TestClient(api, base_url="http://127.0.0.1:8000",
                    client=("127.0.0.1", 50000)) as http:
        yield api, http, repo
    for lote in isolado._lotes.values():
        lote.pasta.cleanup()
    verificar.assert_not_called()


def test_dashboard_e_rotas_sem_login_com_api_local(servidor):
    api, http, repo = servidor
    assert http.get("/interface/").status_code == 200
    config = http.get("/interface/js/config.mjs")
    assert config.status_code == 200
    assert 'export const API_BASE_URL = "";' in config.text
    assert 'export const AUTH_REQUIRED = false;' in config.text
    assert config.headers["cache-control"] == "no-store"
    assert http.get("/api/health").json() == {"status": "ok"}
    assert http.get("/api/avaliacoes").json() == []
    assert http.get("/api/alunos").json() == []
    assert "/api/auth/me" not in [getattr(rota, "path", "") for rota in api.routes]
    assert http.get("/docs").status_code == 404
    repo.listar_provas.assert_called_once()


def test_avaliacoes_sem_login_somente_apos_validacao_de_loopback(servidor):
    api, local, repo = servidor
    assert api.state.ambiente == "local_operacional"
    assert local.get("/api/avaliacoes").status_code == 200
    # Corpo inválido chega à validação da rota: a autenticação não interceptou o POST.
    assert local.post("/api/avaliacoes", json={}).status_code == 422
    assert local.get("/api/auth/me").status_code == 404

    with TestClient(api, base_url="http://127.0.0.1:8000",
                    client=("192.0.2.10", 50000)) as remoto:
        for metodo in ("GET", "POST"):
            assert remoto.request(metodo, "/api/avaliacoes",
                headers={"Authorization": "Bearer token-ficticio",
                         "X-Forwarded-For": "127.0.0.1"}).status_code == 403
    assert repo.listar_provas.call_count == 1


def test_rejeita_cliente_host_origem_e_proxy(servidor):
    api, http, repo = servidor
    for headers in ({"Host": "exemplo.com"}, {"Host": "localhost:8000"},
                    {"Origin": "https://exemplo.com"},
                    {"Forwarded": "for=127.0.0.1"},
                    {"X-Forwarded-For": "127.0.0.1"}):
        assert http.get("/api/avaliacoes", headers=headers).status_code == 403
    with TestClient(api, base_url="http://127.0.0.1:8000",
                    client=("192.0.2.10", 50000)) as remoto:
        assert remoto.get("/api/health").status_code == 403
        assert remoto.get("/api/avaliacoes").status_code == 403
    repo.listar_provas.assert_not_called()


def test_rejeita_servidor_vinculado_fora_do_loopback(servidor):
    api, _, _ = servidor

    async def servidor_externo(scope, receive, send):
        scope = {**scope, "server": ("0.0.0.0", 8000)}
        await api(scope, receive, send)

    with TestClient(servidor_externo, base_url="http://127.0.0.1:8000",
                    client=("127.0.0.1", 50000)) as http:
        assert http.get("/api/health").status_code == 403


def test_ipv6_somente_quando_configurado(configuracao, monkeypatch):
    monkeypatch.setenv("LOCAL_OPERACIONAL_HOST", "::1")
    api = criar_app()
    with TestClient(api, base_url="http://[::1]:8000", client=("::1", 50000)) as http:
        assert http.get("/api/health").status_code == 200
        assert http.get("/api/health", headers={"Origin": "http://[::1]:8000"}).status_code == 200
        assert http.get("/api/health", headers={"Host": "127.0.0.1:8000"}).status_code == 403


def test_integridade_das_rotas_e_limites(servidor):
    _, http, _ = servidor
    assert http.post("/api/avaliacoes", json={}).status_code == 422
    assert http.post("/api/correcoes/salvar", json={}).status_code == 422
    assert http.post("/api/correcoes/processar", headers={
        "Content-Length": str(LIMITE_CORPO_UPLOAD + 1),
        "Content-Type": "multipart/form-data; boundary=teste"}).status_code == 413


def _zip_ficticio(arquivos, compressao=ZIP_STORED):
    saida = BytesIO()
    with ZipFile(saida, "w", compression=compressao) as arquivo:
        for nome, conteudo in arquivos:
            arquivo.writestr(nome, conteudo)
    return saida.getvalue()


def _pdf_ficticio(paginas, *, criptografado=False, largura=300, altura=400):
    with pymupdf.open() as documento:
        for indice in range(paginas):
            pagina = documento.new_page(width=largura, height=altura)
            pagina.insert_text((30, 30), f"Pagina {indice + 1}")
        opcoes = ({"encryption": pymupdf.PDF_ENCRYPT_AES_256,
                   "owner_pw": "dono", "user_pw": "senha"} if criptografado else {})
        return documento.tobytes(**opcoes)


def test_lote_pdf_multipaginas_e_formatos_mistos(servidor):
    _, http, repo = servidor
    pdf = _pdf_ficticio(2)
    jpg = b"\xff\xd8\xff" + b"imagem-ficticia"
    png = b"\x89PNG\r\n\x1a\n" + b"imagem-ficticia"
    zip_bytes = _zip_ficticio([("digitalizados/cartoes.pdf", pdf),
                              ("foto.jpg", jpg), ("foto.png", png)])
    resposta = http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", zip_bytes)})
    assert resposta.status_code == 200
    lote = resposta.json()
    assert lote["total"] == 4
    assert [(item["nome"], item.get("pagina"), item["estado"]) for item in lote["imagens"]] == [
        ("digitalizados/cartoes.pdf", 1, "pendente"),
        ("digitalizados/cartoes.pdf", 2, "pendente"),
        ("foto.jpg", None, "pendente"),
        ("foto.png", None, "pendente"),
    ]
    imagens = [http.get(f"/api/lotes/{lote['lote_id']}/imagens/{indice}") for indice in (0, 1)]
    assert all(r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
               and r.content.startswith(b"\xff\xd8\xff") for r in imagens)
    assert imagens[0].content != imagens[1].content
    assert all(r.headers["x-image-sha256"] == sha256(r.content).hexdigest() for r in imagens)
    assert http.get(f"/api/lotes/{lote['lote_id']}/imagens/3").content == png
    assert http.get(f"/api/lotes/{lote['lote_id']}").json()["imagens"] == lote["imagens"]
    assert http.delete(f"/api/lotes/{lote['lote_id']}").status_code == 204
    repo.salvar_correcao.assert_not_called()


def test_pagina_pdf_do_zip_passa_pelo_motor_de_50_questoes(servidor, tmp_path):
    from test_reconhecimento import cartao
    from app.services.reconhecimento import reconhecer_arquivo

    _, http, _ = servidor
    imagem = cartao({(1, 0): "cheia", (50, 4): "cheia"})
    with pymupdf.open() as documento:
        pagina = documento.new_page(width=850, height=1100)
        pagina.insert_image(pagina.rect, stream=cv2.imencode(".png", imagem)[1].tobytes())
        pdf = documento.tobytes()
    zip_bytes = _zip_ficticio([("gabaritos.pdf", pdf)])
    lote = http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", zip_bytes)}).json()
    resposta = http.get(f"/api/lotes/{lote['lote_id']}/imagens/0")
    assert resposta.status_code == 200
    caminho = tmp_path / "pagina.jpg"
    caminho.write_bytes(resposta.content)
    reconhecidas = reconhecer_arquivo(caminho)
    assert len(reconhecidas) == 50
    assert reconhecidas["1"]["resposta"] == "A"
    assert reconhecidas["50"]["resposta"] == "E"


def test_zip_real_pdf_em_subpasta_chega_a_interface_e_ao_reconhecimento(servidor):
    from test_reconhecimento import cartao

    _, http, repo = servidor
    nome = "Nova pasta/Grade_de_respostas_com_linhas (1).pdf"
    imagem = cartao({(1, 0): "cheia", (50, 4): "cheia"})
    with pymupdf.open() as documento:
        for _ in range(2):
            pagina = documento.new_page(width=850, height=1100)
            pagina.insert_image(pagina.rect, stream=cv2.imencode(".png", imagem)[1].tobytes())
        pdf = documento.tobytes()
    zip_bytes = _zip_ficticio([(nome, pdf)])
    resposta = http.post("/api/lotes/zip", files={"arquivo": ("gabaritos.zip", zip_bytes, "application/zip")})
    assert resposta.status_code == 200
    lote = resposta.json()
    assert lote["total"] == 2
    assert [(item["nome"], item["pagina"], item["estado"], item["erro"])
            for item in lote["imagens"]] == [(nome, 1, "pendente", None), (nome, 2, "pendente", None)]
    for indice in range(2):
        pagina = http.get(f"/api/lotes/{lote['lote_id']}/imagens/{indice}")
        assert pagina.status_code == 200
        assert pagina.headers["content-type"] == "image/jpeg"
        assert pagina.headers["x-image-sha256"] == sha256(pagina.content).hexdigest()
        processada = http.post("/api/correcoes/processar", data={
            "gabarito": json.dumps({str(numero): "A" for numero in range(1, 51)}),
            "visual": "true",
        }, files={"arquivo": (f"pagina-{indice + 1}.jpg", pagina.content, "image/jpeg")})
        assert processada.status_code == 200
        respostas = processada.json()["respostas"]
        assert len(respostas) == 50
        assert respostas["1"]["resposta"] == "A"
        assert respostas["50"]["resposta"] == "E"
    repo.salvar_correcao.assert_not_called()  # Revisão e confirmação seguem obrigatórias.


def test_lote_pdf_uma_pagina_e_arquivos_invalidos(servidor):
    _, http, _ = servidor
    zip_bytes = _zip_ficticio([
        ("unico.pdf", _pdf_ficticio(1)),
        ("protegido.pdf", _pdf_ficticio(1, criptografado=True)),
        ("corrompido.pdf", b"%PDF-isto-nao-e-pdf"),
        ("falso.pdf", b"\x89PNG\r\n\x1a\n"),
        ("gigante.pdf", _pdf_ficticio(1, largura=10000, altura=10000)),
    ])
    resposta = http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", zip_bytes)})
    assert resposta.status_code == 200
    lote = resposta.json()
    assert lote["total"] == 5
    assert [item["estado"] for item in lote["imagens"]] == [
        "pendente", "falha", "falha", "falha", "falha"]
    assert "página" in lote["imagens"][4]["erro"].lower()
    for indice in range(1, 5):
        assert http.get(f"/api/lotes/{lote['lote_id']}/imagens/{indice}").status_code == 415


def test_lote_pdf_excede_limite_de_paginas(servidor):
    _, http, _ = servidor
    zip_bytes = _zip_ficticio([("muitas.pdf", _pdf_ficticio(31))])
    resposta = http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", zip_bytes)})
    assert resposta.status_code == 413
    assert "páginas" in resposta.json()["detail"]


def test_lote_pdf_excede_limite_individual_de_tamanho(servidor):
    _, http, _ = servidor
    conteudo = b"%PDF-" + b"x" * (10 * 1024 * 1024)
    resposta = http.post("/api/lotes/zip", files={"arquivo": (
        "lote.zip", _zip_ficticio([("grande.pdf", conteudo)]))})
    assert resposta.status_code == 413
    assert "tamanho" in resposta.json()["detail"]


def test_lote_pdf_conta_paginas_no_limite_total(servidor, monkeypatch):
    _, http, _ = servidor
    monkeypatch.setenv("LOTE_MAX_IMAGENS", "3")
    zip_bytes = _zip_ficticio([("duas-paginas.pdf", _pdf_ficticio(2)),
                              ("outras.pdf", _pdf_ficticio(2))])
    resposta = http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", zip_bytes)})
    assert resposta.status_code == 413
    assert "gabaritos/páginas" in resposta.json()["detail"]


def test_origem_antiga_de_imagem_preserva_formato_para_reenvio():
    from app.routes.interface import OrigemLote
    origem = {"lote_id": "a" * 32, "indice": 0, "imagem_sha256": "b" * 64}
    assert OrigemLote(**origem).model_dump(exclude_none=True) == origem


def test_lote_zip_local_sequencial_sem_firestore(servidor):
    _, http, repo = servidor
    png = b"\x89PNG\r\n\x1a\n" + b"imagem-ficticia"
    jpg = b"\xff\xd8\xff" + b"imagem-ficticia"
    conteudo = _zip_ficticio([("01.png", png), ("pasta/02.jpg", jpg),
                             ("nao-suportado.txt", b"texto"), ("falso.png", jpg)])
    resposta = http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", conteudo, "application/zip")})
    assert resposta.status_code == 200
    lote = resposta.json()
    assert lote["total"] == 4
    assert [item["estado"] for item in lote["imagens"]] == ["pendente", "pendente", "falha", "falha"]
    identificador = lote["lote_id"]
    assert http.get(f"/api/lotes/{identificador}").json()["total"] == 4
    imagem = http.get(f"/api/lotes/{identificador}/imagens/0")
    assert imagem.content == png
    assert imagem.headers["cache-control"] == "no-store"
    assert imagem.headers["x-image-sha256"]
    assert http.get(f"/api/lotes/{identificador}/imagens/2").status_code == 415
    assert http.delete(f"/api/lotes/{identificador}").status_code == 204
    assert http.get(f"/api/lotes/{identificador}").status_code == 404
    assert http.post("/api/lotes/zip", headers={"X-Forwarded-For": "127.0.0.1"},
        files={"arquivo": ("lote.zip", conteudo)}).status_code == 403
    repo.salvar_correcao.assert_not_called()


@pytest.mark.parametrize("arquivos,esperado", [
    ([], 400),
    ([("../segredo.png", b"\x89PNG\r\n\x1a\n")], 400),
    ([("/absoluto.png", b"\x89PNG\r\n\x1a\n")], 400),
    ([("a.png", b"\x89PNG\r\n\x1a\n"), ("A.PNG", b"\x89PNG\r\n\x1a\n")], 400),
    ([(f"{i:04}.png", b"\x89PNG\r\n\x1a\n") for i in range(1001)], 413),
])
def test_lote_zip_rejeita_arquivo_inseguro_ou_excessivo(servidor, arquivos, esperado):
    _, http, _ = servidor
    conteudo = _zip_ficticio(arquivos)
    assert http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", conteudo)}).status_code == esperado


def test_lote_zip_bomba_e_limite_http(servidor):
    _, http, _ = servidor
    bomba = _zip_ficticio([("bomba.png", b"\x89PNG\r\n\x1a\n" + b"0" * 1024 * 1024)], ZIP_DEFLATED)
    assert http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", bomba)}).status_code == 413
    assert http.post("/api/lotes/zip", headers={"Content-Length": str(LIMITE_CORPO_LOTE + 1),
        "Content-Type": "multipart/form-data; boundary=teste"}).status_code == 413


def test_lote_zip_rejeita_link_e_criptografia(servidor):
    _, http, _ = servidor
    saida = BytesIO()
    with ZipFile(saida, "w") as arquivo:
        info = ZipInfo("atalho.png")
        info.create_system = 3
        info.external_attr = (S_IFLNK | 0o777) << 16
        arquivo.writestr(info, "../fora.png")
    assert http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", saida.getvalue())}).status_code == 400
    cifrado = bytearray(_zip_ficticio([("01.png", b"\x89PNG\r\n\x1a\nconteudo")]))
    local = cifrado.index(b"PK\x03\x04")
    central = cifrado.index(b"PK\x01\x02")
    cifrado[local + 6] |= 1
    cifrado[central + 8] |= 1
    assert http.post("/api/lotes/zip", files={"arquivo": ("lote.zip", bytes(cifrado))}).status_code == 400


@pytest.mark.parametrize("nome,valor", [
    ("LOTE_MAX_IMAGENS", "1000"), ("LOTE_ZIP_MAX_MIB", "100"),
    ("LOTE_TOTAL_MAX_MIB", "abc"), ("LOTE_PDF_MAX_PAGINAS", "101"),
])
def test_lote_configuracao_invalida_bloqueia_inicio(configuracao, monkeypatch, nome, valor):
    monkeypatch.setenv(nome, valor)
    with pytest.raises(ValueError):
        criar_app()


@pytest.mark.parametrize("nome,valor", [
    ("FIRESTORE_MODO", "emulador"),
    ("FIREBASE_PROJECT_ID", "demo-projeto"),
    ("GOOGLE_APPLICATION_CREDENTIALS", ""),
    ("INTEGRIDADE_CHAVE", "0" * 64),
    ("SERVIR_FRONTEND", "false"),
    ("LOCAL_OPERACIONAL_HOST", "0.0.0.0"),
    ("CORS_ORIGINS", "https://exemplo.com"),
    ("FORWARDED_ALLOW_IPS", "*"),
    ("RENDER_SERVICE_ID", "servico-ficticio"),
    ("PORT", "10000"),
    ("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080"),
    ("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099"),
])
def test_configuracoes_inseguras_falham_antes_de_iniciar(configuracao, monkeypatch, nome, valor):
    monkeypatch.setenv(nome, valor)
    with pytest.raises(ValueError):
        criar_app()


def test_credencial_invalida_ou_de_outro_projeto_falha(configuracao):
    configuracao.return_value.project_id = "outro-projeto"
    with pytest.raises(ValueError, match="Credenciais locais inválidas"):
        criar_app()
    configuracao.side_effect = ValueError("chave inválida")
    with pytest.raises(ValueError, match="Credenciais locais inválidas"):
        criar_app()


def test_persistencia_real_e_explicita_sem_conexao_de_teste(configuracao, monkeypatch):
    api = criar_app()
    conectar = Mock()

    @contextmanager
    def cliente_simulado(*, emulador):
        conectar(emulador=emulador)
        yield Mock()

    monkeypatch.setattr(interface, "conectar_firestore", cliente_simulado)
    monkeypatch.setattr(interface, "Persistencia", lambda cliente: SimpleNamespace(listar_provas=lambda: []))
    with TestClient(api, base_url="http://127.0.0.1:8000",
                    client=("127.0.0.1", 50000)) as http:
        assert http.get("/api/avaliacoes").status_code == 200
        conectar.assert_called_once_with(emulador=False)
        monkeypatch.setenv("FIRESTORE_MODO", "emulador")
        assert http.get("/api/avaliacoes").status_code == 503
        conectar.assert_called_once()


def test_config_publica_nao_e_alterada(servidor):
    from pathlib import Path
    config = Path(__file__).resolve().parents[2] / "Frontend/js/config.mjs"
    assert "https://corretor-gabaritos-8yal.onrender.com" in config.read_text(encoding="utf-8")
