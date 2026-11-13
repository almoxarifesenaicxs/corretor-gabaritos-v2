"""Fluxo público isolado com cliente Firestore simulado; nenhuma conexão real."""

from contextlib import contextmanager
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
from zipfile import ZipFile

import cv2
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import criar_app
from app import main as modulo_main
from app import seguranca, autenticacao
from app.routes import interface, lotes
from app.services import integridade
from app.services.lotes_zip import LotesZIP
from app.sessoes_publicas import criar_token, identificar_token, registrar_sessao, FirestoreDaSessao
from test_persistencia import banco
from test_reconhecimento import cartao


@pytest.fixture
def publico(monkeypatch, tmp_path, banco):
    monkeypatch.setattr(seguranca, "_PUBLIC_JANELAS", {})
    repo, dados = banco
    credencial = tmp_path / "simulada.json"
    credencial.write_text("{}", encoding="utf-8")
    configuracao = {
        "APP_AMBIENTE": "publico_sessoes", "ALLOWED_HOSTS": "api.example.test",
        "CORS_ORIGINS": "https://site.example.test", "SERVIR_FRONTEND": "false",
        "FIRESTORE_MODO": "real", "FIREBASE_PROJECT_ID": "projeto-publico-isolado",
        "FIREBASE_PRODUCTION_PROJECT_ID": "projeto-real-operacional",
        "GOOGLE_APPLICATION_CREDENTIALS": str(credencial),
        "INTEGRIDADE_CHAVE": "0123456789abcdef" * 4,
        "PUBLIC_SESSION_KEY": "fedcba9876543210" * 4,
        "LOTE_ZIP_MAX_MIB": "8", "LOTE_MAX_IMAGENS": "20",
        "LOTE_TOTAL_MAX_MIB": "50", "LOTE_PDF_MAX_PAGINAS": "10",
    }
    for nome, valor in configuracao.items():
        monkeypatch.setenv(nome, valor)
    for nome in ("FORWARDED_ALLOW_IPS", "FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST", "ADMIN_UIDS"):
        monkeypatch.delenv(nome, raising=False)
    from firebase_admin import credentials
    monkeypatch.setattr(credentials, "Certificate", Mock(return_value=SimpleNamespace(project_id="projeto-publico-isolado")))
    proibido = Mock(side_effect=AssertionError("Firebase Authentication não deve ser usado"))
    monkeypatch.setattr(autenticacao, "_app_auth", proibido)
    monkeypatch.setattr(integridade, "_CHAVE", integridade._CHAVE)

    class Raiz:
        def document(self, sessao):
            class Documento:
                def create(self, conteudo):
                    assert sessao not in metadados
                    metadados[sessao] = conteudo

                def collection(self, nome):
                    return repo.cliente.collection(f"sessoes_publicas/{sessao}/{nome}")
            return Documento()

    metadados = {}

    class Cliente:
        project = "projeto-publico-isolado"
        def collection(self, nome):
            assert nome == "sessoes_publicas"
            return Raiz()
        def batch(self):
            return repo.cliente.batch()
        def transaction(self, **kwargs):
            return repo.cliente.transaction(**kwargs)

    @contextmanager
    def simulado(*, emulador):
        assert emulador is False
        yield Cliente()

    monkeypatch.setattr(interface, "conectar_firestore", simulado)
    monkeypatch.setattr(modulo_main, "conectar_firestore", simulado)
    isolado = LotesZIP()
    monkeypatch.setattr(lotes, "lotes_zip", isolado)
    api = criar_app(pasta_frontend=tmp_path / "ausente")
    with TestClient(api, base_url="http://api.example.test", client=("192.0.2.10", 1234)) as http:
        yield http, dados
    for lote in isolado._lotes.values():
        lote.pasta.cleanup()
    proibido.assert_not_called()


def sessao(http):
    response = http.post("/api/public/session")
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_tokens_imprevisiveis_expiram_e_nao_aceitam_alteracao():
    chave = bytes.fromhex("fedcba9876543210" * 4)
    primeiro = criar_token(chave, agora=1_700_000_000)
    segundo = criar_token(chave, agora=1_700_000_000)
    assert primeiro != segundo
    assert identificar_token(chave, primeiro, agora=1_700_000_001)
    assert identificar_token(chave, primeiro, agora=1_700_000_000 + 31 * 86400) is None
    assert identificar_token(chave, primeiro[:-1] + ("A" if primeiro[-1] != "A" else "B"), agora=1_700_000_001) is None


def test_expiracao_da_sessao_e_registrada_para_limpeza():
    chave = bytes.fromhex("fedcba9876543210" * 4)
    token = criar_token(chave, agora=1_700_000_000)
    cliente = Mock()
    registrar_sessao(cliente, token)
    criado = cliente.collection.return_value.document.return_value.create.call_args.args[0]
    assert criado["expires_at"].timestamp() == 1_700_000_000 + 30 * 86400
    cliente.collection.assert_called_once_with("sessoes_publicas")
    cliente.collection.return_value.document.assert_called_once_with(token.split(".")[0])


def test_indisponibilidade_do_firestore_impede_criacao_da_sessao(publico, monkeypatch):
    http, _ = publico

    @contextmanager
    def indisponivel(*, emulador):
        assert emulador is False
        raise RuntimeError("Firestore simulado indisponível")
        yield

    monkeypatch.setattr(modulo_main, "conectar_firestore", indisponivel)
    with pytest.raises(RuntimeError, match="Firestore simulado indisponível"):
        http.post("/api/public/session")


def test_sessoes_nao_compartilham_avaliacoes_alunos_ou_resultados(publico):
    http, dados = publico
    a, b = sessao(http), sessao(http)
    assert http.get("/api/avaliacoes").status_code == 401
    assert http.get("/api/avaliacoes", headers={"Authorization": "Bearer invalido"}).status_code == 401
    alternativas = {str(i): "A" for i in range(1, 51)}
    criada = http.post("/api/avaliacoes", headers=a, json={
        "titulo": "Avaliação fictícia A", "alternativas": alternativas,
        "confirmado": True, "operacao_id": uuid4().hex})
    assert criada.status_code == 201, criada.text
    prova = criada.json()["id"]
    assert len(http.get("/api/avaliacoes", headers=a).json()) == 1
    assert http.get("/api/avaliacoes", headers=b).json() == []
    assert http.get(f"/api/avaliacoes/{prova}/gabarito", headers=b).status_code == 404
    imagem = cv2.imencode(".png", cartao({(1, 0): "cheia"}))[1].tobytes()
    processada = http.post("/api/correcoes/processar", headers=a, files={"arquivo": ("ficticio.png", imagem)},
                           data={"gabarito": json.dumps(alternativas), "visual": "true"})
    assert processada.status_code == 200, processada.text
    leitura = processada.json()
    operacao = uuid4().hex
    entrada = {"prova_id": prova, "aluno": "ALUNA FICTÍCIA", "resultado": leitura["resultado"],
               "respostas": leitura["respostas"], "comprovante": leitura["comprovante"],
               "operacao_id": operacao, "confirmado": True}
    salva = http.post("/api/correcoes/salvar", headers=a, json=entrada)
    assert salva.status_code == 201, salva.text
    assert http.post("/api/correcoes/salvar", headers=b, json=entrada).status_code in {404, 422}
    assert http.get("/api/alunos", headers=b).json() == []
    assert len(http.get("/api/alunos", headers=a).json()) == 1
    assert http.get("/api/correcoes/exportar", headers=b).json()["resumo"]["total_correcoes"] == 0
    assert http.get("/api/correcoes/exportar", headers=a).json()["resumo"]["total_correcoes"] == 1
    assert http.get(f"/api/operacoes/correcao/{operacao}", headers=b).json()["estado"] != "confirmada"
    assert http.post("/api/correcoes/salvar", headers=a, json=entrada).status_code == 201
    assert len([key for key in dados if key[0].endswith("/correcoes")]) == 1


def test_zip_e_host_isolados(publico):
    http, _ = publico
    a, b = sessao(http), sessao(http)
    imagem = cv2.imencode(".png", cartao())[1].tobytes()
    buffer = BytesIO()
    with ZipFile(buffer, "w") as arquivo:
        arquivo.writestr("ficticio.png", imagem)
    resposta = http.post("/api/lotes/zip", headers=a, files={"arquivo": ("lote.zip", buffer.getvalue())})
    assert resposta.status_code == 200, resposta.text
    lote_id = resposta.json()["lote_id"]
    assert http.get(f"/api/lotes/{lote_id}", headers=b).status_code == 404
    assert http.get(f"/api/lotes/{lote_id}/imagens/0", headers=b).status_code == 404
    assert http.delete(f"/api/lotes/{lote_id}", headers=b).status_code == 404
    assert http.get(f"/api/lotes/{lote_id}", headers=a).status_code == 200
    assert http.get("/api/avaliacoes", headers=a | {"Host": "invasor.test",
        "X-Forwarded-Host": "api.example.test"}).status_code == 403


def test_sessao_e_resultados_sobrevivem_a_reinicio_da_aplicacao(publico):
    http, _ = publico
    credencial = sessao(http)
    criada = http.post("/api/avaliacoes", headers=credencial, json={
        "titulo": "Persistência fictícia", "alternativas": {str(i): "A" for i in range(1, 51)},
        "confirmado": True, "operacao_id": uuid4().hex})
    assert criada.status_code == 201
    with TestClient(criar_app(), base_url="http://api.example.test",
                    client=("192.0.2.10", 1234)) as reiniciada:
        provas = reiniciada.get("/api/avaliacoes", headers=credencial)
        assert provas.status_code == 200
        assert [p["id"] for p in provas.json()] == [criada.json()["id"]]
    assert http.get("/api/avaliacoes?token=" + credencial["Authorization"].split()[1]).status_code == 401


def test_publico_recusa_projeto_operacional_e_configuracao_incompleta(publico, monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "corretor-gabaritos-v2")
    with pytest.raises(ValueError, match="projeto Firebase exclusivo"):
        criar_app()
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "projeto-publico-isolado")
    monkeypatch.delenv("PUBLIC_SESSION_KEY")
    with pytest.raises(ValueError, match="PUBLIC_SESSION_KEY"):
        criar_app()


def test_zip_publico_misto_pdf_multipagina_restrito_a_sessao(publico):
    http, _ = publico
    a, b = sessao(http), sessao(http)
    imagem = cv2.imencode(".png", cartao({(1, 0): "cheia"}))[1].tobytes()
    with pymupdf.open() as documento:
        for _ in range(2):
            pagina = documento.new_page(width=850, height=1100)
            pagina.insert_image(pagina.rect, stream=imagem)
        pdf = documento.tobytes()
    buffer = BytesIO()
    with ZipFile(buffer, "w") as arquivo:
        arquivo.writestr("subpasta/cartoes.pdf", pdf)
        arquivo.writestr("subpasta/cartao.png", imagem)
    resposta = http.post("/api/lotes/zip", headers=a, files={"arquivo": ("misto.zip", buffer.getvalue())})
    assert resposta.status_code == 200, resposta.text
    lote = resposta.json()
    assert lote["total"] == 3
    pdfs = [item for item in lote["imagens"] if item["nome"].endswith(".pdf")]
    assert [item["pagina"] for item in pdfs] == [1, 2]
    assert http.get(f"/api/lotes/{lote['lote_id']}/imagens/{pdfs[1]['indice']}", headers=a).status_code == 200
    assert http.get(f"/api/lotes/{lote['lote_id']}/imagens/{pdfs[1]['indice']}", headers=b).status_code == 404


def test_zip_publico_respeita_limite_http(publico):
    http, _ = publico
    credencial = sessao(http)
    resposta = http.post("/api/lotes/zip", headers=credencial,
                         files={"arquivo": ("excessivo.zip", b"x" * (9 * 1024 * 1024))})
    assert resposta.status_code == 413


def test_publico_limita_gravacoes_anonimas(publico):
    http, _ = publico
    credencial = sessao(http)
    resultados = []
    for indice in range(7):
        resposta = http.post("/api/avaliacoes", headers=credencial, json={
            "titulo": f"Prova fictícia {indice}",
            "alternativas": {str(i): "A" for i in range(1, 51)},
            "confirmado": True, "operacao_id": uuid4().hex})
        resultados.append(resposta.status_code)
    assert resultados == [201] * 6 + [429]
