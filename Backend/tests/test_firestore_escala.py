"""Consultas de escala com banco fictício; nenhuma conexão real é criada."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import FailedPrecondition, ServiceUnavailable

from app.main import app
from app.routes.interface import obter_persistencia
from app.services.persistencia import _LEGADOS
from test_persistencia import banco


def test_mais_de_mil_alunos_paginados_e_consulta_exata(banco):
    repo, dados = banco
    criar_colecao = repo.cliente.collection.side_effect
    varreduras = []

    def rastrear(nome):
        colecao = criar_colecao(nome)
        if nome == "alunos":
            stream = colecao.stream.side_effect
            def contar(**kwargs):
                varreduras.append(nome)
                return stream(**kwargs)
            colecao.stream.side_effect = contar
        return colecao

    repo.cliente.collection.side_effect = rastrear
    for i in range(1005):
        identificador = f"aluno-{i:04d}"
        nome = f"Aluno {i:04d}"
        dados["alunos", identificador] = {
            "id": identificador, "nome": nome,
            "nome_normalizado": nome.casefold(), "criado_em": datetime.now(timezone.utc),
        }
    dados["alunos", "antigo"] = {"id": "antigo", "nome": "Aluno antigo"}
    paginas, cursor = [], None
    while True:
        pagina = repo.listar_alunos_pagina(limite=30, cursor=cursor)
        paginas.extend(pagina["alunos"])
        cursor = pagina["proximo_cursor"]
        if cursor is None:
            break
    assert len(paginas) == 1006
    assert len({aluno["id"] for aluno in paginas}) == 1006
    assert paginas[-1]["id"] == "antigo"
    assert [a["nome"] for a in repo.listar_alunos_pagina("Aluno 007", limite=30)["alunos"]] == [
        f"Aluno {i:04d}" for i in range(70, 80)]
    assert [a["id"] for a in repo._alunos_exatos("aluno antigo")] == ["antigo"]
    assert [a["id"] for a in repo._alunos_exatos("aluno 1004")] == ["aluno-1004"]
    assert len(_LEGADOS) == 1
    assert varreduras == ["alunos"]


def test_historico_paginado_e_legado_sem_varrer_correcoes(banco):
    repo, dados = banco
    aluno = repo.cadastrar_aluno("Ana Silva")
    prova = repo.criar_prova("Evento")
    inicio = datetime(2026, 11, 14, tzinfo=timezone.utc)
    for i in range(65):
        identificador = f"correcao-{i:03d}"
        dados["correcoes", identificador] = {
            "id": identificador, "aluno_id": aluno["id"], "aluno": aluno["nome"],
            "prova_id": prova["id"], "processada_em": inicio + timedelta(minutes=i),
        }
    dados["correcoes", "legada"] = {
        "id": "legada", "aluno": "Ana Silva", "prova_id": prova["id"],
        "processada_em": inicio - timedelta(days=1),
    }
    cursor, recebidas = None, []
    for quantidade in (30, 30, 5):
        pagina = repo.historico_aluno_pagina(aluno["id"], limite=30, cursor=cursor)
        assert len(pagina["correcoes"]) == quantidade
        recebidas.extend(pagina["correcoes"])
        assert pagina["legadas_por_nome"] == []
        cursor = pagina["proximo_cursor"]
    assert cursor is None
    assert len({c["id"] for c in recebidas}) == 65
    assert recebidas[0]["id"] == "correcao-064"
    assert all(c["avaliacao"] == "Evento" for c in recebidas)
    antigas = repo.historico_aluno_pagina(aluno["id"], somente_legadas=True)
    assert [c["id"] for c in antigas["legadas_por_nome"]] == ["legada"]


def test_cursor_invalido_e_contrato_http_preservado(banco):
    repo, _ = banco
    aluno = repo.cadastrar_aluno("Ana Silva")
    with pytest.raises(ValueError, match="Cursor"):
        repo.listar_alunos_pagina(cursor="inexistente")
    with pytest.raises(ValueError, match="Cursor"):
        repo.historico_aluno_pagina(aluno["id"], cursor="inexistente")
    app.dependency_overrides[obter_persistencia] = lambda: repo
    try:
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as http:
            assert isinstance(http.get("/api/alunos").json(), list)
            pagina = http.get("/api/alunos?pagina=true&limite=30").json()
            assert pagina["alunos"][0]["id"] == aluno["id"]
            assert http.get("/api/alunos?pagina=true&cursor=inexistente").status_code == 422
            assert http.get(f"/api/alunos/{aluno['id']}/correcoes?pagina=true").json()["correcoes"] == []
    finally:
        app.dependency_overrides.pop(obter_persistencia, None)


def test_historico_sem_indice_composto_preserva_ordenacao_e_paginas(banco, caplog):
    repo, dados = banco
    aluno = repo.cadastrar_aluno("TESTE FICTÍCIO")
    prova = repo.criar_prova("Avaliação fictícia")
    inicio = datetime(2026, 11, 14, tzinfo=timezone.utc)
    for i in range(65):
        dados["correcoes", f"correcao-{i:03d}"] = {
            "id": f"correcao-{i:03d}", "aluno_id": aluno["id"], "aluno": aluno["nome"],
            "prova_id": prova["id"], "processada_em": inicio + timedelta(minutes=35 if i == 34 else i),
        }
    original = repo.cliente.collection.side_effect
    consultas_sem_ordem = []

    def colecao(nome):
        referencia = original(nome)
        if nome != "correcoes":
            return referencia
        filtrar = referencia.where.side_effect
        def where(*, filter):
            consulta = filtrar(filter=filter)
            ordenar = consulta.order_by.side_effect
            def order_by(campo, direction="ASCENDING"):
                if campo == "processada_em":
                    consulta.stream.side_effect = FailedPrecondition("The query requires an index")
                return ordenar(campo, direction)
            consulta.order_by.side_effect = order_by
            consultas_sem_ordem.append(consulta)
            return consulta
        referencia.where.side_effect = where
        return referencia

    repo.cliente.collection.side_effect = colecao
    recebidas, cursor = [], None
    with caplog.at_level("WARNING", logger="app.services.persistencia"):
        for tamanho in (30, 30, 5):
            pagina = repo.historico_aluno_pagina(aluno["id"], limite=30, cursor=cursor)
            assert len(pagina["correcoes"]) == tamanho
            recebidas.extend(c["id"] for c in pagina["correcoes"])
            cursor = pagina["proximo_cursor"]
    assert cursor is None
    esperado = [*range(64, 35, -1), 34, 35, *range(33, -1, -1)]
    assert recebidas == [f"correcao-{i:03d}" for i in esperado]
    assert any(not q.order_by.called for q in consultas_sem_ordem)
    assert "indice_composto_indisponivel" in caplog.text
    assert aluno["nome"] not in caplog.text


@pytest.mark.parametrize("falha", [
    ServiceUnavailable("offline"),
    FailedPrecondition("Index configuration invalid; query cannot run"),
])
def test_historico_sem_indice_nao_disfarca_outras_falhas(banco, falha):
    repo, _ = banco
    aluno = repo.cadastrar_aluno("TESTE FICTÍCIO")
    original = repo.cliente.collection.side_effect
    consultas = []
    def colecao(nome):
        referencia = original(nome)
        if nome == "correcoes":
            filtrar = referencia.where.side_effect
            def where(*, filter):
                consultas.append(filter)
                consulta = filtrar(filter=filter)
                consulta.stream.side_effect = falha
                return consulta
            referencia.where.side_effect = where
        return referencia
    repo.cliente.collection.side_effect = colecao
    from app.services.persistencia import ErroPersistencia
    with pytest.raises(ErroPersistencia):
        repo.historico_aluno_pagina(aluno["id"])
    assert len(consultas) == 1
