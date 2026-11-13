from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from firebase_admin import auth

from app import autenticacao
from app.main import criar_app
from app.routes.interface import obter_persistencia


@pytest.fixture
def contexto(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "projeto-teste-auth")
    monkeypatch.setenv("ADMIN_UIDS", "admin-teste")
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    monkeypatch.setattr(autenticacao, "_app_auth", lambda projeto: "app-simulado")
    verificar = MagicMock(return_value={"uid": "admin-teste"})
    monkeypatch.setattr(auth, "verify_id_token", verificar)
    api = criar_app()
    repo = MagicMock()
    repo.listar_provas.return_value = []
    api.dependency_overrides[obter_persistencia] = lambda: repo
    with TestClient(api, base_url="http://127.0.0.1", client=("127.0.0.1", 12345)) as http:
        yield http, verificar, repo, api


def test_administrador_autorizado(contexto):
    http, verificar, repo, _ = contexto
    assert http.get("/api/avaliacoes", headers={"Authorization": "Bearer token-simulado"}).status_code == 200
    verificar.assert_called_once_with("token-simulado", app="app-simulado", check_revoked=True)
    repo.listar_provas.assert_called_once()
    assert http.get("/api/auth/me", headers={"Authorization": "Bearer token-simulado"}).json() == {"uid": "admin-teste"}


@pytest.mark.parametrize("uid,lista", [("outro", "admin-teste"), ("admin-teste", ""), ("admin-teste", "*")])
def test_sem_permissao(contexto, monkeypatch, uid, lista):
    http, verificar, repo, _ = contexto
    monkeypatch.setenv("ADMIN_UIDS", lista)
    verificar.return_value = {"uid": uid, "admin": True, "email": "admin@example.test"}
    assert http.get("/api/avaliacoes", headers={"Authorization": "Bearer token-simulado"}).status_code == 403
    repo.listar_provas.assert_not_called()


@pytest.mark.parametrize("erro", [auth.InvalidIdTokenError("invalido"),
    auth.ExpiredIdTokenError("expirado", None), auth.RevokedIdTokenError("revogado"),
    auth.UserDisabledError("desativado")])
def test_token_invalido_expirado_revogado(contexto, erro):
    http, verificar, repo, _ = contexto
    verificar.side_effect = erro
    resposta = http.get("/api/avaliacoes", headers={"Authorization": "Bearer token-simulado"})
    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"
    repo.listar_provas.assert_not_called()


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer"])
def test_ausencia_de_bearer(contexto, header):
    http, verificar, _, _ = contexto
    assert http.get("/api/auth/me", headers={"Authorization": header} if header else {}).status_code == 401
    verificar.assert_not_called()


def test_todas_rotas_de_negocio_exigem_identidade(contexto):
    http, verificar, _, api = contexto
    from fastapi.routing import APIRoute
    for rota in api.routes:
        if isinstance(rota, APIRoute) and rota.path.startswith("/api/") and rota.path != "/api/health":
            caminho = rota.path.replace("{prova_id}", "prova").replace("{aluno_id}", "aluno")
            metodo = next(iter(rota.methods))
            assert http.request(metodo, caminho).status_code == 401, caminho
    verificar.assert_not_called()


def test_todas_rotas_de_negocio_negam_usuario_nao_autorizado(contexto):
    http, verificar, _, api = contexto
    verificar.return_value = {"uid": "nao-autorizado"}
    from fastapi.routing import APIRoute
    for rota in api.routes:
        if isinstance(rota, APIRoute) and rota.path.startswith("/api/") and rota.path != "/api/health":
            caminho = rota.path.replace("{prova_id}", "prova").replace("{aluno_id}", "aluno")
            assert http.request(next(iter(rota.methods)), caminho,
                headers={"Authorization": "Bearer token-simulado"}).status_code == 403, caminho


def test_protecao_local_antes_de_autenticacao(contexto):
    http, verificar, _, api = contexto
    for headers in [{"Origin": "https://externo.example"}, {"X-Forwarded-For": "127.0.0.1"}]:
        assert http.get("/api/auth/me", headers={**headers, "Authorization": "Bearer token-simulado"}).status_code == 403
    with TestClient(api, base_url="http://127.0.0.1", client=("192.0.2.1", 12345)) as remoto:
        assert remoto.get("/api/auth/me", headers={"Authorization": "Bearer token-simulado"}).status_code == 403
    verificar.assert_not_called()


def test_config_insegura_ou_indisponibilidade_falha_fechado(contexto, monkeypatch):
    http, verificar, _, _ = contexto
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "localhost:9099")
    assert http.get("/api/auth/me", headers={"Authorization": "Bearer token-simulado"}).status_code == 503
    verificar.assert_not_called()
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST")
    verificar.side_effect = RuntimeError("segredo-nao-deve-vazar")
    resposta = http.get("/api/auth/me", headers={"Authorization": "Bearer token-simulado"})
    assert resposta.status_code == 503
    assert "segredo" not in resposta.text


def test_saude_e_dashboard_estaticos_sem_token(contexto):
    http, verificar, _, _ = contexto
    assert http.get("/api/health").status_code == 200
    interface = http.get("/interface/").text
    assert 'id="sidebar"' in interface
    assert 'id="login-form"' in interface
    assert http.get("/interface/js/auth.mjs").status_code == 200
    verificar.assert_not_called()
