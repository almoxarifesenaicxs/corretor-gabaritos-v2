"""Barreira de segurança: clientes reais de testes somente no emulador."""

import pytest
from google.cloud.firestore_v1 import Client, AsyncClient

from app.database.firestore import validar_emulador


@pytest.fixture(autouse=True)
def administrador_nos_testes_de_negocio():
    # Somente a aplicação compartilhada pelos testes de negócio. Os testes de
    # autenticação criam aplicações novas, sem este override e sem bypass por env.
    from app.main import app
    from app.autenticacao import exigir_administrador
    app.dependency_overrides[exigir_administrador] = lambda: {"uid": "admin-teste"}
    yield
    app.dependency_overrides.pop(exigir_administrador, None)


@pytest.fixture(autouse=True)
def bloquear_firestore_producao(monkeypatch):
    def proteger(inicializar):
        def inicializar_seguro(self, *args, **kwargs):
            projeto = validar_emulador()
            informado = kwargs.get("project", args[0] if args else None)
            if informado != projeto:
                raise ValueError("Cliente de teste requer o projeto demo configurado.")
            return inicializar(self, *args, **kwargs)
        return inicializar_seguro

    for classe in (Client, AsyncClient):
        monkeypatch.setattr(classe, "__init__", proteger(classe.__init__))


@pytest.fixture(autouse=True)
def bloquear_auth_real(monkeypatch):
    from firebase_admin import auth
    import google.auth

    def bloqueado(*args, **kwargs):
        raise RuntimeError("Firebase real bloqueado nos testes; use mocks explícitos.")

    monkeypatch.setattr(auth, "verify_id_token", bloqueado)
    monkeypatch.setattr(google.auth, "default", bloqueado)
