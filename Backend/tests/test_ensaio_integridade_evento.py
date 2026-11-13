"""Ensaio de 1.000 gravações fictícias pelo contrato real de persistência.

O cliente Firestore é simulado pela fixture banco; não se abre conexão externa.
"""

import csv
from io import BytesIO, StringIO
from types import SimpleNamespace
from uuid import UUID
from zipfile import ZipFile

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from app.services.exportacao import exportar_correcoes
from app.services.lotes_zip import LotesZIP
from app.services.persistencia import Persistencia
from suporte_estabilizacao import entrada_segura
from test_persistencia import banco


def test_mil_correcoes_idempotencia_recuperacao_e_exportacao(banco):
    repo, dados = banco
    prova = repo.criar_avaliacao("Evento fictício", {str(i): "A" for i in range(1, 51)})
    ids, operacoes = set(), set()
    perdidas = []
    for indice in range(1000):
        body = entrada_segura(prova["id"])
        body["aluno"] = f"Aluno fictício {indice + 1:04}"
        origem = {"lote_id": f"{indice // 100 + 1:032x}", "indice": indice % 100,
                  "imagem_sha256": f"{indice + 1:064x}"}
        argumentos = dict(respostas=body["respostas"], comprovante=body["comprovante"],
                          operacao_id=body["operacao_id"], origem_lote=origem)
        registro = repo.salvar_correcao(body["prova_id"], body["aluno"], body["resultado"],
                                        **argumentos)
        ids.add(registro["id"])
        operacoes.add(body["operacao_id"])
        if indice % 100 == 0:
            # A resposta HTTP se perdeu: consultar o ID antes de um reenvio.
            perdidas.append((body, argumentos, registro["id"]))
    assert len(ids) == len(operacoes) == 1000
    assert len([chave for chave in dados if chave[0] == "correcoes"]) == 1000

    # Novo objeto de serviço representa o reinício do backend; o banco fictício
    # continua contendo os commits e as operações podem ser reconciliadas.
    reiniciado = Persistencia(repo.cliente)
    for body, argumentos, identificador in perdidas:
        estado = reiniciado.consultar_operacao_correcao(body["operacao_id"])
        assert estado["estado"] == "confirmada"
        assert estado["registro"]["id"] == identificador
        repetido = reiniciado.salvar_correcao(body["prova_id"], body["aluno"], body["resultado"],
                                              **argumentos)
        assert repetido["id"] == identificador
    assert len([chave for chave in dados if chave[0] == "correcoes"]) == 1000

    exportado = exportar_correcoes(reiniciado, prova["id"])
    linhas = list(csv.DictReader(StringIO(exportado["csv"].lstrip("\ufeff")), delimiter=";"))
    assert len(linhas) == exportado["resumo"]["total_correcoes"] == 1000
    assert exportado["resumo"]["alunos_distintos"] == 1000
    assert {linha["correcao_id"] for linha in linhas} == ids
    assert {linha["operacao_id"] for linha in linhas} == operacoes
    assert {linha["lote_id"] for linha in linhas} == {f"{n:032x}" for n in range(1, 11)}
    assert all(0 <= int(linha["lote_indice"]) < 100 for linha in linhas)
    assert all(len(linha["imagem_sha256"]) == 64 for linha in linhas)
    assert all(UUID(linha["operacao_id"]) for linha in linhas)


def test_reinicio_perde_zip_temporario_e_reimportacao_recebe_novo_id():
    imagem = np.full((1100, 850, 3), 255, dtype=np.uint8)
    for bloco in range(2):
        for linha in range(25):
            for alternativa in range(5):
                cv2.circle(imagem, (100 + bloco * 400 + alternativa * 45, 70 + linha * 40),
                           11, (0, 0, 0), 2)
    conteudo = cv2.imencode(".jpg", imagem)[1].tobytes()
    saida = BytesIO()
    with ZipFile(saida, "w") as zip_arquivo:
        zip_arquivo.writestr("cartao.jpg", conteudo)
    origem = LotesZIP()
    primeiro = origem.criar(SimpleNamespace(filename="lote.zip", file=BytesIO(saida.getvalue())))
    reiniciado = LotesZIP()
    with pytest.raises(HTTPException) as erro:
        reiniciado.manifesto(primeiro["lote_id"])
    assert erro.value.status_code == 404
    segundo = reiniciado.criar(SimpleNamespace(filename="lote.zip", file=BytesIO(saida.getvalue())))
    assert segundo["lote_id"] != primeiro["lote_id"]
    assert segundo["total"] == primeiro["total"] == 1
    origem.cancelar(primeiro["lote_id"])
    reiniciado.cancelar(segundo["lote_id"])
