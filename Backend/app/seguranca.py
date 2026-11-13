"""Barreiras locais e orçamento de recepção antes do parser de formulários."""

from ipaddress import ip_address
from threading import BoundedSemaphore, Lock
from collections import deque
from urllib.parse import urlsplit
import asyncio
import time

from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from app.autenticacao import autorizar_credencial
from app.ambiente import Ambiente
from app.sessoes_publicas import identificar_token

LIMITE_CORPO_UPLOAD = 11 * 1024 * 1024
LIMITE_CORPO_LOTE = 33 * 1024 * 1024
LIMITE_CORPO_JSON = 128 * 1024
PRAZO_CORPO = 30
_PROCESSAMENTOS = BoundedSemaphore(2)
_RECEPCOES = BoundedSemaphore(4)
_DEMO_PROCESSAMENTOS = BoundedSemaphore(1)
_DEMO_JANELA = deque()
_DEMO_LOCK = Lock()
_PUBLIC_LOCK = Lock()
_PUBLIC_JANELAS = {}
_DEMO_ROTAS = {
    ("GET", "/api/health"), ("GET", "/api/demo/info"),
    ("GET", "/api/avaliacoes"), ("GET", "/api/avaliacoes/demonstracao-50/gabarito"),
    ("GET", "/api/alunos"), ("GET", "/api/alunos/correspondencias"),
    ("POST", "/api/correcoes/processar"), ("POST", "/api/correcoes/recalcular"),
    ("POST", "/api/alunos/reconhecer-nome"),
}
_DEMO_CUSTOSAS = {"/api/correcoes/processar", "/api/alunos/reconhecer-nome"}
ROTAS_PROCESSAMENTO = {
    "/api/correcoes/processar", "/api/gabaritos/reconhecer",
    "/api/capturas/analisar", "/api/alunos/reconhecer-nome", "/api/correcoes/recalcular",
    "/api/lotes/zip",
}


class ProtecaoLocal:
    def __init__(self, app, ambiente=None):
        self.app = app
        self.ambiente = ambiente or Ambiente("local")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if (scope["path"].startswith("/api/lotes")
                and self.ambiente.modo not in {"local_operacional", "producao", "homologacao", "publico_sessoes", "publico_compartilhado"}):
            return await JSONResponse({"detail": "Lotes disponíveis somente no modo operacional local."}, 404)(scope, receive, send)
        headers = dict(scope["headers"])
        if self.ambiente.modo == "homologacao":
            return await self.homologacao(scope, receive, send, headers)
        if self.ambiente.modo == "publico_demo":
            return await self.publico_demo(scope, receive, send, headers)
        if self.ambiente.modo == "publico_sessoes":
            return await self.publico_sessoes(scope, receive, send, headers)
        if self.ambiente.modo == "publico_compartilhado":
            return await self.publico_sessoes(scope, receive, send, headers, compartilhado=True)
        if self.ambiente.modo == "local_operacional":
            return await self.local_operacional(scope, receive, send, headers)
        if self.ambiente.modo in {"producao", "publico"}:
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

    async def local_operacional(self, scope, receive, send, headers):
        for nome in (b"host", b"origin", b"content-length", b"authorization"):
            if sum(chave == nome for chave, _ in scope["headers"]) > 1:
                return await JSONResponse({"detail": "Cabeçalhos ambíguos."}, 400)(scope, receive, send)
        try:
            cliente = ip_address(scope["client"][0]).is_loopback
            servidor = scope.get("server")
            host_configurado = self.ambiente.hosts[0]
            servidor_local = (servidor is not None and servidor[0] == host_configurado
                              and isinstance(servidor[1], int) and 1 <= servidor[1] <= 65535)
            host_esperado = (f"[{host_configurado}]" if host_configurado == "::1"
                             else host_configurado) + f":{servidor[1]}"
            host = headers.get(b"host", b"").decode("ascii")
            origem = headers.get(b"origin")
            permitido = (cliente and servidor_local and scope["scheme"] == "http"
                         and host == host_esperado
                         and (origem is None or origem.decode("ascii") == f"http://{host}")
                         and not any(chave == b"forwarded" or chave.startswith(b"x-forwarded-")
                                     for chave, _ in scope["headers"]))
        except (ValueError, UnicodeError, TypeError, KeyError, IndexError):
            permitido = False
        if not permitido:
            return await JSONResponse({"detail": "Modo operacional disponível somente no loopback direto."}, 403)(scope, receive, send)
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

    async def publico_demo(self, scope, receive, send, headers):
        if sum(k == b"host" for k, _ in scope["headers"]) != 1 or sum(k == b"origin" for k, _ in scope["headers"]) > 1:
            return await JSONResponse({"detail": "Cabeçalhos ambíguos."}, 400)(scope, receive, send)
        try:
            host = headers.get(b"host", b"").decode("ascii").lower()
            origin = headers.get(b"origin")
            autorizado = host in self.ambiente.hosts and (
                origin is None or origin.decode("ascii") in self.ambiente.origens)
        except UnicodeError:
            autorizado = False
        if not autorizado:
            return await JSONResponse({"detail": "Host ou origem não autorizado."}, 403)(scope, receive, send)
        requested = headers.get(b"access-control-request-method", b"").decode("ascii", "ignore").upper()
        method = requested if scope["method"] == "OPTIONS" else scope["method"]
        if (method, scope["path"]) not in _DEMO_ROTAS:
            return await JSONResponse({"detail": "Rota indisponível na demonstração."}, 404)(scope, receive, send)
        enviar_original = send

        async def enviar(evento):
            if evento["type"] == "http.response.start":
                cabecalhos = list(evento.get("headers", []))
                cabecalhos.append((b"cache-control", b"no-store"))
                if origin is not None and not any(k == b"access-control-allow-origin" for k, _ in cabecalhos):
                    cabecalhos.extend([(b"access-control-allow-origin", origin), (b"vary", b"Origin")])
                evento = {**evento, "headers": cabecalhos}
            await enviar_original(evento)

        if scope["method"] == "OPTIONS" or scope["path"] not in _DEMO_CUSTOSAS:
            return await self.receber_corpo(scope, receive, enviar, headers)
        now = time.monotonic()
        with _DEMO_LOCK:
            while _DEMO_JANELA and now - _DEMO_JANELA[0] > 60:
                _DEMO_JANELA.popleft()
            excedido = len(_DEMO_JANELA) >= 12
            if not excedido:
                _DEMO_JANELA.append(now)
        if excedido:
            return await JSONResponse({"detail": "Limite temporário de processamento atingido."}, 429)(scope, receive, enviar)
        if not _DEMO_PROCESSAMENTOS.acquire(blocking=False):
            return await JSONResponse({"detail": "Processamento ocupado. Tente novamente."}, 503)(scope, receive, enviar)
        try:
            return await self.receber_corpo(scope, receive, enviar, headers)
        finally:
            _DEMO_PROCESSAMENTOS.release()

    async def publico_sessoes(self, scope, receive, send, headers, compartilhado=False):
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
        caminho = scope["path"]
        metodo = scope["method"]
        enviar_original = send

        async def enviar(evento):
            if evento["type"] == "http.response.start":
                cabecalhos = list(evento.get("headers", []))
                cabecalhos.append((b"cache-control", b"no-store"))
                if origem is not None and not any(k == b"access-control-allow-origin" for k, _ in cabecalhos):
                    cabecalhos.extend([(b"access-control-allow-origin", origem), (b"vary", b"Origin")])
                evento = {**evento, "headers": cabecalhos}
            await enviar_original(evento)

        if metodo == "OPTIONS":
            return await self.app(scope, receive, enviar)
        if caminho == "/api/health" and metodo == "GET":
            return await self.app(scope, receive, enviar)
        nova = not compartilhado and caminho == "/api/public/session" and metodo == "POST"
        sessao = None
        if not nova and not compartilhado:
            try:
                valor = headers.get(b"authorization", b"").decode("ascii")
                partes = valor.split()
                sessao = identificar_token(self.ambiente.chave_sessao, partes[1]) if (
                    len(partes) == 2 and partes[0].lower() == "bearer") else None
            except UnicodeError:
                sessao = None
            if not sessao:
                return await JSONResponse({"detail": "Sessão anônima ausente ou expirada."}, 401)(scope, receive, enviar)
            scope = {**scope, "state": {**scope.get("state", {}), "public_session": sessao}}
        agora = time.monotonic()
        chave = "novas" if nova else "publico_compartilhado" if compartilhado else f"sessao:{sessao}"
        limite = 8 if nova else 120
        custosa = caminho in ROTAS_PROCESSAMENTO or caminho.startswith("/api/lotes/")
        escrita = metodo == "POST" and caminho in {"/api/avaliacoes", "/api/correcoes/salvar"}
        exportacao = metodo == "GET" and caminho == "/api/correcoes/exportar"
        with _PUBLIC_LOCK:
            for identificador, janela in list(_PUBLIC_JANELAS.items()):
                while janela and agora - janela[0] > 60:
                    janela.popleft()
                if not janela:
                    del _PUBLIC_JANELAS[identificador]
            janela = _PUBLIC_JANELAS.setdefault(chave, deque())
            excedido = len(janela) >= limite
            if not excedido:
                janela.append(agora)
            if custosa and not excedido:
                global_janela = _PUBLIC_JANELAS.setdefault("processamentos", deque())
                excedido = len(global_janela) >= 18
                if not excedido:
                    global_janela.append(agora)
            if escrita and not excedido:
                global_janela = _PUBLIC_JANELAS.setdefault("escritas", deque())
                excedido = len(global_janela) >= 6
                if not excedido:
                    global_janela.append(agora)
            if exportacao and not excedido:
                global_janela = _PUBLIC_JANELAS.setdefault("exportacoes", deque())
                excedido = len(global_janela) >= 2
                if not excedido:
                    global_janela.append(agora)
        if excedido:
            return await JSONResponse({"detail": "Limite temporário de requisições atingido."}, 429)(scope, receive, enviar)
        if custosa and not _DEMO_PROCESSAMENTOS.acquire(blocking=False):
            return await JSONResponse({"detail": "Processamento ocupado. Tente novamente."}, 503)(scope, receive, enviar)
        try:
            return await self.receber_corpo(scope, receive, enviar, headers)
        finally:
            if custosa:
                _DEMO_PROCESSAMENTOS.release()

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
        if not publico and not preflight and self.ambiente.modo == "producao":
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
        limite = (9 * 1024 * 1024 if scope["path"] == "/api/lotes/zip" and self.ambiente.modo in {"publico_sessoes", "publico_compartilhado"}
                  else LIMITE_CORPO_LOTE if scope["path"] == "/api/lotes/zip" and self.ambiente.modo in {"local_operacional", "producao"}
                  else LIMITE_CORPO_UPLOAD if multipart else LIMITE_CORPO_JSON)
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
