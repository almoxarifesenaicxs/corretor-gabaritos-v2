"""Ajuste conservador da malha 2 × (25 × 5) a linhas observadas.

Não contém imagem de cartão nem modelo treinado. O modelo é a topologia da
grade: duas tabelas, sete limites verticais e 27 horizontais por tabela.
"""

import cv2
import numpy as np


def _picos(projecao, minimo, distancia):
    indices = np.flatnonzero(projecao >= minimo)
    grupos = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    picos = [float(np.mean(g)) for g in grupos if g.size]
    unidos = []
    for pico in picos:
        if unidos and pico - unidos[-1] <= distancia:
            unidos[-1] = (unidos[-1] + pico) / 2
        else:
            unidos.append(pico)
    return unidos


def _ajustar_linhas(picos, quantidade, tolerancia, minimo):
    """Interpola só poucos limites ausentes; rejeita fase ou passo incertos."""
    if len(picos) < minimo or len(picos) > quantidade:
        return None
    primeiro, ultimo = picos[0], picos[-1]
    passo = (ultimo - primeiro) / (quantidade - 1)
    if passo <= 4:
        return None
    indices = np.rint((np.asarray(picos) - primeiro) / passo).astype(int)
    previstos = primeiro + indices * passo
    if (len(set(indices)) != len(indices) or indices[0] != 0
            or indices[-1] != quantidade - 1
            or np.max(np.abs(np.asarray(picos) - previstos)) > passo * tolerancia):
        return None
    return [round(primeiro + passo * i) for i in range(quantidade)]


def identificar_tabelas_modelo(binaria):
    """Localiza 250 células por topologia e evidência parcial das linhas.

    Retorna limites nas coordenadas originais. Ausência de âncoras suficientes
    devolve lista vazia; o chamador conserva a rejeição do motor existente.
    """
    altura, largura = binaria.shape
    horizontal = cv2.morphologyEx(binaria, cv2.MORPH_OPEN,
                                 np.ones((1, max(12, largura // 60)), np.uint8))
    vertical = cv2.morphologyEx(binaria, cv2.MORPH_OPEN,
                               np.ones((max(12, altura // 80), 1), np.uint8))
    # Une pequenos trechos, sem preencher as células nem apagar os X.
    malha = cv2.bitwise_or(
        cv2.dilate(horizontal, np.ones((max(3, altura // 120), 1), np.uint8)),
        cv2.dilate(vertical, np.ones((1, max(3, largura // 120)), np.uint8)),
    )
    contornos, _ = cv2.findContours(malha, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidatas = []
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if w < largura * 0.25 or h < altura * 0.30 or not 1.4 <= h / w <= 4:
            continue
        faixa = max(3, round(min(h, w) * 0.012))
        xs = _picos(np.count_nonzero(vertical[y:y+h, x:x+w], axis=0), h * 0.40, faixa)
        ys = _picos(np.count_nonzero(horizontal[y:y+h, x:x+w], axis=1), w * 0.40, faixa)
        if len(xs) != 7:
            continue  # Não inferir a coluna de numeração nem uma alternativa.
        xs = [x + round(p) for p in xs]
        passos = np.diff(xs)
        alternativas = passos[1:]
        if (np.min(passos) <= 4 or np.ptp(alternativas) > np.median(alternativas) * 0.20
                or not 0.25 <= passos[0] / np.median(alternativas) <= 1.5):
            continue
        ys_ajustados = _ajustar_linhas(ys, 27, 0.28, 24)
        if ys_ajustados is None:
            continue
        ys = [y + p for p in ys_ajustados]
        # Evidência em quase toda a malha, tolerando até três horizontais
        # interrompidas. Não aceitar um retângulo vazio ou apenas texto.
        evidentes = 0
        for yy in ys:
            trecho = horizontal[max(0, yy-faixa):min(altura, yy+faixa+1), xs[0]:xs[-1]]
            if trecho.size and np.count_nonzero(np.any(trecho, axis=0)) >= (xs[-1]-xs[0]) * 0.55:
                evidentes += 1
        if evidentes < 24:
            continue
        # A referência é uma malha regular de 6 colunas e 26 faixas, cuja
        # primeira coluna tem largura própria. Estima a transformação dos
        # quatro cantos observados; só a utiliza se os limites internos
        # concordarem. Uma perspectiva ou ondulação maior exige revisão da
        # captura, não extrapolação livre das respostas.
        largura_alt = float(np.median(alternativas))
        largura_num = passos[0] / largura_alt
        referencia = np.float32([[0, 0], [largura_num + 5, 0],
                                 [largura_num + 5, 26], [0, 26]])
        observados = np.float32([[xs[0], ys[0]], [xs[-1], ys[0]],
                                [xs[-1], ys[-1]], [xs[0], ys[-1]]])
        transformacao = cv2.getPerspectiveTransform(referencia, observados)
        pontos = np.float32([[[coluna, linha]] for coluna in
                             [0, largura_num, *[largura_num + k for k in range(1, 6)]]
                             for linha in range(27)])
        projetados = cv2.perspectiveTransform(pontos, transformacao).reshape(7, 27, 2)
        if (np.max(np.abs(projetados[:, :, 0] - np.asarray(xs)[:, None])) > largura_alt * 0.20
                or np.max(np.abs(projetados[:, :, 1] - np.asarray(ys)[None, :])) >
                np.median(np.diff(ys)) * 0.28):
            continue
        candidatas.append((xs, ys))
    candidatas.sort(key=lambda tabela: tabela[0][0])
    if (len(candidatas) != 2 or candidatas[0][0][-1] >= candidatas[1][0][0]
            or np.max(np.abs(np.asarray(candidatas[0][1]) - candidatas[1][1])) > altura * 0.025):
        return []
    return candidatas
