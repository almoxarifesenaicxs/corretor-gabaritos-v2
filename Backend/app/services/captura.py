"""Enquadramento heurístico de folha A4 e retificação de capturas, sem OCR."""

import json
import cv2
import numpy as np

from app.services.reconhecimento import ErroLeitura
from app.services.limites_imagem import validar_cabecalho


def decodificar_captura(conteudo):
    try:
        validar_cabecalho(conteudo)
    except Exception as erro:
        raise ErroLeitura("Imagem ilegível ou acima do limite de pixels.") from erro
    imagem = cv2.imdecode(np.frombuffer(conteudo, np.uint8), cv2.IMREAD_COLOR)
    if imagem is None:
        raise ErroLeitura("Imagem ilegível.")
    return imagem


def analisar_folha(imagem, *, area_minima=0.15):
    """Retorna estado e cantos normalizados; não garante legibilidade da grade."""
    h, w = imagem.shape[:2]
    escala = min(1, 800 / max(h, w))
    miniatura = cv2.resize(imagem, None, fx=escala, fy=escala)
    cinza = cv2.cvtColor(miniatura, cv2.COLOR_BGR2GRAY)
    bordas = cv2.Canny(cv2.GaussianBlur(cinza, (5, 5), 0), 40, 120)
    bordas = cv2.morphologyEx(bordas, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contornos, _ = cv2.findContours(bordas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # Uma borda fina pode ficar interrompida na foto. O papel claro contra um
    # fundo mais escuro fornece um segundo contorno, sem ampliar a imagem.
    _, papel = cv2.threshold(cv2.GaussianBlur(cinza, (5, 5), 0), 0, 255,
                             cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contornos_papel, _ = cv2.findContours(papel, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contornos = list(contornos) + list(contornos_papel)
    altura, largura = cinza.shape
    for contorno in sorted(contornos, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(contorno) / (altura * largura)
        if area < area_minima:
            break
        poligono = cv2.approxPolyDP(contorno, 0.02 * cv2.arcLength(contorno, True), True)
        if len(poligono) != 4 or not cv2.isContourConvex(poligono):
            continue
        pontos = poligono[:, 0, :].astype(np.float32)
        # Ordem cíclica, começando pelo canto superior esquerdo.
        centro = pontos.mean(axis=0)
        pontos = pontos[np.argsort(np.arctan2(pontos[:, 1]-centro[1], pontos[:, 0]-centro[0]))]
        pontos = np.roll(pontos, -int(np.argmin(pontos.sum(axis=1))), axis=0)
        normalizados = pontos / [largura, altura]
        lados = np.linalg.norm(np.roll(pontos, -1, axis=0)-pontos, axis=1)
        razao = (lados[0]+lados[2]) / (lados[1]+lados[3])
        if not 0.48 <= razao <= 0.95:
            continue  # Modelo A4 em retrato; não usar uma tabela larga como folha.
        visivel = bool(np.all(normalizados > 0.025) and np.all(normalizados < 0.975))
        alinhada = (abs(float(pontos[1, 1]-pontos[0, 1])) / lados[0] < 0.07
                    and abs(float(pontos[3, 0]-pontos[0, 0])) / lados[3] < 0.07
                    and max(lados[0], lados[2])/min(lados[0], lados[2]) < 1.12
                    and max(lados[1], lados[3])/min(lados[1], lados[3]) < 1.12)
        centralizada = bool(np.all(abs(normalizados.mean(axis=0)-0.5) < 0.12))
        adequada = visivel and alinhada and centralizada and area >= 0.30 and 0.63 <= razao <= 0.79
        estado = "verde" if adequada else "amarelo" if visivel else "vermelho"
        mensagem = ("Folha enquadrada. Confira foco e iluminação." if adequada else
                    "Ajuste posição, tamanho e inclinação." if visivel else "Mantenha os quatro cantos visíveis.")
        return {"estado": estado, "mensagem": mensagem, "cantos": normalizados.tolist(),
                "folha_visivel": visivel}
    return {"estado": "vermelho", "mensagem": "Folha não detectada. Use fundo contrastante.",
            "cantos": [], "folha_visivel": False}


def validar_cantos_manuais(cantos):
    """Valida TL, TR, BR, BL normalizados sem presumir que a grade é legível."""
    if isinstance(cantos, str):
        if len(cantos) > 256:
            raise ErroLeitura("Cantos manuais inválidos.")
        try:
            cantos = json.loads(cantos)
        except (TypeError, ValueError) as erro:
            raise ErroLeitura("Cantos manuais inválidos.") from erro
    try:
        pontos = np.asarray(cantos, dtype=np.float32)
    except (TypeError, ValueError) as erro:
        raise ErroLeitura("Cantos manuais inválidos.") from erro
    if (pontos.shape != (4, 2) or not np.all(np.isfinite(pontos))
            or np.any(pontos < 0) or np.any(pontos > 1)
            or not cv2.isContourConvex(pontos.reshape(-1, 1, 2))
            or cv2.contourArea(pontos) < 0.05):
        raise ErroLeitura("Cantos manuais inválidos.")
    topo = np.linalg.norm(pontos[1] - pontos[0])
    base = np.linalg.norm(pontos[2] - pontos[3])
    esquerda = np.linalg.norm(pontos[3] - pontos[0])
    direita = np.linalg.norm(pontos[2] - pontos[1])
    largura = max(topo, base)
    altura = max(esquerda, direita)
    if (not 0.40 <= largura / altura <= 1.05
            or pontos[0, 0] >= pontos[1, 0]
            or pontos[3, 0] >= pontos[2, 0]
            or pontos[0, 1] >= pontos[3, 1]
            or pontos[1, 1] >= pontos[2, 1]):
        raise ErroLeitura("Cantos manuais inválidos.")
    return pontos


def retificar_captura(conteudo, cantos=None):
    """Aplica cantos escolhidos ou, na ausência deles, usa detecção opcional."""
    imagem = decodificar_captura(conteudo)
    if cantos is None:
        analise = analisar_folha(imagem)
        if not analise["folha_visivel"]:
            return conteudo
        # Uma tabela lateral pode parecer uma folha; só aceitar candidato central.
        centro = np.mean(analise["cantos"], axis=0)
        if np.any(abs(centro - 0.5) >= 0.12):
            return conteudo
        pontos = np.float32(analise["cantos"])
    else:
        pontos = validar_cantos_manuais(cantos)
    h, w = imagem.shape[:2]
    origem = pontos * np.float32([w, h])
    # A4 retrato observado nos PDFs; evita deformar a proporção do modelo.
    largura, altura = 1240, 1754
    destino = np.float32([[0, 0], [largura-1, 0], [largura-1, altura-1], [0, altura-1]])
    matriz = cv2.getPerspectiveTransform(origem.astype(np.float32), destino)
    retificada = cv2.warpPerspective(imagem, matriz, (largura, altura))
    return cv2.imencode(".png", retificada)[1].tobytes()
