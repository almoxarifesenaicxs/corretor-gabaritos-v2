"""Seleção real validada somente com conexão substituída; nunca há RPC real."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import firebase_admin
from fastapi.testclient import TestClient
import pytest

from app.database.firestore import usar_emulador_configurado, conectar_firestore
from app.main import app
from app.routes import interface


def configurar_real(monkeypatch):
    monkeypatch.setenv("FIRESTORE_MODO", "real")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "projeto-configuracao-simulada")
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)


def test_emulador_e_padrao_mesmo_com_credencial_configurada(monkeypatch):
    monkeypatch.delenv("FIRESTORE_MODO", raising=False)
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo-testes")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "arquivo-inexistente-nao-deve-ser-lido.json")
    assert usar_emulador_configurado() is True


@pytest.mark.parametrize("modo", ["", "producao", "firebase", "true"])
def test_modo_desconhecido_sem_fallback(monkeypatch, modo):
    monkeypatch.setenv("FIRESTORE_MODO", modo)
    abrir = MagicMock()
    monkeypatch.setattr(interface, "conectar_firestore", abrir)
    assert TestClient(app).get('/api/avaliacoes').status_code == 503
    abrir.assert_not_called()


@pytest.mark.parametrize("projeto,host", [(None, None), ("demo-testes", None),
                                        ("projeto-simulado", "127.0.0.1:8080"), (" ", None)])
def test_real_rejeita_configuracao_ambigua(monkeypatch, projeto, host):
    configurar_real(monkeypatch)
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    if projeto is not None:
        monkeypatch.setenv("FIREBASE_PROJECT_ID", projeto)
    if host is not None:
        monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", host)
    with pytest.raises(ValueError):
        usar_emulador_configurado()


@pytest.mark.parametrize("modo,emulador", [("emulador", True), ("real", False)])
def test_rota_seleciona_destino_sem_cliente_real(monkeypatch, modo, emulador):
    configurar_real(monkeypatch)
    if emulador:
        monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo-testes")
        monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    monkeypatch.setenv("FIRESTORE_MODO", modo)
    cliente = MagicMock()
    cliente.collection.return_value.stream.return_value = []
    @contextmanager
    def fake_conexao(**kwargs):
        assert kwargs == {"emulador": emulador}
        yield cliente
    abrir = MagicMock(side_effect=fake_conexao)
    monkeypatch.setattr(interface, "conectar_firestore", abrir)
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)) as http:
        resposta = http.get('/api/avaliacoes', headers={"Origin": "http://127.0.0.1:8000"})
    assert resposta.status_code == 200
    assert resposta.json() == []
    abrir.assert_called_once_with(emulador=emulador)


@pytest.mark.parametrize("peer,base_url,headers", [
    ("192.168.1.12", "http://127.0.0.1:8000", {}),
    ("127.0.0.1", "http://publico.example", {}),
    ("127.0.0.1", "http://127.0.0.1:8000", {"Origin": "https://outro.example"}),
    ("127.0.0.1", "http://127.0.0.1:8000", {"Origin": "null"}),
    ("127.0.0.1", "http://127.0.0.1:8000", {"Origin": "http://127.0.0.1:9000"}),
    ("127.0.0.1", "http://127.0.0.1:8000", {"X-Forwarded-For": "127.0.0.1"}),
    ("127.0.0.1", "http://127.0.0.1:8000", {"Forwarded": "for=127.0.0.1"}),
])
def test_real_bloqueia_acesso_nao_local_e_proxy_antes_de_abrir_cliente(monkeypatch, peer, base_url, headers):
    configurar_real(monkeypatch)
    abrir = MagicMock()
    monkeypatch.setattr(interface, "conectar_firestore", abrir)
    resposta = TestClient(app, base_url=base_url, client=(peer, 12345)).get('/api/avaliacoes', headers=headers)
    assert resposta.status_code == 403
    abrir.assert_not_called()


def test_real_continua_bloqueado_em_pytest_antes_de_adc(monkeypatch):
    configurar_real(monkeypatch)
    inicializar = MagicMock()
    monkeypatch.setattr(firebase_admin, "initialize_app", inicializar)
    assert usar_emulador_configurado() is False  # Seleção não implica conexão.
    with pytest.raises(ValueError, match="bloqueada em testes"):
        with conectar_firestore(emulador=False):
            pytest.fail("Não pode criar cliente real.")
    resposta = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345)).get('/api/avaliacoes')
    assert resposta.status_code == 503
    inicializar.assert_not_called()
