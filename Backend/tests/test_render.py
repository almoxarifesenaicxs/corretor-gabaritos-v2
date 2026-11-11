import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app, criar_app
from app.routes import interface, correcoes
from test_correcao import gabarito, respostas

RAIZ = Path(__file__).resolve().parents[2]


def test_blueprint_preserva_modo_local_e_comandos_seguros():
    service = yaml.safe_load((RAIZ / "render.yaml").read_text())["services"][0]
    variaveis = {item["key"]: item for item in service["envVars"]}
    assert service["rootDir"] == "Backend"
    assert service["autoDeployTrigger"] == "off"
    assert variaveis["APP_AMBIENTE"]["value"] == "local"
    assert variaveis["SERVIR_FRONTEND"]["value"] == "false"
    assert variaveis["PYTHON_VERSION"]["value"] == (RAIZ / "Backend/.python-version").read_text().strip()
    assert service["startCommand"] == 'python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --no-proxy-headers --workers 1'
    assert "--only-binary=:all:" in service["buildCommand"]
    assert "python scripts/verificar_runtime.py" in service["buildCommand"]
    assert service["healthCheckPath"] == "/api/health"
    for nome in ("INTEGRIDADE_CHAVE", "GOOGLE_APPLICATION_CREDENTIALS", "ADMIN_UIDS", "FIREBASE_PROJECT_ID"):
        assert variaveis[nome] == {"key": nome, "sync": False}


def test_health_sem_frontend_autenticacao_ou_firestore(monkeypatch, tmp_path):
    from app import autenticacao
    abrir = MagicMock(side_effect=AssertionError("Firestore não deve ser consultado"))
    validar = MagicMock(side_effect=AssertionError("Token não deve ser validado"))
    monkeypatch.setattr(interface, "conectar_firestore", abrir)
    monkeypatch.setattr(autenticacao, "verificar_token", validar)
    monkeypatch.setenv("APP_AMBIENTE", "local")
    monkeypatch.setenv("SERVIR_FRONTEND", "false")
    with TestClient(criar_app(pasta_frontend=tmp_path / "ausente"),
                    base_url="http://127.0.0.1", client=("127.0.0.1", 10000)) as http:
        assert http.get("/api/health").json() == {"status": "ok"}
        assert http.get("/interface/").status_code == 404
    abrir.assert_not_called()
    validar.assert_not_called()


@pytest.mark.parametrize("rota,modulo,servico", [
    ("/api/correcoes/processar", correcoes, "reconhecer_arquivo"),
    ("/api/gabaritos/reconhecer", interface, "reconhecer_arquivo"),
    ("/api/alunos/reconhecer-nome", interface, "carregar_imagem"),
])
@pytest.mark.parametrize("falha", [False, True])
def test_temporarios_removidos_em_sucesso_e_erro(monkeypatch, tmp_path, rota, modulo, servico, falha):
    caminhos = []
    def temporario(**kwargs):
        pasta = TemporaryDirectory(dir=tmp_path, **kwargs)
        caminhos.append(Path(pasta.name))
        return pasta
    def processar(caminho):
        assert Path(caminho).is_file()
        if falha:
            raise RuntimeError("Falha interna simulada")
        return respostas()
    monkeypatch.setattr(modulo, "TemporaryDirectory", temporario)
    monkeypatch.setattr(modulo, servico, processar)
    monkeypatch.setattr(interface, "ler_nome", lambda _: {"estado": "nao_identificado"})
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 10000)) as http:
        resposta = http.post(rota, files={"arquivo": ("cartao.pdf", b"%PDF-conteudo-simulado", "application/pdf")},
                             data={"gabarito": json.dumps(gabarito())})
    assert resposta.status_code == (500 if falha else 200)
    assert caminhos and all(not caminho.exists() for caminho in caminhos)
    assert "Falha interna simulada" not in resposta.text
