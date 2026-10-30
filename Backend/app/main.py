
from fastapi import FastAPI

app = FastAPI(
    title="Corretor Automático de Gabaritos",
    description="API REST para correção automática de provas.",
    version="1.0.0"
)


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
