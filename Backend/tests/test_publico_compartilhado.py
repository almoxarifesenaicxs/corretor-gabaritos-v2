"""Acesso público compartilhado com Firestore simulado, sem conexão externa."""

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

from app import autenticacao, seguranca
from app.main import criar_app
from app.routes import interface, lotes
from app.services.lotes_zip import LotesZIP
from test_persistencia import banco
from test_reconhecimento import cartao


@pytest.fixture
def publico(monkeypatch, tmp_path, banco):
    seguranca._PUBLIC_JANELAS.clear()
    repo, dados = banco
    certificado = tmp_path / "certificado-ficticio.json"
    certificado.write_text("{}", encoding="utf-8")
    variaveis = {
        "APP_AMBIENTE": "publico_compartilhado",
        "ALLOWED_HOSTS": "api.example.test",
        "CORS_ORIGINS": "https://site.example.test",
        "SERVIR_FRONTEND": "false",
        "FIRESTORE_MODO": "real",
        "FIREBASE_PROJECT_ID": "projeto-publico-dedicado",
        "FIREBASE_PRODUCTION_PROJECT_ID": "projeto-operacional-separado",
        "GOOGLE_APPLICATION_CREDENTIALS": str(certificado),
        "INTEGRIDADE_CHAVE": "0123456789abcdef" * 4,
        "LOTE_ZIP_MAX_MIB": "8", "LOTE_MAX_IMAGENS": "20",
        "LOTE_TOTAL_MAX_MIB": "50", "LOTE_PDF_MAX_PAGINAS": "10",
    }
    for nome, valor in variaveis.items():
        monkeypatch.setenv(nome, valor)
    for nome in ("FORWARDED_ALLOW_IPS", "FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST",
                 "ADMIN_UIDS", "PUBLIC_SESSION_KEY"):
        monkeypatch.delenv(nome, raising=False)
    from firebase_admin import credentials
    monkeypatch.setattr(credentials, "Certificate", Mock(return_value=SimpleNamespace(project_id="projeto-publico-dedicado")))
    auth = Mock(side_effect=AssertionError("Firebase Authentication não deve ser chamado"))
    monkeypatch.setattr(autenticacao, "_app_auth", auth)

    @contextmanager
    def simulado(*, emulador):
        assert emulador is False
        yield repo.cliente

    monkeypatch.setattr(interface, "conectar_firestore", simulado)
    zip_isolado = LotesZIP()
    monkeypatch.setattr(lotes, "lotes_zip", zip_isolado)
    app = criar_app(pasta_frontend=tmp_path / "frontend-ausente")
    with TestClient(app, base_url="http://api.example.test", client=("192.0.2.1", 1234)) as a, \
         TestClient(app, base_url="http://api.example.test", client=("198.51.100.2", 1234)) as b:
        yield a, b, dados
    for lote in zip_isolado._lotes.values():
        lote.pasta.cleanup()
    auth.assert_not_called()


def _avaliacao(http):
    resposta = http.post("/api/avaliacoes", json={
        "titulo": "Avaliação compartilhada fictícia",
        "alternativas": {str(i): "A" for i in range(1, 51)},
        "confirmado": True, "operacao_id": uuid4().hex,
    })
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["id"]


def test_dois_computadores_compartilham_avaliacao_aluno_correcao_e_exportacao(publico):
    a, b, dados = publico
    prova = _avaliacao(a)
    assert [p["id"] for p in b.get("/api/avaliacoes").json()] == [prova]
    assert len(b.get(f"/api/avaliacoes/{prova}/gabarito").json()["alternativas"]) == 50

    imagem = cv2.imencode(".png", cartao({(1, 0): "cheia"}))[1].tobytes()
    processada = b.post("/api/correcoes/processar",
                       files={"arquivo": ("cartao-ficticio.png", imagem)},
                       data={"gabarito": json.dumps({str(i): "A" for i in range(1, 51)}), "visual": "true"})
    assert processada.status_code == 200, processada.text
    leitura = processada.json()
    operacao = uuid4().hex
    entrada = {"prova_id": prova, "aluno": "ALUNA FICTÍCIA", "resultado": leitura["resultado"],
               "respostas": leitura["respostas"], "comprovante": leitura["comprovante"],
               "operacao_id": operacao, "confirmado": True}
    salvo = a.post("/api/correcoes/salvar", json=entrada)
    assert salvo.status_code == 201, salvo.text
    assert b.post("/api/correcoes/salvar", json=entrada).json() == salvo.json()
    assert len(b.get("/api/alunos").json()) == 1
    assert b.get(f"/api/operacoes/correcao/{operacao}").json()["estado"] == "confirmada"
    assert b.get("/api/correcoes/exportar").json()["resumo"]["total_correcoes"] == 1
    assert len([key for key in dados if key[0] == "correcoes"]) == 1
    assert not any(key[0].startswith("sessoes_publicas/") for key in dados)


def test_publico_nao_exige_sessao_mas_nao_disponibiliza_rotas_privadas(publico):
    a, _, _ = publico
    assert a.get("/api/health").status_code == 200
    assert a.get("/api/avaliacoes").status_code == 200
    assert a.get("/api/public/session").status_code == 404
    assert a.post("/api/public/session").status_code == 404
    for caminho in ("/docs", "/redoc", "/openapi.json", "/interface/", "/docs/firebase.md"):
        assert a.get(caminho).status_code == 404
    assert a.get("/api/avaliacoes", headers={"Host": "invasor.example.test",
        "X-Forwarded-Host": "api.example.test"}).status_code == 403


def test_registros_continuam_apos_reinicio_da_api_sem_sessao(publico):
    a, _, _ = publico
    prova = _avaliacao(a)
    with TestClient(criar_app(), base_url="http://api.example.test",
                    client=("203.0.113.3", 1234)) as reiniciada:
        resposta = reiniciada.get("/api/avaliacoes")
        assert resposta.status_code == 200
        assert [item["id"] for item in resposta.json()] == [prova]


def test_zip_pdf_multipagina_exige_token_somente_para_arquivos_temporarios(publico):
    a, b, _ = publico
    imagem = cv2.imencode(".png", cartao())[1].tobytes()
    with pymupdf.open() as documento:
        for _ in range(2):
            pagina = documento.new_page(width=850, height=1100)
            pagina.insert_image(pagina.rect, stream=imagem)
        pdf = documento.tobytes()
    memoria = BytesIO()
    with ZipFile(memoria, "w") as zip_arquivo:
        zip_arquivo.writestr("subpasta/cartoes.pdf", pdf)
        zip_arquivo.writestr("subpasta/cartao.png", imagem)
    importado = a.post("/api/lotes/zip", files={"arquivo": ("lote.zip", memoria.getvalue())})
    assert importado.status_code == 200, importado.text
    lote = importado.json()
    assert lote["total"] == 3
    assert [item["pagina"] for item in lote["imagens"] if item["nome"].endswith(".pdf")] == [1, 2]
    caminho = f"/api/lotes/{lote['lote_id']}"
    assert b.get(caminho).status_code == 404
    assert b.get(caminho + "/imagens/0").status_code == 404
    assert b.delete(caminho).status_code == 404
    headers = {"X-Lote-Token": lote["lote_token"]}
    assert b.get(caminho, headers=headers).status_code == 200
    imagem_pdf = b.get(caminho + "/imagens/1", headers=headers)
    assert imagem_pdf.status_code == 200
    assert imagem_pdf.headers["content-type"] == "image/jpeg"
    assert imagem_pdf.content.startswith(b"\xff\xd8\xff")
    assert b.delete(caminho, headers=headers).status_code == 204


def test_configuracao_falha_fechada_sem_projeto_dedicado_ou_chave(publico, monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "projeto-operacional-separado")
    with pytest.raises(ValueError, match="projeto Firebase exclusivo"):
        criar_app()
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "projeto-publico-dedicado")
    monkeypatch.delenv("INTEGRIDADE_CHAVE")
    with pytest.raises(ValueError, match="INTEGRIDADE_CHAVE"):
        criar_app()


def test_configuracao_rejeita_emulador_ou_credencial_de_outro_projeto(publico, monkeypatch):
    monkeypatch.setenv("FIRESTORE_MODO", "emulador")
    with pytest.raises(ValueError, match="Firestore real isolado"):
        criar_app()
    monkeypatch.setenv("FIRESTORE_MODO", "real")
    from firebase_admin import credentials
    monkeypatch.setattr(credentials, "Certificate", Mock(return_value=SimpleNamespace(project_id="outro-projeto")))
    with pytest.raises(ValueError, match="Credenciais do projeto público inválidas"):
        criar_app()


def test_limites_publicos_e_sem_exclusao_automatica(publico):
    a, _, dados = publico
    resultados = []
    for indice in range(7):
        resultados.append(a.post("/api/avaliacoes", json={
            "titulo": f"Avaliação fictícia {indice}",
            "alternativas": {str(i): "A" for i in range(1, 51)},
            "confirmado": True, "operacao_id": uuid4().hex,
        }).status_code)
    assert resultados == [201] * 6 + [429]
    assert len([key for key in dados if key[0] == "provas"]) == 6
