"""Produção simulada: sem ADC real, rede Firebase ou escrita no Firestore."""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from firebase_admin import auth

from app import autenticacao, seguranca
from app.main import criar_app
from app.routes import interface
from app.services import integridade


@pytest.fixture
def configuracao(monkeypatch, tmp_path):
    credencial = tmp_path / "adc-ficticio.json"
    credencial.write_text("{}")  # Não é credencial: carregador abaixo é simulado.
    valores = {
        "APP_AMBIENTE": "producao", "FIREBASE_PROJECT_ID": "projeto-auth-teste",
        "FIRESTORE_MODO": "real", "ADMIN_UIDS": "administrador",
        "CORS_ORIGINS": "https://frontend.example", "ALLOWED_HOSTS": "api.example",
        "INTEGRIDADE_CHAVE": "0123456789abcdef" * 4,
        "GOOGLE_APPLICATION_CREDENTIALS": str(credencial), "SERVIR_FRONTEND": "false",
    }
    for nome, valor in valores.items():
        monkeypatch.setenv(nome, valor)
    for nome in ("FIREBASE_AUTH_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST", "FORWARDED_ALLOW_IPS"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setattr(integridade, "_CHAVE", integridade._CHAVE)
    app_auth = MagicMock()
    monkeypatch.setattr(autenticacao, "_app_auth", app_auth)
    verificar = MagicMock(return_value={"uid": "administrador"})
    monkeypatch.setattr(auth, "verify_id_token", verificar)
    return verificar, app_auth


@pytest.fixture
def servidor(configuracao):
    api = criar_app()
    repo = MagicMock()
    repo.listar_provas.return_value = []
    api.dependency_overrides[interface.obter_persistencia] = lambda: repo
    # Simula HTTP entre proxy TLS e aplicação, sem confiar nos headers de proxy.
    with TestClient(api, base_url="http://api.example", client=("192.0.2.10", 50000)) as http:
        yield api, http, configuracao[0], repo


BEARER = {"Authorization": "Bearer token-ficticio", "Origin": "https://frontend.example"}


def test_producao_autorizada_e_cors(servidor):
    _, http, verificar, repo = servidor
    resposta = http.get("/api/avaliacoes", headers=BEARER)
    assert resposta.status_code == 200
    assert resposta.headers["access-control-allow-origin"] == "https://frontend.example"
    assert verificar.call_count == 1  # Middleware + dependência não duplicam validação.
    assert verificar.call_args.kwargs["check_revoked"] is True
    repo.listar_provas.assert_called_once()


@pytest.mark.parametrize("caso,status", [("ausente", 401), ("invalido", 401),
    ("expirado", 401), ("sem_permissao", 403)])
def test_todas_rotas_protegidas_em_producao(servidor, caso, status):
    api, http, verificar, repo = servidor
    headers = dict(BEARER)
    if caso == "ausente":
        del headers["Authorization"]
    elif caso == "invalido":
        verificar.side_effect = auth.InvalidIdTokenError("invalido")
    elif caso == "expirado":
        verificar.side_effect = auth.ExpiredIdTokenError("expirado", None)
    else:
        verificar.return_value = {"uid": "outro"}
    for rota in api.routes:
        if isinstance(rota, APIRoute) and rota.path.startswith("/api/") and rota.path != "/api/health":
            caminho = rota.path.replace("{aluno_id}", "aluno").replace("{prova_id}", "prova")
            resposta = http.request(next(iter(rota.methods)), caminho, headers=headers)
            assert resposta.status_code == status, caminho
            assert resposta.headers["access-control-allow-origin"] == "https://frontend.example"
    repo.listar_provas.assert_not_called()


def test_preflight_nao_executa_operacao(servidor):
    _, http, verificar, repo = servidor
    headers = {"Origin": "https://frontend.example", "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "authorization,content-type"}
    assert http.options("/api/correcoes/processar", headers=headers).status_code == 200
    verificar.assert_not_called()
    repo.listar_provas.assert_not_called()
    headers["Access-Control-Request-Method"] = "DELETE"
    assert http.options("/api/avaliacoes", headers=headers).status_code == 400


@pytest.mark.parametrize("origem", ["https://invasor.example", "null", "https://frontend.example.invasor.test"])
def test_origem_nao_autorizada_bloqueia_antes_do_token(servidor, origem):
    _, http, verificar, _ = servidor
    for metodo in ("GET", "POST", "OPTIONS"):
        resposta = http.request(metodo, "/api/avaliacoes", headers={**BEARER, "Origin": origem,
            "Access-Control-Request-Method": "POST"})
        assert resposta.status_code == 403
        assert "access-control-allow-origin" not in resposta.headers
    verificar.assert_not_called()


def test_proxy_nao_concede_acesso_nem_altera_host_ou_esquema(servidor):
    api, http, verificar, _ = servidor
    encaminhados = {"X-Forwarded-For": "127.0.0.1, 10.0.0.1", "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "api.example", "Forwarded": "for=127.0.0.1;proto=https"}
    assert http.get("/api/avaliacoes", headers=encaminhados).status_code == 401
    verificar.assert_not_called()
    assert http.get("/api/avaliacoes", headers={**BEARER, **encaminhados, "Host": "invasor.example"}).status_code == 403
    verificar.assert_not_called()
    # Rota apenas nesta instância de teste: observa o scope após sanitização.
    @api.get("/api/inspecao-teste")
    def inspecao(request: Request):
        return {"ip": request.client.host, "scheme": request.url.scheme,
                "headers": [k for k in request.headers if k.startswith("x-forwarded-") or k == "forwarded"]}
    resposta = http.get("/api/inspecao-teste", headers={**BEARER, **encaminhados})
    assert resposta.json() == {"ip": "192.0.2.10", "scheme": "http", "headers": []}
    assert http.get("/api/inspecao-teste").status_code == 401  # Rotas futuras também protegidas.


def test_cabecalhos_ambiguos(servidor):
    _, http, verificar, _ = servidor
    assert http.get("/api/auth/me", headers=[("Authorization", "Bearer a"),
        ("Authorization", "Bearer b")]).status_code == 400
    verificar.assert_not_called()


def test_limites_de_upload_e_concorrencia_preservados(servidor, monkeypatch):
    _, http, _, _ = servidor
    assert http.post("/api/correcoes/processar", headers={**BEARER,
        "Content-Length": str(seguranca.LIMITE_CORPO_UPLOAD + 1),
        "Content-Type": "multipart/form-data; boundary=teste"}).status_code == 413
    bloqueio = MagicMock()
    bloqueio.acquire.return_value = False
    monkeypatch.setattr(seguranca, "_PROCESSAMENTOS", bloqueio)
    assert http.post("/api/correcoes/processar", headers=BEARER,
        files={"arquivo": ("cartao.png", b"imagem")}).status_code == 503


def test_autenticacao_antes_de_receber_upload(servidor):
    _, http, _, _ = servidor
    resposta = http.post("/api/correcoes/processar", headers={
        "Content-Length": str(seguranca.LIMITE_CORPO_UPLOAD + 1)})
    assert resposta.status_code == 401  # Nem chega ao parser/limite do corpo.


def test_firestore_remoto_exige_marca_interna_de_autorizacao(servidor, monkeypatch):
    api, http, _, repo = servidor
    api.dependency_overrides.clear()
    aberto = MagicMock()
    @contextmanager
    def conectar(**kwargs):
        aberto(**kwargs)
        yield object()
    monkeypatch.setattr(interface, "conectar_firestore", conectar)
    monkeypatch.setattr(interface, "Persistencia", lambda _: repo)
    assert http.get("/api/avaliacoes", headers=BEARER).status_code == 200
    aberto.assert_called_once_with(emulador=False)
    request = Request({"type": "http", "app": api, "state": {}, "headers": []})
    with pytest.raises(interface.HTTPException) as erro:
        next(interface.obter_persistencia(request))
    assert erro.value.status_code == 403


def test_saude_publica_sem_docs_ou_interface(servidor):
    _, http, _, _ = servidor
    assert http.get("/api/health").json() == {"status": "ok"}
    for caminho in ("/docs", "/redoc", "/openapi.json", "/interface/"):
        assert http.get(caminho, headers=BEARER).status_code == 404


@pytest.mark.parametrize("nome,valor", [
    ("APP_AMBIENTE", "prod"), ("APP_AMBIENTE", ""), ("FIREBASE_PROJECT_ID", ""),
    ("FIREBASE_PROJECT_ID", "demo-teste"), ("FIRESTORE_MODO", "emulador"),
    ("ADMIN_UIDS", ""), ("ADMIN_UIDS", "*"), ("CORS_ORIGINS", ""),
    ("CORS_ORIGINS", "*"), ("CORS_ORIGINS", "http://frontend.example"),
    ("ALLOWED_HOSTS", ""), ("ALLOWED_HOSTS", "*.example"),
    ("INTEGRIDADE_CHAVE", ""), ("INTEGRIDADE_CHAVE", "0" * 64),
    ("GOOGLE_APPLICATION_CREDENTIALS", ""), ("SERVIR_FRONTEND", "true"),
    ("FIRESTORE_EMULATOR_HOST", "localhost:8080"),
    ("FIREBASE_AUTH_EMULATOR_HOST", "localhost:9099"), ("FORWARDED_ALLOW_IPS", "*"),
])
def test_producao_falha_sem_configuracao_segura(configuracao, monkeypatch, nome, valor):
    monkeypatch.setenv(nome, valor)
    with pytest.raises(ValueError):
        criar_app()


def test_adc_invalido_falha_sem_vazar_detalhes(configuracao):
    configuracao[1].side_effect = RuntimeError("caminho-privado")
    with pytest.raises(ValueError, match="Credenciais") as erro:
        criar_app()
    assert "caminho-privado" not in str(erro.value)


def test_chave_persistente_preserva_comprovante(configuracao):
    criar_app()
    assinatura = integridade.assinar_respostas({"resposta": "A"}, {"gabarito": "A"})
    integridade._CHAVE = b"simula-novo-processo"
    criar_app()
    integridade.conferir_respostas(assinatura, {"resposta": "A"}, {"gabarito": "A"})


def test_local_e_padrao_continuam_fechados(configuracao, monkeypatch):
    monkeypatch.delenv("APP_AMBIENTE")
    api = criar_app()
    assert api.state.ambiente == "local"
    with TestClient(api, base_url="http://api.example", client=("192.0.2.10", 50000)) as http:
        assert http.get("/api/auth/me", headers=BEARER).status_code == 403
    configuracao[0].assert_not_called()
