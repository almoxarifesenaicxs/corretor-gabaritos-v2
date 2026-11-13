"""Regressão das três geometrias reais, sem versionar PDFs com dados pessoais."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import cv2
import numpy as np
import pytest

from app.services.reconhecimento import (
    ErroLeitura, converter_pagina_pdf, identificar_tabelas, reconhecer_arquivo,
    reconhecer_imagem, reconhecer_tabelas,
)
from app.services.correcao_visual import preparar_visualizacao


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


@pytest.mark.parametrize("nome,esperado", [
    ("2.0.docs.pdf", "CDACBDDCCBACABBBBCBBACBCDCDBCDBBBBBCDCCABCCBBCCBBB"),
    ("Grade_de_respostas_com_linhas (1).pdf",
     "CDACBDDCCBACCBBBBCBBACBCBCDBCDBBBBBCDCCABCCBBCDBBB"),
    ("Grade_de_respostas_com_linhas (2).pdf",
     "CDACBDDCCBACABBBBCBBACBCDCDBCDBBBBBCDCCABCCBBCCBBB"),
])
@pytest.mark.parametrize("variacao", ["rotacao_positiva", "rotacao_negativa", "rotacao_jpeg", "reduzida", "sombra",
                                      "contraste_baixo", "ruido", "jpeg", "png"])
def test_variacoes_dos_tres_cartoes_reais(nome, esperado, variacao):
    arquivo = Path(os.environ.get("CORRETOR_PDFS_VARIANTES_ZIP",
                                  str(Path.home() / "Downloads" / "Nova pasta.zip")))
    if not arquivo.is_file():
        pytest.skip("PDFs originais indisponíveis para regressão visual.")
    with ZipFile(arquivo) as zip_arquivo, TemporaryDirectory(prefix="regressao-grade-") as temporario:
        pdf = Path(temporario) / "cartao.pdf"
        pdf.write_bytes(zip_arquivo.read(f"Nova pasta/{nome}"))
        imagem = converter_pagina_pdf(pdf, 0)
    altura, largura = imagem.shape[:2]
    if variacao.startswith("rotacao_"):
        graus = 2 if variacao == "rotacao_positiva" else -2
        if variacao == "rotacao_jpeg":
            graus = 2
        matriz = cv2.getRotationMatrix2D((largura / 2, altura / 2), graus, 1)
        imagem = cv2.warpAffine(imagem, matriz, (largura, altura), borderValue=(255, 255, 255))
        if variacao == "rotacao_jpeg":
            dados = cv2.imencode(".jpg", imagem, [cv2.IMWRITE_JPEG_QUALITY, 80])[1]
            imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    elif variacao == "reduzida":
        imagem = cv2.resize(imagem, None, fx=0.7, fy=0.7)
    elif variacao == "sombra":
        imagem = (imagem * np.linspace(0.45, 1, altura)[:, None, None]).astype(np.uint8)
    elif variacao == "contraste_baixo":
        imagem = cv2.convertScaleAbs(imagem, alpha=0.55, beta=90)
    elif variacao == "ruido":
        ruido = np.random.default_rng(7).normal(0, 5, imagem.shape)
        imagem = np.clip(imagem.astype(np.int16) + ruido, 0, 255).astype(np.uint8)
    else:
        extensao = ".jpg" if variacao == "jpeg" else ".png"
        dados = cv2.imencode(extensao, imagem)[1]
        imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    respostas = reconhecer_imagem(imagem)
    assert len(respostas) == 50
    assert all(respostas[str(numero)] == {
        "resposta": alternativa, "estado": "marcada", "alternativas": [alternativa]
    } for numero, alternativa in enumerate(esperado, 1))
    if variacao == "rotacao_positiva":
        visual = preparar_visualizacao(imagem)
        assert visual["imagem"] is not None and len(visual["posicoes"]) == 50


def test_perspectiva_sem_retificacao_nao_inventa_alternativa():
    arquivo = Path(os.environ.get("CORRETOR_PDFS_VARIANTES_ZIP",
                                  str(Path.home() / "Downloads" / "Nova pasta.zip")))
    if not arquivo.is_file():
        pytest.skip("PDFs originais indisponíveis para teste de perspectiva.")
    with ZipFile(arquivo) as zip_arquivo, TemporaryDirectory(prefix="regressao-grade-") as temporario:
        pdf = Path(temporario) / "cartao.pdf"
        pdf.write_bytes(zip_arquivo.read("Nova pasta/Grade_de_respostas_com_linhas (2).pdf"))
        imagem = converter_pagina_pdf(pdf, 0)
    altura, largura = imagem.shape[:2]
    origem = np.float32([[0, 0], [largura-1, 0], [largura-1, altura-1], [0, altura-1]])
    destino = np.float32([[largura*.005, 0], [largura-1-largura*.005, altura*.005],
                          [largura-1, altura-1], [0, altura-1-altura*.005]])
    distorcida = cv2.warpPerspective(imagem, cv2.getPerspectiveTransform(origem, destino),
                                    (largura, altura), borderValue=(255, 255, 255))
    esperado = "CDACBDDCCBACABBBBCBBACBCDCDBCDBBBBBCDCCABCCBBCCBBB"
    try:
        respostas = reconhecer_imagem(distorcida)
    except ErroLeitura:
        return  # Sem quatro cantos confiáveis, rejeitar a grade é seguro.
    assert all(respostas[str(numero)]["resposta"] in (None, alternativa)
               for numero, alternativa in enumerate(esperado, 1))


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


def test_tabelas_sinteticas_rotacionadas_mantem_numeracao():
    binaria = _tabelas_sinteticas([55, 85, 86, 85, 86, 85])
    tabelas = identificar_tabelas(binaria)
    for numero in range(1, 51):
        bloco, linha = divmod(numero - 1, 25)
        coluna = (numero - 1) % 5 + 1
        xs, ys = tabelas[bloco]
        x = (xs[coluna] + xs[coluna + 1]) // 2
        y = (ys[linha + 1] + ys[linha + 2]) // 2
        cv2.line(binaria, (x-5, y-5), (x+5, y+5), 255, 2)
        cv2.line(binaria, (x-5, y+5), (x+5, y-5), 255, 2)
    imagem = cv2.cvtColor(255 - binaria, cv2.COLOR_GRAY2BGR)
    altura, largura = imagem.shape[:2]
    for graus in (-2, 2):
        matriz = cv2.getRotationMatrix2D((largura / 2, altura / 2), graus, 1)
        rodada = cv2.warpAffine(imagem, matriz, (largura, altura), borderValue=(255, 255, 255))
        respostas = reconhecer_imagem(rodada)
        assert [respostas[str(numero)]["resposta"] for numero in range(1, 51)] == list("ABCDE" * 10)


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
