
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.routes.correcoes import router as correcoes_router
from app.routes.interface import router as interface_router
from app.seguranca import ProtecaoLocal


class ArquivosPublicos(StaticFiles):
    permitidos = {"", ".", "index.html", "css/style.css", "components/captura.html",
                  "pages/avaliacoes.html", "pages/correcao.html", "pages/alunos.html",
                  "assets/fonts/Manrope-Variable.ttf", "assets/fonts/OFL.txt"} | {
        "js/" + nome for nome in ("app.mjs", "api.mjs", "camera.mjs", "alunos.mjs",
        "nome-aluno.mjs", "layout.mjs", "fluxo-captura.mjs", "paginas.mjs",
        "revisao.mjs", "correcao-visual.mjs")}

    async def get_response(self, path, scope):
        if path.replace("\\", "/") not in self.permitidos:
            from starlette.exceptions import HTTPException
            raise HTTPException(404)
        return await super().get_response(path, scope)

app = FastAPI(
    title="Corretor Automático de Gabaritos",
    description="API REST para correção automática de provas.",
    version="1.0.0"
)

app.include_router(correcoes_router)
app.include_router(interface_router)
app.add_middleware(ProtecaoLocal)
app.mount("/interface", ArquivosPublicos(directory=Path(__file__).resolve().parents[2] / "Frontend", html=True), name="interface")


@app.get("/")
def inicio():
    return {
        "mensagem": "API do Corretor de Gabaritos funcionando!"
    }


@app.get("/api/health")
def verificar_status():
    return {
        "status": "ok"
    }
