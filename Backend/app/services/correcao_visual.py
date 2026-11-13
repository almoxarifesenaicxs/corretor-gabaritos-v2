"""Geometria da imagem processada; reutiliza os detectores existentes."""

import base64
import cv2

from app.services.reconhecimento import alinhar_imagem, binarizar, identificar_grade, identificar_tabelas, ErroLeitura


def classificar_questoes(respostas, gabarito):
    # Classificação para apresentação, sem calcular notas ou resolver pendências.
    return {numero: {
        "estado": ("branco" if item["estado"] == "branco" else
                   "pendente" if item["estado"] in {"multipla", "duvidosa"} else
                   "correta" if item["resposta"] == gabarito[numero] else "incorreta"),
        "alternativas": item["alternativas"].copy(),
    } for numero, item in respostas.items()}


def localizar_alternativas(imagem):
    return _localizar_alternativas_alinhadas(alinhar_imagem(imagem))


def _localizar_alternativas_alinhadas(imagem):
    binaria = binarizar(imagem)
    tabelas = identificar_tabelas(binaria)
    posicoes = {}
    if tabelas:
        for bloco, (xs, ys) in enumerate(tabelas):
            for linha in range(25):
                posicoes[str(bloco*25+linha+1)] = {
                    letra: {"x": xs[coluna+1], "y": ys[linha+1],
                            "largura": xs[coluna+2]-xs[coluna+1],
                            "altura": ys[linha+2]-ys[linha+1]}
                    for coluna, letra in enumerate("ABCDE")}
    else:
        linhas = identificar_grade(binaria)
        for bloco in range(2):
            for linha, circulos in enumerate(linhas):
                posicoes[str(bloco*25+linha+1)] = {
                    letra: {"x": x-raio, "y": y-raio, "largura": raio*2, "altura": raio*2}
                    for letra, (x, y, raio) in zip("ABCDE", circulos[bloco*5:bloco*5+5])}
    return posicoes


def preparar_visualizacao(imagem):
    try:
        imagem = alinhar_imagem(imagem)
        posicoes = localizar_alternativas(imagem)
    except (ErroLeitura, cv2.error):
        return {"imagem": None, "posicoes": {},
                "mensagem": "Posições não localizadas com segurança. Confira o resultado textual."}
    altura, largura = imagem.shape[:2]
    return {"imagem": "data:image/png;base64," + base64.b64encode(cv2.imencode('.png', imagem)[1]).decode('ascii'),
            "largura": largura, "altura": altura, "posicoes": posicoes,
            "mensagem": "Sobreposição na imagem processada. O arquivo original não foi alterado."}
