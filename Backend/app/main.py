
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.routes.correcoes import router as correcoes_router
from app.routes.interface import router as interface_router

app = FastAPI(
    title="Corretor Automático de Gabaritos",
    description="API REST para correção automática de provas.",
    version="1.0.0"
)

app.include_router(correcoes_router)
app.include_router(interface_router)
app.mount("/interface", StaticFiles(directory=Path(__file__).resolve().parents[2] / "Frontend", html=True), name="interface")


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
