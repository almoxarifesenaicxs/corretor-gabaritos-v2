"""Confirmação de operações perdidas, usando somente Firestore fictício."""
from fastapi.testclient import TestClient

from app.main import criar_app, app
from app.routes import interface
from suporte_estabilizacao import entrada_segura
from test_persistencia import banco
from test_local_operacional import configuracao


def test_resposta_perdida_consulta_e_reenvio_nao_duplicam(configuracao, banco):
    repo, dados = banco
    prova = repo.criar_avaliacao("Evento", {str(i): "A" for i in range(1, 51)})
    api = criar_app()
    body = entrada_segura(prova["id"])
    api.dependency_overrides[interface.obter_persistencia] = lambda: repo
    url = "/api/operacoes/correcao/" + body["operacao_id"]
    with TestClient(api, base_url="http://127.0.0.1:8000",
                    client=("127.0.0.1", 50000)) as http:
        assert http.get(url).json() == {"estado": "nao_encontrada"}
        # O banco confirma a transação; a resposta HTTP é simuladamente perdida.
        primeiro = repo.salvar_correcao(body["prova_id"], body["aluno"], body["resultado"],
            respostas=body["respostas"], comprovante=body["comprovante"],
            operacao_id=body["operacao_id"])
        confirmado = http.get(url).json()
        assert confirmado["estado"] == "confirmada"
        assert confirmado["registro"]["id"] == primeiro["id"]
        repetido = http.post("/api/correcoes/salvar", json=body)
        assert repetido.status_code == 201
        assert repetido.json()["id"] == primeiro["id"]
        assert len([key for key in dados if key[0] == "correcoes"]) == 1
        assert http.get(url, headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403


def test_consulta_indisponivel_fora_do_modo_operacional(configuracao):
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as http:
        assert http.get("/api/operacoes/correcao/00000000-0000-0000-0000-000000000000").status_code == 404
