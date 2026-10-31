"""Enquadramento heurístico de folha A4 e retificação de capturas, sem OCR."""

import cv2
import numpy as np

from app.services.reconhecimento import ErroLeitura


def decodificar_captura(conteudo):
    imagem = cv2.imdecode(np.frombuffer(conteudo, np.uint8), cv2.IMREAD_COLOR)
    if imagem is None:
        raise ErroLeitura("Imagem ilegível.")
    return imagem


def analisar_folha(imagem):
    """Retorna estado e cantos normalizados; não garante legibilidade da grade."""
    h, w = imagem.shape[:2]
    escala = min(1, 800 / max(h, w))
    miniatura = cv2.resize(imagem, None, fx=escala, fy=escala)
    cinza = cv2.cvtColor(miniatura, cv2.COLOR_BGR2GRAY)
    bordas = cv2.Canny(cv2.GaussianBlur(cinza, (5, 5), 0), 40, 120)
    bordas = cv2.morphologyEx(bordas, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contornos, _ = cv2.findContours(bordas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    altura, largura = cinza.shape
    for contorno in sorted(contornos, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(contorno) / (altura * largura)
        if area < 0.15:
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


def retificar_captura(conteudo):
    """Corrige somente folha visível; sem detecção mantém a captura manual."""
    imagem = decodificar_captura(conteudo)
    analise = analisar_folha(imagem)
    if not analise["folha_visivel"]:
        return conteudo
    h, w = imagem.shape[:2]
    # Uma tabela de respostas lateral pode parecer uma folha, mas cortaria
    # o cabeçalho/nome. Retificar somente um candidato centralizado.
    centro = np.mean(analise["cantos"], axis=0)
    if np.any(abs(centro - 0.5) >= 0.12):
        return conteudo
    origem = np.float32(analise["cantos"]) * [w, h]
    # A4 retrato observado nos PDFs; evita deformar a proporção do modelo.
    largura, altura = 1240, 1754
    destino = np.float32([[0, 0], [largura-1, 0], [largura-1, altura-1], [0, altura-1]])
    matriz = cv2.getPerspectiveTransform(origem.astype(np.float32), destino)
    retificada = cv2.warpPerspective(imagem, matriz, (largura, altura))
    return cv2.imencode(".png", retificada)[1].tobytes()
