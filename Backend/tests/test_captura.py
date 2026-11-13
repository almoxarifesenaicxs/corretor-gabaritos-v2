import cv2
import numpy as np
import pytest

from app.services.captura import (analisar_folha, retificar_captura,
                                  decodificar_captura, validar_cantos_manuais)
from app.services.reconhecimento import ErroLeitura


def folha(pontos=None):
    imagem = np.full((800, 800, 3), 35, np.uint8)
    if pontos is not None:
        cv2.fillConvexPoly(imagem, np.int32(pontos), (250, 250, 250))
    return imagem


@pytest.mark.parametrize("pontos,estado,visivel,total_cantos", [
    (None, "vermelho", False, 0),
    ([[160, 60], [640, 60], [640, 740], [160, 740]], "verde", True, 4),
    ([[200, 80], [650, 140], [600, 730], [120, 670]], "amarelo", True, 4),
    ([[5, 50], [475, 50], [475, 740], [5, 740]], "vermelho", False, 4),
    ([[280, 230], [520, 230], [520, 570], [280, 570]], "vermelho", False, 0),
])
def test_enquadramento_real(pontos, estado, visivel, total_cantos):
    analise = analisar_folha(folha(pontos))
    assert analise["estado"] == estado
    assert analise["folha_visivel"] is visivel
    assert len(analise["cantos"]) == total_cantos


def test_retificacao_preserva_proporcao_a4():
    imagem = folha([[200, 80], [650, 140], [600, 730], [120, 670]])
    dados = cv2.imencode(".png", imagem)[1].tobytes()
    retificada = decodificar_captura(retificar_captura(dados))
    assert retificada.shape == (1754, 1240, 3)
    assert np.mean(retificada[100:-100, 100:-100]) > 240


def test_captura_manual_sem_folha_nao_inventa_cantos():
    dados = cv2.imencode(".png", folha())[1].tobytes()
    assert retificar_captura(dados) == dados
    with pytest.raises(ErroLeitura):
        decodificar_captura(b"invalida")


def test_cantos_manuais_retificam_folha_sem_enquadramento_verde():
    pontos = [[100, 230], [500, 180], [550, 700], [110, 740]]
    imagem = folha(pontos)
    dados = cv2.imencode(".png", imagem)[1].tobytes()
    assert analisar_folha(imagem)["estado"] != "verde"
    normalizados = (np.array(pontos) / [800, 800]).tolist()
    assert validar_cantos_manuais(normalizados).shape == (4, 2)
    retificada = decodificar_captura(retificar_captura(dados, normalizados))
    assert retificada.shape == (1754, 1240, 3)
    assert np.mean(retificada[100:-100, 100:-100]) > 240


@pytest.mark.parametrize("cantos", [
    "não é JSON", [[0, 0]], [[0, 0], [1, 0], [0, 1], [1, 1]],
    [[0, 0], [1, 0], [1, 1], [0, float("nan")]],
    [[0, 0], [0.1, 0], [0.1, 0.2], [0, 0.2]],
    [[0, 0], [1.1, 0], [1, 1], [0, 1]],
])
def test_cantos_manuais_invalidos_sao_rejeitados(cantos):
    with pytest.raises(ErroLeitura, match="Cantos manuais inválidos"):
        validar_cantos_manuais(cantos)
