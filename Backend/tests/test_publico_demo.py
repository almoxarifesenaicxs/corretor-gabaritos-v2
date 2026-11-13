"""A demonstração pública não monta rotas persistentes nem inicia Firebase."""

from unittest.mock import Mock
import json

import cv2
import pymupdf

import pytest
from fastapi.testclient import TestClient

from app.main import criar_app
from app import autenticacao
from app.routes import interface
from test_reconhecimento import cartao
from app.routes.demo import GABARITO


@pytest.fixture
def demo(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_AMBIENTE", "publico_demo")
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.test")
    monkeypatch.setenv("CORS_ORIGINS", "https://site.example.test")
    for name in ("SERVIR_FRONTEND", "FORWARDED_ALLOW_IPS", "FIRESTORE_MODO",
                 "FIREBASE_PROJECT_ID", "GOOGLE_APPLICATION_CREDENTIALS",
                 "ADMIN_UIDS", "INTEGRIDADE_CHAVE", "FIRESTORE_EMULATOR_HOST",
                 "FIREBASE_AUTH_EMULATOR_HOST", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    forbidden = Mock(side_effect=AssertionError("Firebase não deve ser usado"))
    import firebase_admin
    import google.auth
    monkeypatch.setattr(firebase_admin, "initialize_app", forbidden)
    monkeypatch.setattr(google.auth, "default", forbidden)
    monkeypatch.setattr(autenticacao, "verificar_token", forbidden)
    monkeypatch.setattr(interface, "conectar_firestore", forbidden)
    with TestClient(criar_app(pasta_frontend=tmp_path / "missing"),
                    base_url="http://api.example.test", client=("192.0.2.10", 1234)) as client:
        yield client
    forbidden.assert_not_called()


def test_demo_dados_ficticios_sem_login_ou_firestore(demo):
    assert demo.get("/api/health").json() == {"status": "ok"}
    info = demo.get("/api/demo/info")
    assert info.status_code == 200 and info.json()["persistencia"] is False
    provas = demo.get("/api/avaliacoes")
    assert provas.status_code == 200 and len(provas.json()) == 1
    prova = provas.json()[0]
    gabarito = demo.get(f"/api/avaliacoes/{prova['id']}/gabarito")
    assert gabarito.status_code == 200 and len(gabarito.json()["alternativas"]) == 50
    assert demo.get("/api/alunos?pagina=true").json()["alunos"] == []
    assert demo.get("/api/alunos/correspondencias?nome=Teste").json()["exatos"] == []


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/avaliacoes"), ("POST", "/api/correcoes/salvar"),
    ("GET", "/api/correcoes/exportar"), ("GET", "/api/operacoes/correcao/qualquer"),
    ("GET", "/api/auth/me"), ("POST", "/api/lotes/zip"),
    ("POST", "/api/gabaritos/reconhecer"),
    ("DELETE", "/api/avaliacoes/demonstracao-50"),
])
def test_demo_bloqueia_dados_e_escrita(demo, method, path):
    assert demo.request(method, path).status_code in {403, 404, 405}


def test_demo_host_e_origem_explicitos(demo):
    assert demo.get("/api/avaliacoes", headers={"Host": "host-invasor.test"}).status_code == 403
    assert demo.get("/api/avaliacoes", headers={"Origin": "https://host-invasor.test"}).status_code == 403
    valid = demo.get("/api/avaliacoes", headers={"Origin": "https://site.example.test"})
    assert valid.status_code == 200
    assert valid.headers["access-control-allow-origin"] == "https://site.example.test"
    assert valid.headers["cache-control"] == "no-store"
    assert demo.get("/api/avaliacoes", headers={"Host": "host-invasor.test",
        "X-Forwarded-Host": "api.example.test"}).status_code == 403
    assert demo.post("/api/correcoes/salvar", headers={
        "Authorization": "Bearer token-ficticio"}).status_code == 404
    preflight = demo.options("/api/correcoes/processar", headers={
        "Origin": "https://site.example.test",
        "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 200
    blocked = demo.options("/api/correcoes/salvar", headers={
        "Origin": "https://site.example.test",
        "Access-Control-Request-Method": "POST"})
    assert blocked.status_code == 404


@pytest.mark.parametrize("formato", ["png", "jpg", "pdf"])
def test_demo_processa_cartao_real_sem_persistir(demo, formato):
    imagem = cartao({(1, 0): "cheia", (26, 1): "cheia"})
    png = cv2.imencode(".png", imagem)[1].tobytes()
    if formato == "pdf":
        with pymupdf.open() as documento:
            pagina = documento.new_page(width=850, height=1100)
            pagina.insert_image(pagina.rect, stream=png)
            conteudo = documento.tobytes()
    else:
        conteudo = cv2.imencode("." + formato, imagem)[1].tobytes()
    response = demo.post("/api/correcoes/processar", data={"gabarito": json.dumps(GABARITO),
                         "visual": "true"}, files={"arquivo": ("ficticio." + formato, conteudo)})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["respostas"]) == 50
    assert result["respostas"]["1"]["resposta"] == "A"
    assert "visualizacao" in result


@pytest.mark.parametrize("name,value", [
    ("FIRESTORE_MODO", "real"), ("FIRESTORE_MODO", "emulador"),
    ("GOOGLE_APPLICATION_CREDENTIALS", "private.json"),
    ("FIREBASE_PROJECT_ID", "real-project"), ("ADMIN_UIDS", "uid"),
])
def test_demo_recusa_configuracao_firebase(demo, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="publico_demo"):
        criar_app()
