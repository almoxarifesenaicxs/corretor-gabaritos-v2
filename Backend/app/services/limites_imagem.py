"""Inspeção de cabeçalho antes da alocação de pixels pelo OpenCV."""

from io import BytesIO
import math
import warnings

from PIL import Image

MAX_DIMENSAO = 6000
MAX_PIXELS = 12_000_000


def validar_dimensoes(largura, altura):
    if (not math.isfinite(largura) or not math.isfinite(altura)
            or largura <= 0 or altura <= 0 or max(largura, altura) > MAX_DIMENSAO
            or largura * altura > MAX_PIXELS):
        raise ValueError("Dimensões excedem o orçamento de imagem.")


def validar_cabecalho(conteudo):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(conteudo)) as imagem:
            if imagem.format not in {"PNG", "JPEG"}:
                raise ValueError("Formato de imagem incompatível.")
            validar_dimensoes(*imagem.size)
            imagem.verify()
