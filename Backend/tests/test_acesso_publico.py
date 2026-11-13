"""Modo público explícito, com API e Firestore simulados."""
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.main import criar_app
from app.routes import interface
from app.seguranca import LIMITE_CORPO_UPLOAD


@pytest.fixture
def configuracao(monkeypatch, tmp_path):
    credencial = tmp_path / "adc-ficticio.json"
    credencial.write_text("{}")
    valores = {
        "APP_AMBIENTE": "publico", "FIREBASE_PROJECT_ID": "projeto-publico-teste",
        "FIRESTORE_MODO": "real", "CORS_ORIGINS": "https://frontend.example",
        "ALLOWED_HOSTS": "api.example", "INTEGRIDADE_CHAVE": "0123456789abcdef" * 4,
        "GOOGLE_APPLICATION_CREDENTIALS": str(credencial), "SERVIR_FRONTEND": "false",
    }
    for nome, valor in valores.items():
        monkeypatch.setenv(nome, valor)
    for nome in ("ADMIN_UIDS", "FIREBASE_AUTH_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST",
                 "FORWARDED_ALLOW_IPS"):
        monkeypatch.delenv(nome, raising=False)


@pytest.fixture
def servidor(configuracao, monkeypatch):
    from app import autenticacao
    proibido = Mock(side_effect=AssertionError("Autenticação Firebase não deve ser chamada"))
    monkeypatch.setattr(autenticacao, "verificar_token", proibido)
    monkeypatch.setattr(autenticacao, "_app_auth", proibido)
    api = criar_app()
    repo = Mock()
    repo.listar_provas.return_value = []
    api.dependency_overrides[interface.obter_persistencia] = lambda: repo
    with TestClient(api, base_url="http://api.example", client=("192.0.2.10", 50000)) as http:
        yield api, http, repo
    proibido.assert_not_called()


def test_dashboard_anônimo_pode_consultar_dados(servidor):
    api, http, repo = servidor
    resposta = http.get("/api/avaliacoes", headers={"Origin": "https://frontend.example"})
    assert resposta.status_code == 200
    assert resposta.json() == []
    assert resposta.headers["access-control-allow-origin"] == "https://frontend.example"
    repo.listar_provas.assert_called_once()
    assert "/api/auth/me" not in [getattr(rota, "path", "") for rota in api.routes]


def test_lote_zip_nao_e_exposto_no_modo_publico(servidor):
    _, http, repo = servidor
    assert http.get("/api/lotes/qualquer").status_code == 404
    assert http.post("/api/lotes/zip", files={"arquivo": ("teste.zip", b"PK")}).status_code == 404
    repo.salvar_correcao.assert_not_called()


def test_host_e_origem_continuam_restritos(servidor):
    _, http, repo = servidor
    assert http.get("/api/avaliacoes", headers={"Host": "invasor.example"}).status_code == 403
    assert http.get("/api/avaliacoes", headers={"Origin": "https://invasor.example"}).status_code == 403
    assert http.get("/api/avaliacoes", headers={"X-Forwarded-Host": "invasor.example"}).status_code == 200
    repo.listar_provas.assert_called_once()


def test_post_sem_login_preserva_validacao_e_limite_de_upload(servidor):
    _, http, _ = servidor
    origem = {"Origin": "https://frontend.example"}
    assert http.post("/api/avaliacoes", headers=origem, json={}).status_code == 422
    resposta = http.post("/api/correcoes/processar", headers={**origem,
        "Content-Length": str(LIMITE_CORPO_UPLOAD + 1),
        "Content-Type": "multipart/form-data; boundary=teste"})
    assert resposta.status_code == 413
    assert resposta.headers["access-control-allow-origin"] == "https://frontend.example"


def test_homologacao_nao_e_liberada(configuracao, monkeypatch):
    monkeypatch.setenv("APP_AMBIENTE", "homologacao")
    with TestClient(criar_app(), base_url="http://api.example",
                    client=("192.0.2.10", 50000)) as http:
        assert http.get("/api/health").status_code == 200
        assert http.get("/api/avaliacoes").status_code == 403
        assert http.post("/api/lotes/zip", files={"arquivo": ("teste.zip", b"PK")}).status_code == 403


def test_local_publico_preserva_loopback_sem_login(monkeypatch):
    monkeypatch.setenv("APP_AMBIENTE", "local_publico")
    monkeypatch.setenv("FIRESTORE_MODO", "emulador")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo-publico-local")
    api = criar_app()
    repo = Mock()
    repo.listar_provas.return_value = []
    api.dependency_overrides[interface.obter_persistencia] = lambda: repo
    with TestClient(api, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as http:
        assert http.get("/api/avaliacoes").status_code == 200
    with TestClient(api, base_url="http://127.0.0.1", client=("192.0.2.10", 50000)) as remoto:
        assert remoto.get("/api/avaliacoes").status_code == 403
    repo.listar_provas.assert_called_once()


def test_local_publico_nao_aceita_firestore_real(monkeypatch):
    monkeypatch.setenv("APP_AMBIENTE", "local_publico")
    monkeypatch.setenv("FIRESTORE_MODO", "real")
    with pytest.raises(ValueError, match="emulador"):
        criar_app()


@pytest.mark.parametrize("nome,valor", [
    ("FIRESTORE_MODO", "emulador"), ("FIREBASE_PROJECT_ID", ""),
    ("CORS_ORIGINS", ""), ("ALLOWED_HOSTS", ""),
    ("INTEGRIDADE_CHAVE", ""), ("GOOGLE_APPLICATION_CREDENTIALS", ""),
    ("SERVIR_FRONTEND", "true"), ("FORWARDED_ALLOW_IPS", "*"),
])
def test_modo_publico_falha_sem_configuracao_critica(configuracao, monkeypatch, nome, valor):
    monkeypatch.setenv(nome, valor)
    with pytest.raises(ValueError):
        criar_app()


def test_firestore_publico_exige_modo_explicito_e_nao_abre_conexao_real(servidor, monkeypatch):
    api, http, repo = servidor
    api.dependency_overrides.clear()
    aberto = Mock()

    @contextmanager
    def conectar(**kwargs):
        aberto(**kwargs)
        yield object()

    monkeypatch.setattr(interface, "conectar_firestore", conectar)
    monkeypatch.setattr(interface, "Persistencia", lambda _: repo)
    assert http.get("/api/avaliacoes").status_code == 200
    aberto.assert_called_once_with(emulador=False)


def test_documentacao_da_api_indisponivel(servidor):
    _, http, _ = servidor
    for caminho in ("/docs", "/redoc", "/openapi.json", "/interface/"):
        assert http.get(caminho).status_code == 404
