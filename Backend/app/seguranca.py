"""Barreiras locais e orçamento de recepção antes do parser de formulários."""

from ipaddress import ip_address
from threading import BoundedSemaphore
from urllib.parse import urlsplit
import asyncio
import time

from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from app.autenticacao import autorizar_credencial
from app.ambiente import Ambiente

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
    def __init__(self, app, ambiente=None):
        self.app = app
        self.ambiente = ambiente or Ambiente("local")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        if self.ambiente.modo == "homologacao":
            return await self.homologacao(scope, receive, send, headers)
        if self.ambiente.modo == "producao":
            return await self.producao(scope, receive, send, headers)
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
        return await self.receber_corpo(scope, receive, send, headers)

    async def homologacao(self, scope, receive, send, headers):
        if sum(k == b"host" for k, _ in scope["headers"]) != 1:
            return await JSONResponse({"detail": "Host inválido."}, 400)(scope, receive, send)
        try:
            host = headers.get(b"host", b"").decode("ascii").lower()
            permitido = host in self.ambiente.hosts
        except UnicodeError:
            permitido = False
        if not permitido:
            return await JSONResponse({"detail": "Host não autorizado."}, 403)(scope, receive, send)
        if scope["method"] != "GET" or scope["path"] != "/api/health":
            return await JSONResponse({"detail": "Operação indisponível em homologação."}, 403)(scope, receive, send)
        # Nenhum cabeçalho encaminhado participa da decisão ou chega à rota.
        scope = dict(scope)
        scope["headers"] = [(k, v) for k, v in scope["headers"]
                            if k != b"forwarded" and not k.startswith(b"x-forwarded-")]
        return await self.app(scope, receive, send)

    async def producao(self, scope, receive, send, headers):
        # Host/Origin/Authorization ambíguos são rejeitados, nunca escolher um dos valores.
        for nome in (b"host", b"origin", b"authorization", b"content-length"):
            if sum(chave == nome for chave, _ in scope["headers"]) > 1:
                return await JSONResponse({"detail": "Cabeçalhos ambíguos."}, 400)(scope, receive, send)
        try:
            host = headers.get(b"host", b"").decode("ascii").lower()
            origem = headers.get(b"origin")
            permitido = host in self.ambiente.hosts and (
                origem is None or origem.decode("ascii") in self.ambiente.origens)
        except UnicodeError:
            permitido = False
        if not permitido:
            return await JSONResponse({"detail": "Host ou origem não autorizado."}, 403)(scope, receive, send)

        # Erros de autenticação/limites também precisam ser legíveis pela origem
        # autorizada. Não acrescentar CORS a origens ou hosts rejeitados acima.
        enviar_original = send

        async def enviar(evento):
            if evento["type"] == "http.response.start" and origem is not None:
                cabecalhos = list(evento.get("headers", []))
                if not any(k == b"access-control-allow-origin" for k, _ in cabecalhos):
                    cabecalhos.extend([(b"access-control-allow-origin", origem), (b"vary", b"Origin")])
                    evento = {**evento, "headers": cabecalhos}
            await enviar_original(evento)

        send = enviar

        # Render termina TLS antes do serviço. Não interpretar IP, esquema ou Host
        # encaminhados; autenticação e autorização nunca dependem desses valores.
        scope = dict(scope)
        scope["headers"] = [(k, v) for k, v in scope["headers"]
                            if k != b"forwarded" and not k.startswith(b"x-forwarded-")]
        headers = dict(scope["headers"])
        preflight = (scope["method"] == "OPTIONS" and origem is not None
                     and b"access-control-request-method" in headers)
        publico = scope["method"] in {"GET", "HEAD"} and scope["path"] in {"/", "/api/health"}
        if not publico and not preflight:
            try:
                valor = headers.get(b"authorization", b"").decode("ascii")
                partes = valor.split()
                credencial = (HTTPAuthorizationCredentials(scheme="Bearer", credentials=partes[1])
                              if len(partes) == 2 and partes[0].lower() == "bearer" else None)
                usuario = await run_in_threadpool(autorizar_credencial, credencial)
            except UnicodeError:
                return await JSONResponse({"detail": "Autenticação inválida."}, 401,
                    headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
            except HTTPException as erro:
                return await JSONResponse({"detail": erro.detail}, erro.status_code,
                    headers=erro.headers)(scope, receive, send)
            scope["state"] = {**scope.get("state", {}), "administrador_verificado": usuario}
        return await self.receber_corpo(scope, receive, send, headers)

    async def receber_corpo(self, scope, receive, send, headers):
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
