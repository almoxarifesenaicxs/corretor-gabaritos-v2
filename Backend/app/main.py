
from fastapi import FastAPI

from app.routes.correcoes import router as correcoes_router

app = FastAPI(
    title="Corretor Automático de Gabaritos",
    description="API REST para correção automática de provas.",
    version="1.0.0"
)

app.include_router(correcoes_router)


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
