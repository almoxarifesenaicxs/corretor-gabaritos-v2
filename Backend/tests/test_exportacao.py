"""Exportação usa somente Firestore simulado e dados fictícios."""

import csv
from datetime import datetime, timezone
from io import StringIO
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import PermissionDenied

from app.main import criar_app
from app.routes import interface
from app.services.exportacao import (CAMPOS, ErroPersistencia, LimiteExportacao,
                                      AvaliacaoInexistente, exportar_correcoes)
from test_local_operacional import configuracao
from test_persistencia import banco, resultado


def preencher(dados, quantidade, *, primeiro_legado=False):
    base = resultado()
    dados["provas", "avaliacao-a"] = {"id": "avaliacao-a", "titulo": "=HYPERLINK(\"site\")"}
    dados["provas", "avaliacao-b"] = {"id": "avaliacao-b", "titulo": "Outra"}
    for numero in range(quantidade):
        identificador = f"{numero + 1:032x}"
        operacao = str(UUID(int=numero + 1))
        registro = {
            "id": identificador, "prova_id": "avaliacao-a" if numero % 2 == 0 else "avaliacao-b",
            "aluno_id": f"aluno-{numero % 701}",
            "aluno": "=1+1" if numero == 0 else f"Aluno fictício {numero % 701}",
            "resultado": base, "situacao": "sem_pendencias",
            "processada_em": datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc),
        }
        if numero or not primeiro_legado:
            registro["operacao_id"] = operacao
        else:
            dados["operacoes", "correcao-" + UUID(operacao).hex] = {"registro": {"id": identificador}}
        dados["correcoes", identificador] = registro


def linhas(csv_texto):
    return list(csv.DictReader(StringIO(csv_texto.lstrip("\ufeff")), delimiter=";"))


def test_exporta_mais_de_mil_com_paginacao_contagem_ids_e_notas(banco):
    repo, dados = banco
    preencher(dados, 1005, primeiro_legado=True)
    exportado = exportar_correcoes(repo)
    registros = linhas(exportado["csv"])
    assert len(registros) == 1005
    assert tuple(registros[0]) == CAMPOS
    assert exportado["resumo"]["total_correcoes"] == 1005
    assert exportado["resumo"]["alunos_distintos"] == 701
    assert exportado["resumo"]["operacoes_sem_id"] == 0
    assert {r["correcao_id"] for r in registros} == {f"{i + 1:032x}" for i in range(1005)}
    assert registros[0]["operacao_id"] == str(UUID(int=1))
    assert registros[0]["lote_id"] == ""
    assert registros[0]["aluno_nome"].startswith("'=1+1")
    assert registros[0]["avaliacao"].startswith("'=HYPERLINK")
    assert registros[0]["acertos"] == "50"
    assert registros[0]["pontuacao_total"] == "50"
    assert registros[0]["portugues_pontuacao"] == "25"
    assert registros[0]["matematica_pontuacao"] == "25"
    assert registros[0]["processada_em_utc"].endswith("+00:00")
    assert exportado["resumo"]["identificadores"][0] == {
        "correcao_id": registros[0]["correcao_id"], "operacao_id": registros[0]["operacao_id"]}
    filtrado = exportar_correcoes(repo, "avaliacao-a")
    assert filtrado["resumo"]["total_correcoes"] == 503
    assert all(r["avaliacao_id"] == "avaliacao-a" for r in linhas(filtrado["csv"]))


def test_vazio_legado_sem_operacao_e_injecao_em_identificadores(banco):
    repo, dados = banco
    vazio = exportar_correcoes(repo)
    assert vazio["resumo"]["total_correcoes"] == 0
    assert linhas(vazio["csv"]) == []
    with pytest.raises(AvaliacaoInexistente):
        exportar_correcoes(repo, "avaliacao-a")
    preencher(dados, 1)
    registro = dados.pop(("correcoes", f"{1:032x}"))
    registro["id"] = "+identificador"
    dados["correcoes", "+identificador"] = registro
    registro.pop("operacao_id")
    registro["aluno"] = "  @SUM(1)"
    resultado_exportado = exportar_correcoes(repo)
    linha = linhas(resultado_exportado["csv"])[0]
    assert linha["correcao_id"] == "'+identificador"
    assert linha["aluno_nome"] == "'  @SUM(1)"
    assert linha["operacao_id"] == ""
    assert resultado_exportado["resumo"]["operacoes_sem_id"] == 1


def test_exportacao_preserva_origem_do_lote_sem_imagem(banco):
    repo, dados = banco
    preencher(dados, 1)
    dados["correcoes", f"{1:032x}"]["origem_lote"] = {
        "lote_id": "a" * 32, "indice": 0, "imagem_sha256": "b" * 64,
        "arquivo": "digitalizados/cartoes.pdf", "pagina": 2,
    }
    linha = linhas(exportar_correcoes(repo)["csv"])[0]
    assert linha["lote_id"] == "a" * 32
    assert linha["lote_indice"] == "0"
    assert linha["imagem_sha256"] == "b" * 64
    assert linha["arquivo_origem"] == "digitalizados/cartoes.pdf"
    assert linha["pagina_pdf"] == "2"
    assert "imagem" not in linha


def test_nome_pdf_na_exportacao_nao_executa_formula(banco):
    repo, dados = banco
    preencher(dados, 1)
    dados["correcoes", f"{1:032x}"]["origem_lote"] = {
        "lote_id": "a" * 32, "indice": 0, "imagem_sha256": "b" * 64,
        "arquivo": "=HYPERLINK(\"https://exemplo.invalid\")", "pagina": 1,
    }
    linha = linhas(exportar_correcoes(repo)["csv"])[0]
    assert linha["arquivo_origem"].startswith("'=HYPERLINK")


def test_falha_na_segunda_pagina_invalida_exportacao(banco):
    repo, dados = banco
    preencher(dados, 205)
    original = repo.cliente.collection.side_effect
    chamadas = 0

    def colecao(nome):
        nonlocal chamadas
        ref = original(nome)
        if nome == "correcoes":
            consulta = ref.order_by("__name__")
            transmitir = consulta.stream.side_effect
            def falhar(**kwargs):
                nonlocal chamadas
                chamadas += 1
                if chamadas == 2:
                    raise PermissionDenied("falha fictícia")
                return transmitir(**kwargs)
            consulta.stream.side_effect = falhar
            ref.order_by.side_effect = lambda *args, **kwargs: consulta
        return ref
    repo.cliente.collection.side_effect = colecao
    with pytest.raises(ErroPersistencia, match="Leitura incompleta"):
        exportar_correcoes(repo)


def test_limite_explicito_nao_trunca_linhas(banco, monkeypatch):
    repo, dados = banco
    preencher(dados, 205)
    monkeypatch.setattr("app.services.exportacao.MAX_CORRECOES", 200)
    with pytest.raises(LimiteExportacao, match="nenhum arquivo"):
        exportar_correcoes(repo)


def test_endpoint_somente_local_operacional_e_sem_firebase(configuracao, banco):
    repo, dados = banco
    preencher(dados, 2)
    api = criar_app()
    api.dependency_overrides[interface.obter_persistencia] = lambda: repo
    with TestClient(api, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as http:
        response = http.get("/api/correcoes/exportar")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["resumo"]["total_correcoes"] == 2
        assert http.get("/api/correcoes/exportar?prova_id=ausente").status_code == 404
        assert http.get("/api/correcoes/exportar", headers={"Host": "site-publico.com"}).status_code == 403
        assert http.get("/api/correcoes/exportar", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
        api.state.ambiente = "publico_demo"
        assert http.get("/api/correcoes/exportar").status_code == 404
        api.state.ambiente = "homologacao"
        assert http.get("/api/correcoes/exportar").status_code == 404
        api.state.ambiente = "local_operacional"
    assert configuracao.called
