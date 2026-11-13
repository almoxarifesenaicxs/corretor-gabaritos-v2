"""Regressão das três geometrias reais, sem versionar PDFs com dados pessoais."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import cv2
import numpy as np
import pytest

from app.services.reconhecimento import (
    ErroLeitura, identificar_tabelas, reconhecer_arquivo, reconhecer_tabelas,
)


@pytest.mark.parametrize("nome,esperado", [
    ("2.0.docs.pdf", "CDACBDDCCBACABBBBCBBACBCDCDBCDBBBBBCDCCABCCBBCCBBB"),
    ("Grade_de_respostas_com_linhas (1).pdf",
     "CDACBDDCCBACCBBBBCBBACBCBCDBCDBBBBBCDCCABCCBBCDBBB"),
    ("Grade_de_respostas_com_linhas (2).pdf",
     "CDACBDDCCBACABBBBCBBACBCDCDBCDBBBBBCDCCABCCBBCCBBB"),
])
def test_tres_pdfs_originais_do_zip(nome, esperado):
    arquivo = Path(os.environ.get("CORRETOR_PDFS_VARIANTES_ZIP",
                                  str(Path.home() / "Downloads" / "Nova pasta.zip")))
    if not arquivo.is_file():
        pytest.skip("Forneça CORRETOR_PDFS_VARIANTES_ZIP para testar os PDFs originais.")
    with ZipFile(arquivo) as zip_arquivo:
        conteudo = zip_arquivo.read(f"Nova pasta/{nome}")
    with TemporaryDirectory(prefix="regressao-grade-") as temporario:
        pdf = Path(temporario) / nome
        pdf.write_bytes(conteudo)
        respostas = reconhecer_arquivo(pdf)
    assert len(respostas) == len(esperado) == 50
    assert all(respostas[str(numero)]["estado"] == "marcada" for numero in range(1, 51))
    assert "".join(respostas[str(numero)]["resposta"] for numero in range(1, 51)) == esperado


def _tabelas_sinteticas(larguras):
    binaria = np.zeros((1600, 1300), dtype=np.uint8)
    for inicio in (40, 710):
        xs = [inicio]
        for largura in larguras:
            xs.append(xs[-1] + largura)
        ys = [400 + linha * 33 for linha in range(27)]
        for x in xs:
            cv2.line(binaria, (x, ys[0]), (x, ys[-1]), 255, 2)
        for y in ys:
            cv2.line(binaria, (xs[0], y), (xs[-1], y), 255, 2)
    return binaria


def test_numero_mais_estreito_nao_rejeita_alternativas_regulares():
    tabelas = identificar_tabelas(_tabelas_sinteticas([55, 85, 86, 85, 86, 85]))
    assert len(tabelas) == 2
    assert all(len(xs) == 7 and len(ys) == 27 for xs, ys in tabelas)


def test_alternativas_com_espacamento_irregular_continuam_bloqueadas():
    with pytest.raises(ErroLeitura, match="espaçamento irregular"):
        identificar_tabelas(_tabelas_sinteticas([55, 85, 86, 130, 86, 85]))


def test_geometria_nova_preserva_branco_multipla_e_duvidosa():
    binaria = _tabelas_sinteticas([55, 85, 86, 85, 86, 85])
    tabelas = identificar_tabelas(binaria)

    def marcar(questao, alternativa, fraca=False):
        bloco, linha = divmod(questao - 1, 25)
        xs, ys = tabelas[bloco]
        x = (xs[alternativa + 1] + xs[alternativa + 2]) // 2
        y = (ys[linha + 1] + ys[linha + 2]) // 2
        if fraca:
            cv2.rectangle(binaria, (x - 1, y - 1), (x + 1, y + 1), 255, -1)
        else:
            cv2.line(binaria, (x - 5, y - 5), (x + 5, y + 5), 255, 2)
            cv2.line(binaria, (x - 5, y + 5), (x + 5, y - 5), 255, 2)

    marcar(2, 0)
    marcar(3, 1)
    marcar(3, 2)
    marcar(4, 3, fraca=True)
    marcar(26, 4)
    respostas = reconhecer_tabelas(binaria, tabelas)
    assert respostas["1"] == {"resposta": None, "estado": "branco", "alternativas": []}
    assert respostas["2"] == {"resposta": "A", "estado": "marcada", "alternativas": ["A"]}
    assert respostas["3"] == {"resposta": None, "estado": "multipla", "alternativas": ["B", "C"]}
    assert respostas["4"] == {"resposta": None, "estado": "duvidosa", "alternativas": ["D"]}
    assert respostas["26"] == {"resposta": "E", "estado": "marcada", "alternativas": ["E"]}
