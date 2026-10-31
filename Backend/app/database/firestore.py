"""Configuração explícita do Firebase Admin; emulador é o padrão seguro."""

from contextlib import contextmanager
import os
import sys
from urllib.parse import urlsplit
from uuid import uuid4


def validar_emulador() -> str:
    """Exige destino local e projeto demo, sem carregar credenciais reais."""
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
    projeto = os.environ.get("FIREBASE_PROJECT_ID", "")
    try:
        destino = urlsplit("//" + host)
        valido = (destino.hostname in {"localhost", "127.0.0.1", "::1"}
                  and destino.port is not None and 1 <= destino.port <= 65535
                  and not destino.path and not destino.query and not destino.fragment
                  and destino.username is None and destino.password is None
                  and "://" not in host)
    except ValueError:
        valido = False
    if not valido or not projeto.startswith("demo-"):
        raise ValueError("Configure FIRESTORE_EMULATOR_HOST local (host:porta) e FIREBASE_PROJECT_ID demo-*.")
    return projeto


@contextmanager
def conectar_firestore(*, emulador: bool = True):
    """Abre cliente somente dentro de `with`; fecha cliente e app ao sair.

    Em nuvem requer emulador=False explícito, projeto e ADC no ambiente.
    Essa opção é bloqueada em processos de testes Pytest.
    """
    if emulador:
        projeto = validar_emulador()
    else:
        if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
            raise ValueError("Conexão real bloqueada em testes. Use o Firestore Emulator.")
        projeto = os.environ.get("FIREBASE_PROJECT_ID", "")
        if not projeto or projeto.startswith("demo-") or os.environ.get("FIRESTORE_EMULATOR_HOST"):
            raise ValueError("Conexão real requer projeto explícito e ausência de FIRESTORE_EMULATOR_HOST.")

    # Imports tardios: importar a aplicação não inicializa Firebase ou ADC.
    import firebase_admin
    from firebase_admin import credentials, firestore
    from google.auth.credentials import AnonymousCredentials

    class CredencialEmulador(credentials.Base):
        def get_credential(self):
            return AnonymousCredentials()

    credencial = CredencialEmulador() if emulador else credentials.ApplicationDefault()
    app = firebase_admin.initialize_app(credencial, {"projectId": projeto}, name=f"corretor-{uuid4().hex}")
    cliente = None
    try:
        cliente = firestore.client(app=app)
        yield cliente
    finally:
        try:
            if cliente is not None:
                cliente.close()
        finally:
            firebase_admin.delete_app(app)
