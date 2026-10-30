import cv2
import numpy as np
import pymupdf
import pytest

from app.services.reconhecimento import (
    ErroLeitura, carregar_imagem, reconhecer_arquivo, reconhecer_imagem,
)


def cartao(marcacoes=None):
    """Modelo sintético: 2 blocos, 25 linhas, 5 círculos por questão."""
    imagem = np.full((1100, 850, 3), 255, dtype=np.uint8)
    for bloco in range(2):
        for linha in range(25):
            for alternativa in range(5):
                centro = (100 + bloco * 400 + alternativa * 45, 70 + linha * 40)
                cv2.circle(imagem, centro, 11, (0, 0, 0), 2)
                marca = (marcacoes or {}).get((bloco * 25 + linha + 1, alternativa))
                if marca == "cheia":
                    cv2.circle(imagem, centro, 8, (0, 0, 0), -1)
                elif marca == "parcial":
                    cv2.circle(imagem, centro, 4, (0, 0, 0), -1)
    return imagem


def test_estados_e_numeracao():
    resultado = reconhecer_imagem(cartao({
        (1, 0): "cheia", (2, 2): "cheia", (4, 4): "cheia",
        (5, 1): "cheia", (5, 3): "cheia", (6, 0): "parcial",
        (26, 1): "cheia", (50, 4): "cheia",
        (7, 0): "cheia", (7, 1): "parcial",
    }))
    assert list(resultado) == [str(i) for i in range(1, 51)]
    assert resultado["1"] == {"resposta": "A", "estado": "marcada", "alternativas": ["A"]}
    assert resultado["2"]["resposta"] == "C"
    assert resultado["3"] == {"resposta": None, "estado": "branco", "alternativas": []}
    assert resultado["4"]["resposta"] == "E"
    assert resultado["5"] == {"resposta": None, "estado": "multipla", "alternativas": ["B", "D"]}
    assert resultado["6"]["estado"] == "duvidosa"
    assert resultado["6"]["resposta"] is None
    assert resultado["7"]["estado"] == "duvidosa"
    assert resultado["7"]["resposta"] is None
    assert resultado["26"]["resposta"] == "B"
    assert resultado["50"]["resposta"] == "E"


@pytest.mark.parametrize("extensao", [".png", ".jpg", ".jpeg"])
def test_imagens_validas(tmp_path, extensao):
    caminho = tmp_path / ("cartão" + extensao)
    imagem = cartao({(50, 2): "cheia"})
    caminho.write_bytes(cv2.imencode(extensao, imagem)[1].tobytes())
    assert carregar_imagem(caminho).shape == imagem.shape
    assert reconhecer_arquivo(caminho)["50"]["resposta"] == "C"


def test_pdf_primeira_pagina(tmp_path):
    caminho = tmp_path / "cartao.pdf"
    imagem = cartao({(1, 3): "cheia"})
    with pymupdf.open() as documento:
        pagina = documento.new_page(width=850, height=1100)
        pagina.insert_image(pagina.rect, stream=cv2.imencode(".png", imagem)[1].tobytes())
        documento.new_page()  # A segunda página em branco não deve ser lida.
        documento.save(str(caminho))
    convertida = carregar_imagem(caminho)
    assert convertida.shape == (2292, 1771, 3)
    assert reconhecer_arquivo(caminho)["1"]["resposta"] == "D"


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        carregar_imagem(tmp_path / "ausente.pdf")


@pytest.mark.parametrize("extensao", [".pdf", ".png", ".jpg", ".txt"])
def test_arquivo_invalido(tmp_path, extensao):
    caminho = tmp_path / ("invalido" + extensao)
    caminho.write_bytes(b"arquivo invalido")
    with pytest.raises(ErroLeitura):
        carregar_imagem(caminho)


@pytest.mark.parametrize("tipo", ["vazio", "incompleto", "desalinhado"])
def test_grade_invalida(tipo):
    imagem = cartao()
    if tipo == "vazio":
        imagem[:] = 255
    elif tipo == "incompleto":
        imagem[50:90, 80:120] = 255
    else:
        imagem[50:90, 80:120] = 255
        cv2.circle(imagem, (115, 70), 11, (0, 0, 0), 2)
    with pytest.raises(ErroLeitura):
        reconhecer_imagem(imagem)


@pytest.mark.parametrize("escala", [0.75, 1.5])
def test_grade_redimensionada(escala):
    imagem = cv2.resize(cartao({(25, 4): "cheia"}), None, fx=escala, fy=escala)
    assert reconhecer_imagem(imagem)["25"]["resposta"] == "E"


def test_pdf_protegido(tmp_path):
    caminho = tmp_path / "protegido.pdf"
    with pymupdf.open() as documento:
        documento.new_page()
        documento.save(str(caminho), encryption=pymupdf.PDF_ENCRYPT_AES_256,
                       owner_pw="dono", user_pw="senha")
    with pytest.raises(ErroLeitura):
        carregar_imagem(caminho)
