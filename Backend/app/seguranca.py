"""Barreiras locais e orçamento de recepção antes do parser de formulários."""

from ipaddress import ip_address
from threading import BoundedSemaphore
from urllib.parse import urlsplit
import asyncio
import time

from starlette.responses import JSONResponse

LIMITE_CORPO_UPLOAD = 11 * 1024 * 1024
LIMITE_CORPO_JSON = 128 * 1024
PRAZO_CORPO = 30
_PROCESSAMENTOS = BoundedSemaphore(2)
_RECEPCOES = BoundedSemaphore(4)
ROTAS_PROCESSAMENTO = {
    "/api/correcoes/processar", "/api/gabaritos/reconhecer",
    "/api/capturas/analisar", "/api/alunos/reconhecer-nome", "/api/correcoes/recalcular",
}


class ProtecaoLocal:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            host = headers.get(b"host", b"").decode("ascii")
            destino = urlsplit("//" + host)
            local = ip_address(scope["client"][0]).is_loopback
            origem = headers.get(b"origin")
            origem_valida = not origem or origem.decode("ascii") == scope["scheme"] + "://" + host
            permitido = (local and destino.hostname in {"localhost", "127.0.0.1", "::1"}
                         and origem_valida and not any(k.startswith(b"x-forwarded-") or k == b"forwarded"
                                                      for k in headers))
        except (ValueError, UnicodeError, TypeError):
            permitido = False
        if not permitido:
            return await JSONResponse({"detail": "Aplicação disponível somente por acesso local direto."}, 403)(scope, receive, send)
        if scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        if not _RECEPCOES.acquire(blocking=False):
            return await JSONResponse({"detail": "Recepção ocupada. Tente novamente."}, 503)(scope, receive, send)
        try:
            await self.com_corpo(scope, receive, send, headers)
        finally:
            _RECEPCOES.release()

    async def com_corpo(self, scope, receive, send, headers):
        multipart = headers.get(b"content-type", b"").lower().startswith(b"multipart/form-data")
        limite = LIMITE_CORPO_UPLOAD if multipart else LIMITE_CORPO_JSON
        try:
            declarado = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Tamanho HTTP inválido."}, 400)(scope, receive, send)
        if declarado < 0 or declarado > limite:
            return await JSONResponse({"detail": "Corpo da requisição excede o limite permitido."}, 413)(scope, receive, send)
        # Recebe no máximo o orçamento antes de permitir spool/decodificação no framework.
        partes, total = [], 0
        prazo = time.monotonic() + PRAZO_CORPO
        while True:
            try:
                evento = await asyncio.wait_for(receive(), timeout=max(0, min(10, prazo - time.monotonic())))
            except TimeoutError:
                return await JSONResponse({"detail": "Tempo de recepção excedido."}, 408)(scope, receive, send)
            if evento["type"] == "http.disconnect":
                return
            bloco = evento.get("body", b"")
            total += len(bloco)
            if total > limite:
                return await JSONResponse({"detail": "Corpo da requisição excede o limite permitido."}, 413)(scope, receive, send)
            partes.append(bloco)
            if not evento.get("more_body", False):
                break
        corpo = b"".join(partes)
        partes.clear()
        entregue = False

        async def receber_limitado():
            nonlocal entregue
            if entregue:
                return await receive()
            entregue = True
            return {"type": "http.request", "body": corpo, "more_body": False}

        processar = scope["path"] in ROTAS_PROCESSAMENTO
        if processar and not _PROCESSAMENTOS.acquire(blocking=False):
            return await JSONResponse({"detail": "Processamento ocupado. Tente novamente."}, 503)(scope, receive, send)
        try:
            await self.app(scope, receber_limitado, send)
        finally:
            if processar:
                _PROCESSAMENTOS.release()
