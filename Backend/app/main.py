
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import os
from urllib.parse import urlsplit

from app.routes.correcoes import router as correcoes_router
from app.routes.interface import router as interface_router
from app.seguranca import ProtecaoLocal
from app.autenticacao import exigir_administrador
from app.ambiente import carregar_ambiente


class ArquivosPublicos(StaticFiles):
    permitidos = {"", ".", "index.html", "css/style.css", "components/captura.html",
                  "pages/avaliacoes.html", "pages/correcao.html", "pages/alunos.html",
                  "assets/fonts/Manrope-Variable.ttf", "assets/fonts/OFL.txt"} | {
        "js/" + nome for nome in ("app.mjs", "api.mjs", "camera.mjs", "alunos.mjs",
        "nome-aluno.mjs", "layout.mjs", "fluxo-captura.mjs", "paginas.mjs",
        "revisao.mjs", "correcao-visual.mjs", "config.mjs", "auth.mjs", "login.mjs")}

    async def get_response(self, path, scope):
        if path.replace("\\", "/") not in self.permitidos:
            from starlette.exceptions import HTTPException
            raise HTTPException(404)
        return await super().get_response(path, scope)

def origens_cors():
    origens = []
    for item in os.environ.get("CORS_ORIGINS", "").split(","):
        origem = item.strip()
        if not origem:
            continue
        destino = urlsplit(origem)
        if (destino.scheme not in {"http", "https"} or not destino.hostname
                or destino.username is not None or destino.password is not None
                or destino.path or destino.query or destino.fragment
                or "*" in origem or any(c.isspace() for c in origem)):
            raise ValueError("CORS_ORIGINS exige origens HTTP(S) explícitas, sem caminhos ou curingas.")
        destino.port  # Rejeita portas inválidas antes da inicialização.
        origens.append(origem)
    return origens


def inicio():
    return {
        "mensagem": "API do Corretor de Gabaritos funcionando!"
    }


def verificar_status():
    return {
        "status": "ok"
    }


def criar_app(*, pasta_frontend=None):
    origens = origens_cors()
    ambiente = carregar_ambiente(origens)
    producao = ambiente.modo == "producao"
    if producao:
        from app.services import integridade
        integridade._CHAVE = ambiente.chave_integridade
    api = FastAPI(title="Corretor Automático de Gabaritos",
                  description="API REST para correção automática de provas.", version="1.0.0",
                  docs_url=None if producao else "/docs",
                  redoc_url=None if producao else "/redoc",
                  openapi_url=None if producao else "/openapi.json")
    api.state.ambiente = ambiente.modo
    protegidas = [Depends(exigir_administrador)]
    api.include_router(correcoes_router, dependencies=protegidas)
    api.include_router(interface_router, dependencies=protegidas)
    api.add_api_route("/api/auth/me", exigir_administrador, methods=["GET"])
    api.add_api_route("/", inicio, methods=["GET"])
    api.add_api_route("/api/health", verificar_status, methods=["GET"])
    api.add_middleware(CORSMiddleware, allow_origins=origens,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"],
                       allow_credentials=False)
    # Último middleware adicionado executa primeiro: CORS nunca contorna a proteção.
    api.add_middleware(ProtecaoLocal, ambiente=ambiente)
    modo = os.environ.get("SERVIR_FRONTEND", "false" if producao else "auto").strip().lower()
    if modo not in {"auto", "true", "false"}:
        raise ValueError("SERVIR_FRONTEND deve ser auto, true ou false.")
    pasta = Path(pasta_frontend) if pasta_frontend is not None else Path(__file__).resolve().parents[2] / "Frontend"
    if modo == "true" or (modo == "auto" and pasta.is_dir()):
        api.mount("/interface", ArquivosPublicos(directory=pasta, html=True), name="interface")
    return api


app = criar_app()
