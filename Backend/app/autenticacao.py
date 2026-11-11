"""Autenticação obrigatória e autorização por UID, independente do Firestore."""
import os
from functools import lru_cache
from threading import Lock

import firebase_admin
from firebase_admin import auth, credentials
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)
_lock = Lock()


@lru_cache(maxsize=1)
def _app_auth(projeto):
    with _lock:
        try:
            app = firebase_admin.get_app("corretor-auth")
        except ValueError:
            return firebase_admin.initialize_app(credentials.ApplicationDefault(),
                {"projectId": projeto}, name="corretor-auth")
        if app.project_id != projeto:
            raise ValueError("Instância de autenticação pertence a outro projeto.")
        return app


def verificar_token(token):
    projeto = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
    # Não aceitar tokens sem assinatura via configuração acidental de emulador.
    if not projeto or projeto.startswith("demo-") or os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"):
        raise HTTPException(503, "Autenticação não configurada.")
    try:
        app = _app_auth(projeto)
    except Exception:
        raise HTTPException(503, "Autenticação não configurada.") from None
    try:
        return auth.verify_id_token(token, app=app, check_revoked=True)
    except (auth.InvalidIdTokenError, auth.ExpiredIdTokenError,
            auth.RevokedIdTokenError, auth.UserDisabledError, auth.UserNotFoundError, ValueError):
        raise HTTPException(401, "Sessão inválida ou expirada.",
                            headers={"WWW-Authenticate": "Bearer"}) from None
    except Exception:
        raise HTTPException(503, "Serviço de autenticação indisponível.") from None


def autorizar_credencial(credencial):
    if credencial is None:
        raise HTTPException(401, "Autenticação necessária.", headers={"WWW-Authenticate": "Bearer"})
    usuario = verificar_token(credencial.credentials)
    permitidos = {uid.strip() for uid in os.environ.get("ADMIN_UIDS", "").split(",") if uid.strip()}
    uid = usuario.get("uid")
    if not uid or uid not in permitidos:
        raise HTTPException(403, "Usuário sem autorização administrativa.")
    return {"uid": uid}


def exigir_administrador(request: Request,
                        credencial: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    # Marca interna preenchida somente pelo middleware de produção, nunca por headers.
    verificado = getattr(request.state, "administrador_verificado", None)
    if verificado is not None:
        return verificado
    return autorizar_credencial(credencial)
