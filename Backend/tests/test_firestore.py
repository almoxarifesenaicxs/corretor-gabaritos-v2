import importlib
from unittest.mock import MagicMock

import firebase_admin
from firebase_admin import firestore
from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore_v1 import Client
import pytest

from app.database.firestore import conectar_firestore, validar_emulador


@pytest.mark.parametrize("host,projeto", [
    (None, "demo-testes"), ("localhost:8080", "producao"),
    ("firestore.googleapis.com:443", "demo-testes"),
    ("http://localhost:8080", "demo-testes"), ("localhost", "demo-testes"),
    ("localhost:8080/caminho", "demo-testes"), ("localhost:99999", "demo-testes"),
    ("usuario@localhost:8080", "demo-testes"),
])
def test_configuracao_insegura_bloqueada(monkeypatch, host, projeto):
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    if host is not None:
        monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", host)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", projeto)
    inicializar = MagicMock()
    monkeypatch.setattr(firebase_admin, "initialize_app", inicializar)
    with pytest.raises(ValueError):
        with conectar_firestore():
            pytest.fail("Conexão não deveria ser aberta.")
    inicializar.assert_not_called()


def test_nuvem_bloqueada_em_testes(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "producao")
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    with pytest.raises(ValueError, match="bloqueada em testes"):
        with conectar_firestore(emulador=False):
            pytest.fail("Não deve acessar produção.")
    # Também impede contornar o factory e criar um cliente diretamente.
    with pytest.raises(ValueError):
        Client(project="producao", credentials=AnonymousCredentials())


def test_importacao_nao_inicializa_cliente(monkeypatch):
    inicializar, criar_cliente = MagicMock(), MagicMock()
    monkeypatch.setattr(firebase_admin, "initialize_app", inicializar)
    monkeypatch.setattr(firestore, "client", criar_cliente)
    import app.database.firestore as modulo
    importlib.reload(modulo)
    inicializar.assert_not_called()
    criar_cliente.assert_not_called()


@pytest.mark.parametrize("falhar", [False, True])
def test_sdk_emulador_anonimo_e_limpeza(monkeypatch, falhar):
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo-corretor-testes")
    app, cliente = MagicMock(), MagicMock()
    criar_app, remover = MagicMock(return_value=app), MagicMock()
    monkeypatch.setattr(firebase_admin, "initialize_app", criar_app)
    monkeypatch.setattr(firebase_admin, "delete_app", remover)
    monkeypatch.setattr(firestore, "client", MagicMock(return_value=cliente))
    try:
        with conectar_firestore() as obtido:
            assert obtido is cliente
            credencial, opcoes = criar_app.call_args.args
            assert isinstance(credencial.get_credential(), AnonymousCredentials)
            assert opcoes == {"projectId": "demo-corretor-testes"}
            if falhar:
                raise RuntimeError("Falha controlada")
    except RuntimeError:
        assert falhar
    cliente.close.assert_called_once()
    remover.assert_called_once_with(app)


def test_cliente_direto_com_outro_projeto_bloqueado(monkeypatch):
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo-corretor-testes")
    assert validar_emulador() == "demo-corretor-testes"
    with pytest.raises(ValueError, match="projeto demo"):
        Client(project="outro-projeto", credentials=AnonymousCredentials())
