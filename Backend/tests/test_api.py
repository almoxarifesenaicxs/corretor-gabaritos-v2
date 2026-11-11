
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def test_pagina_inicial():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "mensagem": "API do Corretor de Gabaritos funcionando!"
    }


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

