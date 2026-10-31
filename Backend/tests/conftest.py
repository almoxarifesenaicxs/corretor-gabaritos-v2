"""Barreira de segurança: clientes reais de testes somente no emulador."""

import pytest
from google.cloud.firestore_v1 import Client

from app.database.firestore import validar_emulador


@pytest.fixture(autouse=True)
def bloquear_firestore_producao(monkeypatch):
    inicializar = Client.__init__

    def inicializar_seguro(self, *args, **kwargs):
        projeto = validar_emulador()
        informado = kwargs.get("project", args[0] if args else None)
        if informado != projeto:
            raise ValueError("Cliente de teste requer o projeto demo configurado.")
        return inicializar(self, *args, **kwargs)

    monkeypatch.setattr(Client, "__init__", inicializar_seguro)
