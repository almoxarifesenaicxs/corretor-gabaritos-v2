"""Integração opcional: PDFs privados não são distribuídos no repositório."""

from pathlib import Path

import cv2
import pytest

from app.services.reconhecimento import (
    ErroLeitura, binarizar, carregar_imagem, identificar_tabelas,
    reconhecer_arquivo, reconhecer_imagem,
)

LOCAL = Path(__file__).parent / "fixtures" / "local"
# Transcrição visual das marcas, independente do resultado do algoritmo.
# Matemática reinicia em 1 no papel e ocupa 26–50 no contrato do serviço.
PORTUGUES = "C D A C B D D C C B A C A B B B B C B B A C B C D".split()
MATEMATICA = "C D B C D B B B B B C D C C A B C C B B C C B B B".split()


def arquivo_local(nome):
    caminho = LOCAL / nome
    if not caminho.is_file():
        pytest.skip(f"PDF local ausente: {nome}")
    return caminho


def test_pdf_real_em_branco():
    resultado = reconhecer_arquivo(arquivo_local("Gabarito em Branco.pdf"))
    assert list(resultado) == [str(i) for i in range(1, 51)]
    assert all(valor == {"resposta": None, "estado": "branco", "alternativas": []}
               for valor in resultado.values())


def test_pdf_real_preenchido_contra_transcricao_visual():
    resultado = reconhecer_arquivo(arquivo_local("Gabarito Prova AIB.pdf"))
    assert list(resultado) == [str(i) for i in range(1, 51)]
    for numero, esperada in enumerate(PORTUGUES + MATEMATICA, 1):
        assert resultado[str(numero)] == {
            "resposta": esperada, "estado": "marcada", "alternativas": [esperada],
        }, f"Divergência na questão {numero}"


@pytest.mark.parametrize("caso", ["multipla", "duvidosa", "linha_removida"])
def test_alteracoes_controladas_no_cartao_real(caso):
    # Alterações apenas em memória: não modificam o PDF de referência.
    imagem = carregar_imagem(arquivo_local("Gabarito em Branco.pdf"))
    xs, ys = identificar_tabelas(binarizar(imagem))[0]
    if caso == "linha_removida":
        cv2.line(imagem, (xs[0]-2, ys[10]), (xs[-1]+2, ys[10]), (255, 255, 255), 7)
        with pytest.raises(ErroLeitura):
            reconhecer_imagem(imagem)
        return
    y = (ys[1] + ys[2]) // 2
    if caso == "multipla":
        for coluna in (1, 3):
            x = (xs[coluna] + xs[coluna+1]) // 2
            cv2.line(imagem, (x-5, y-5), (x+5, y+5), (0, 0, 0), 2)
            cv2.line(imagem, (x-5, y+5), (x+5, y-5), (0, 0, 0), 2)
    else:
        x = (xs[1] + xs[2]) // 2
        cv2.rectangle(imagem, (x, y), (x+2, y+2), (0, 0, 0), -1)
    resultado = reconhecer_imagem(imagem)
    assert resultado["1"]["estado"] == caso
    assert resultado["1"]["resposta"] is None
    assert resultado["1"]["alternativas"] == (["A", "C"] if caso == "multipla" else ["A"])
    assert all(resultado[str(i)]["estado"] == "branco" for i in range(2, 51))
