from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.main import criar_app
from app import autenticacao, seguranca
from app.routes import interface


@pytest.fixture
def configuracao(monkeypatch):
    monkeypatch.setenv("APP_AMBIENTE", "homologacao")
    monkeypatch.setenv("ALLOWED_HOSTS", "api-teste.onrender.com,api.example.test")
    for nome in ("SERVIR_FRONTEND", "FORWARDED_ALLOW_IPS", "CORS_ORIGINS", "FIREBASE_PROJECT_ID",
                 "ADMIN_UIDS", "GOOGLE_APPLICATION_CREDENTIALS", "INTEGRIDADE_CHAVE",
                 "FIRESTORE_MODO", "FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST"):
        monkeypatch.delenv(nome, raising=False)
    import firebase_admin
    import google.auth
    proibido = Mock(side_effect=AssertionError("Firebase não deve ser inicializado ou consultado"))
    monkeypatch.setattr(firebase_admin, "initialize_app", proibido)
    monkeypatch.setattr(google.auth, "default", proibido)
    monkeypatch.setattr(autenticacao, "_app_auth", proibido)
    monkeypatch.setattr(autenticacao, "verificar_token", proibido)
    monkeypatch.setattr(interface, "conectar_firestore", proibido)
    yield proibido
    proibido.assert_not_called()


@pytest.fixture
def http(configuracao, tmp_path):
    with TestClient(criar_app(pasta_frontend=tmp_path / "ausente"),
                    base_url="http://api-teste.onrender.com", client=("192.0.2.10", 1234)) as cliente:
        yield cliente


def test_health_remoto_sem_firebase(http):
    resposta = http.get("/api/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}
    assert http.get("/api/health", headers={"Host": "API.EXAMPLE.TEST"}).status_code == 200


@pytest.mark.parametrize("host", ["invasor.test", "api-teste.onrender.com.invasor.test",
    "api-teste.onrender.com:443", "localhost", "", "api-teste.onrender.com."])
def test_host_nao_autorizado(http, host):
    assert http.get("/api/health", headers={"Host": host}).status_code == 403


def test_host_duplicado(http):
    assert http.get("/api/health", headers=[("Host", "api-teste.onrender.com"),
        ("Host", "invasor.test")]).status_code == 400


def test_proxy_nao_concede_acesso(http):
    encaminhados = {"X-Forwarded-For": "127.0.0.1", "X-Forwarded-Host": "api-teste.onrender.com",
                    "X-Forwarded-Proto": "https", "Forwarded": "for=127.0.0.1;host=api-teste.onrender.com"}
    assert http.get("/api/health", headers=encaminhados).status_code == 200
    assert http.get("/api/health", headers={**encaminhados, "Host": "invasor.test"}).status_code == 403
    assert http.get("/api/avaliacoes", headers=encaminhados).status_code == 403


@pytest.mark.parametrize("metodo", ["HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_somente_get_health(http, metodo):
    assert http.request(metodo, "/api/health").status_code == 403


@pytest.mark.parametrize("token", [None, "token-simulado-autorizado"])
def test_todas_rotas_administrativas_bloqueadas(configuracao, monkeypatch, token):
    # Obter inventário das rotas existentes sem alterar produção ou consultar Firebase.
    monkeypatch.setenv("APP_AMBIENTE", "local")
    local = criar_app()
    monkeypatch.setenv("APP_AMBIENTE", "homologacao")
    autorizar = Mock(return_value={"uid": "admin-simulado"})
    monkeypatch.setattr(seguranca, "autorizar_credencial", autorizar)
    monkeypatch.setattr(autenticacao, "autorizar_credencial", autorizar)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with TestClient(criar_app(), base_url="http://api-teste.onrender.com",
                    client=("192.0.2.10", 1234)) as cliente:
        rotas = local.openapi()["paths"]
        assert "/api/correcoes/processar" in rotas
        assert "/api/avaliacoes" in rotas
        for rota, operacoes in rotas.items():
            if not rota.startswith("/api/") or rota == "/api/health":
                continue
            caminho = rota.replace("{prova_id}", "prova").replace("{aluno_id}", "aluno")
            for metodo in operacoes:
                assert cliente.request(metodo, caminho, headers=headers).status_code == 403, caminho
    autorizar.assert_not_called()


@pytest.mark.parametrize("caminho", ["/", "/docs", "/redoc", "/openapi.json", "/interface/",
                                      "/api/health/", "/api/health/extra"])
def test_infraestrutura_adicional_indisponivel(http, caminho):
    assert http.get(caminho, follow_redirects=False).status_code == 403
    assert [rota.path for rota in http.app.routes] == ["/api/health"]


@pytest.mark.parametrize("hosts", ["", "*", "https://api.example.test", "api.example.test:443",
    "api.example.test,", "api..test", "-api.test", "api_.test"])
def test_config_host_invalida_falha(configuracao, monkeypatch, hosts):
    monkeypatch.setenv("ALLOWED_HOSTS", hosts)
    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        criar_app()


@pytest.mark.parametrize("nome,valor", [("SERVIR_FRONTEND", "true"), ("FORWARDED_ALLOW_IPS", "*")])
def test_config_insegura_falha(configuracao, monkeypatch, nome, valor):
    monkeypatch.setenv(nome, valor)
    with pytest.raises(ValueError):
        criar_app()


def test_rejeicao_nao_le_corpo(http, monkeypatch):
    receber = Mock(side_effect=AssertionError("Corpo administrativo não deve ser processado"))
    monkeypatch.setattr(seguranca.ProtecaoLocal, "receber_corpo", receber)
    assert http.post("/api/correcoes/processar", files={"arquivo": ("teste.png", b"simulado")}).status_code == 403
    receber.assert_not_called()
