"""Fotos simuladas a partir de grades sintéticas e PDFs conferidos visualmente."""

from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import os

import cv2
import numpy as np
import pytest

from app.services.captura import retificar_captura
from app.services.correcao_visual import preparar_visualizacao
from app.services.reconhecimento import ErroLeitura, converter_pagina_pdf, reconhecer_imagem


REFERENCIAS = [
    ("2.0.docs.pdf", "CDACBDDCCBACABBBBCBBACBCDCDBCDBBBBBCDCCABCCBBCCBBB"),
    ("Grade_de_respostas_com_linhas (1).pdf",
     "CDACBDDCCBACCBBBBCBBACBCBCDBCDBBBBBCDCCABCCBBCDBBB"),
    ("Grade_de_respostas_com_linhas (2).pdf",
     "CDACBDDCCBACABBBBCBBACBCDCDBCDBBBBBCDCCABCCBBCCBBB"),
]


def _fotografar(pagina, *, perspectiva=False, sombra=False, fundo=55):
    pagina = cv2.resize(pagina, (1050, 1480), interpolation=cv2.INTER_AREA)
    altura, largura = 2600, 2200
    if perspectiva:
        origem = np.float32([[0, 0], [1049, 0], [1049, 1479], [0, 1479]])
        destino = np.float32([[520, 460], [1670, 510], [1580, 2010], [560, 1970]])
        foto = cv2.warpPerspective(pagina, cv2.getPerspectiveTransform(origem, destino),
                                  (largura, altura), borderValue=(fundo, fundo, fundo))
    else:
        foto = np.full((altura, largura, 3), fundo, np.uint8)
        foto[500:1980, 575:1625] = pagina
    if sombra:
        foto = (foto * np.linspace(0.55, 1, altura)[:, None, None]).astype(np.uint8)
    return foto


def _grade_sintetica():
    pagina = np.full((1754, 1240, 3), 255, np.uint8)
    for bloco, inicio in enumerate((90, 680)):
        xs = [inicio, inicio + 45] + [inicio + 45 + 70 * n for n in range(1, 6)]
        ys = [440 + 35 * linha for linha in range(27)]
        for x in xs:
            cv2.line(pagina, (x, ys[0]), (x, ys[-1]), (0, 0, 0), 2)
        for y in ys:
            cv2.line(pagina, (xs[0], y), (xs[-1], y), (0, 0, 0), 2)
        for linha in range(25):
            coluna = (bloco * 25 + linha) % 5 + 1
            x = (xs[coluna] + xs[coluna + 1]) // 2
            y = (ys[linha + 1] + ys[linha + 2]) // 2
            cv2.line(pagina, (x-7, y-7), (x+7, y+7), (0, 0, 0), 2)
            cv2.line(pagina, (x-7, y+7), (x+7, y-7), (0, 0, 0), 2)
    return pagina


@pytest.mark.parametrize("perspectiva,sombra,fundo", [(False, False, 55), (True, False, 55),
                                                      (True, True, 55), (False, False, 225)])
def test_foto_sintetica_com_margens_e_x_pequenos(perspectiva, sombra, fundo):
    foto = _fotografar(_grade_sintetica(), perspectiva=perspectiva, sombra=sombra, fundo=fundo)
    respostas = reconhecer_imagem(foto)
    assert [respostas[str(numero)]["resposta"] for numero in range(1, 51)] == list("ABCDE" * 10)
    visual = preparar_visualizacao(foto)
    assert visual["imagem"] is not None and len(visual["posicoes"]) == 50


@pytest.mark.parametrize("nome,esperado", REFERENCIAS)
@pytest.mark.parametrize("perspectiva,sombra", [(False, False), (True, False), (True, True)])
def test_pdfs_conferidos_em_fotos_simuladas(nome, esperado, perspectiva, sombra):
    arquivo = Path(os.environ.get("CORRETOR_PDFS_VARIANTES_ZIP",
                                  str(Path.home() / "Downloads" / "Nova pasta.zip")))
    if not arquivo.is_file():
        pytest.skip("PDFs originais indisponíveis; teste sintético permanece ativo.")
    with ZipFile(arquivo) as zip_arquivo, TemporaryDirectory(prefix="foto-grade-") as temporario:
        pdf = Path(temporario) / "cartao.pdf"
        pdf.write_bytes(zip_arquivo.read(f"Nova pasta/{nome}"))
        pagina = converter_pagina_pdf(pdf, 0)
    foto = _fotografar(pagina, perspectiva=perspectiva, sombra=sombra)
    respostas = reconhecer_imagem(foto)
    assert len(respostas) == 50
    assert [respostas[str(numero)]["resposta"] for numero in range(1, 51)] == list(esperado)


def test_folha_pequena_demais_nao_inventa_respostas():
    pagina = cv2.resize(_grade_sintetica(), (350, 495), interpolation=cv2.INTER_AREA)
    foto = np.full((2600, 2200, 3), 55, np.uint8)
    foto[950:1445, 925:1275] = pagina
    with pytest.raises(ErroLeitura):
        reconhecer_imagem(foto)


def test_ondulacao_leve_sinaliza_incerteza_sem_trocar_alternativa():
    pagina = _grade_sintetica()
    altura, largura = pagina.shape[:2]
    yy, xx = np.indices((altura, largura), dtype=np.float32)
    ondulada = cv2.remap(pagina, (xx + 3*np.sin(yy/160)).astype(np.float32),
                         (yy + 3*np.sin(xx/170)).astype(np.float32),
                         cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    respostas = reconhecer_imagem(_fotografar(ondulada, perspectiva=True))
    esperado = "ABCDE" * 10
    assert sum(respostas[str(i+1)]["resposta"] == esperado[i] for i in range(50)) >= 30
    assert all(respostas[str(i+1)]["resposta"] in (None, esperado[i]) for i in range(50))


def test_pipeline_camera_com_ondulacao_nao_rejeita_nem_inventa_respostas():
    pagina = _grade_sintetica()
    altura, largura = pagina.shape[:2]
    yy, xx = np.indices((altura, largura), dtype=np.float32)
    ondulada = cv2.remap(pagina, (xx + 5*np.sin(yy/160)).astype(np.float32),
                         (yy + 5*np.sin(xx/170)).astype(np.float32),
                         cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    foto = _fotografar(ondulada, perspectiva=True)
    foto = cv2.resize(foto, None, fx=2560/2600, fy=2560/2600,
                      interpolation=cv2.INTER_AREA)
    jpeg = cv2.imencode(".jpg", foto, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
    recebida = cv2.imdecode(np.frombuffer(retificar_captura(jpeg), np.uint8), cv2.IMREAD_COLOR)
    assert recebida.shape[:2] == (1754, 1240)
    respostas = reconhecer_imagem(recebida)
    assert len(respostas) == 50
    esperado = "ABCDE" * 10
    assert any(respostas[str(i+1)]["resposta"] == esperado[i] for i in range(50))
    assert all(respostas[str(i+1)]["resposta"] in (None, esperado[i]) for i in range(50))


@pytest.mark.parametrize("nome,esperado", REFERENCIAS)
def test_pipeline_camera_preserva_tres_cartoes_pdf(nome, esperado):
    arquivo = Path(os.environ.get("CORRETOR_PDFS_VARIANTES_ZIP",
                                  str(Path.home() / "Downloads" / "Nova pasta.zip")))
    if not arquivo.is_file():
        pytest.skip("PDFs originais indisponíveis para regressão.")
    with ZipFile(arquivo) as zip_arquivo, TemporaryDirectory(prefix="foto-grade-") as temporario:
        pdf = Path(temporario) / "cartao.pdf"
        pdf.write_bytes(zip_arquivo.read(f"Nova pasta/{nome}"))
        pagina = converter_pagina_pdf(pdf, 0)
    foto = _fotografar(pagina, perspectiva=True, sombra=True)
    foto = cv2.resize(foto, None, fx=2560/2600, fy=2560/2600,
                      interpolation=cv2.INTER_AREA)
    jpeg = cv2.imencode(".jpg", foto, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
    recebida = cv2.imdecode(np.frombuffer(retificar_captura(jpeg), np.uint8), cv2.IMREAD_COLOR)
    respostas = reconhecer_imagem(recebida)
    assert [respostas[str(i)]["resposta"] for i in range(1, 51)] == list(esperado)


@pytest.mark.parametrize("nome,esperado", REFERENCIAS)
def test_resolucao_final_jpeg_preserva_x(nome, esperado):
    arquivo = Path(os.environ.get("CORRETOR_PDFS_VARIANTES_ZIP",
                                  str(Path.home() / "Downloads" / "Nova pasta.zip")))
    if not arquivo.is_file():
        pytest.skip("PDFs originais indisponíveis; teste sintético permanece ativo.")
    with ZipFile(arquivo) as zip_arquivo, TemporaryDirectory(prefix="foto-grade-") as temporario:
        pdf = Path(temporario) / "cartao.pdf"
        pdf.write_bytes(zip_arquivo.read(f"Nova pasta/{nome}"))
        pagina = converter_pagina_pdf(pdf, 0)
    foto = _fotografar(pagina, perspectiva=True)
    foto = cv2.resize(foto, None, fx=2560/2600, fy=2560/2600, interpolation=cv2.INTER_AREA)
    dados = cv2.imencode(".jpg", foto, [cv2.IMWRITE_JPEG_QUALITY, 92])[1]
    assert len(dados) < 10 * 1024 * 1024
    respostas = reconhecer_imagem(cv2.imdecode(dados, cv2.IMREAD_COLOR))
    assert [respostas[str(numero)]["resposta"] for numero in range(1, 51)] == list(esperado)
