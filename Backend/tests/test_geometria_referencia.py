"""Regressão do modelo geométrico sem imagens ou dados pessoais."""

import cv2
import numpy as np
import pytest

from app.services.correcao_visual import preparar_visualizacao
from app.services.geometria_referencia import identificar_tabelas_modelo
from app.services.reconhecimento import ErroLeitura, binarizar, identificar_tabelas, reconhecer_imagem
from test_fotos_cartoes import _fotografar, _grade_sintetica


def _linha_parcialmente_interrompida():
    imagem = _grade_sintetica()
    # A linha impressa perde 40% de sua largura; os X ficam intactos.
    for inicio in (90, 680):
        cv2.line(imagem, (inicio + 170, 825), (inicio + 335, 825), (255, 255, 255), 8)
    return imagem


@pytest.mark.parametrize("perspectiva,sombra", [(False, False), (True, False), (True, True)])
def test_modelo_recupera_tabelas_com_linhas_parciais_e_revisao_visual(perspectiva, sombra):
    imagem = _fotografar(_linha_parcialmente_interrompida(),
                         perspectiva=perspectiva, sombra=sombra)
    respostas = reconhecer_imagem(imagem)
    assert len(respostas) == 50
    assert [respostas[str(n)]["resposta"] for n in range(1, 51)] == list("ABCDE" * 10)
    visual = preparar_visualizacao(imagem)
    assert len(visual["posicoes"]) == 50


def test_metodo_anterior_rejeita_linha_parcial_e_modelo_encontra_malha():
    binaria = binarizar(_linha_parcialmente_interrompida())
    with pytest.raises(ErroLeitura, match="incompleta|interrompida"):
        identificar_tabelas(binaria)
    assert len(identificar_tabelas_modelo(binaria)) == 2


def test_modelo_rejeita_referencia_sem_evidencia_de_grade():
    imagem = np.full((1754, 1240, 3), 255, np.uint8)
    for x in (90, 505, 680, 1095):
        cv2.line(imagem, (x, 440), (x, 1350), (0, 0, 0), 2)
    assert identificar_tabelas_modelo(binarizar(imagem)) == []


def test_modelo_preserva_branco_e_multipla_sem_inventar_resposta():
    imagem = _linha_parcialmente_interrompida()
    # Questão 1: apagar somente o X; questão 2: acrescentar um segundo X.
    cv2.rectangle(imagem, (158, 480), (182, 505), (255, 255, 255), -1)
    cv2.line(imagem, (303, 520), (317, 534), (0, 0, 0), 2)
    cv2.line(imagem, (303, 534), (317, 520), (0, 0, 0), 2)
    respostas = reconhecer_imagem(imagem)
    assert respostas["1"] == {"resposta": None, "estado": "branco", "alternativas": []}
    assert respostas["2"] == {"resposta": None, "estado": "multipla", "alternativas": ["B", "C"]}
