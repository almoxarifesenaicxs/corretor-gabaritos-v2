import pytest
from fastapi.testclient import TestClient

from app.main import criar_app


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.delenv("SERVIR_FRONTEND", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)


def cliente(app):
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def test_backend_sem_frontend(tmp_path):
    with cliente(criar_app(pasta_frontend=tmp_path / "ausente")) as http:
        assert http.get("/api/health").json() == {"status": "ok"}
        assert http.get("/interface/").status_code == 404
        assert "/api/correcoes/processar" in http.get("/openapi.json").json()["paths"]


def test_interface_local_e_config_publica():
    with cliente(criar_app()) as http:
        assert http.get("/interface/").status_code == 200
        config = http.get("/interface/js/config.mjs")
        assert config.status_code == 200
        assert 'const API_PUBLICA = "https://corretor-gabaritos-8yal.onrender.com"' in config.text
        assert '["localhost", "127.0.0.1"]' in config.text
        assert 'globalThis.location?.hostname' in config.text
        assert 'export const API_BASE_URL = ambienteLocal ? "" : API_PUBLICA;' in config.text
        assert http.get("/interface/tests/unit.test.mjs").status_code == 404


def test_frontend_desativado_explicitamente(monkeypatch):
    monkeypatch.setenv("SERVIR_FRONTEND", "false")
    with cliente(criar_app()) as http:
        assert http.get("/api/health").status_code == 200
        assert http.get("/interface/").status_code == 404


def test_frontend_obrigatorio_ausente_falha(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVIR_FRONTEND", "true")
    with pytest.raises(RuntimeError):
        criar_app(pasta_frontend=tmp_path / "ausente")


@pytest.mark.parametrize("origens,esperado", [("http://127.0.0.1", 200), ("", 400)])
def test_preflight_origem_autorizada_ou_nao(monkeypatch, origens, esperado):
    monkeypatch.setenv("CORS_ORIGINS", origens)
    with cliente(criar_app()) as http:
        resposta = http.options("/api/correcoes/processar", headers={
            "Origin": "http://127.0.0.1", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        assert resposta.status_code == esperado
        assert resposta.headers.get("access-control-allow-origin") == (
            "http://127.0.0.1" if esperado == 200 else None)


def test_cors_nao_libera_acesso_remoto_ou_outra_origem(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://interface.example,http://127.0.0.1")
    api = criar_app()
    with cliente(api) as http:
        for metodo in ("GET", "POST", "OPTIONS"):
            resposta = http.request(metodo, "/api/avaliacoes", headers={
                "Origin": "https://interface.example", "Access-Control-Request-Method": "POST"})
            assert resposta.status_code == 403
            assert "access-control-allow-origin" not in resposta.headers
        assert http.get("/api/health", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    with TestClient(api, base_url="http://127.0.0.1", client=("192.0.2.1", 50000)) as http:
        assert http.get("/api/avaliacoes").status_code == 403


def test_cors_restringe_metodos_e_headers(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://127.0.0.1")
    with cliente(criar_app()) as http:
        for metodo, header in [("DELETE", "content-type"), ("POST", "x-nao-permitido")]:
            assert http.options("/api/avaliacoes", headers={"Origin": "http://127.0.0.1",
                "Access-Control-Request-Method": metodo,
                "Access-Control-Request-Headers": header}).status_code == 400


@pytest.mark.parametrize("origem", ["*", "https://*.example", "null", "https://site.example/path",
    "https://user:secret@site.example", "https://site.example?x=1", "https://site.example:abc"])
def test_config_cors_invalida_falha(monkeypatch, origem):
    monkeypatch.setenv("CORS_ORIGINS", origem)
    with pytest.raises(ValueError):
        criar_app()
