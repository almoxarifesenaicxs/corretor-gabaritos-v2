"""OCR local e conservador do campo Candidato dos dois cartões de referência."""

from functools import lru_cache
from pathlib import Path
from threading import Lock
import math
import unicodedata

import cv2
import numpy as np

_lock = Lock()
LIMIAR_CONFIANCA = 0.96


def recortar_nome(imagem):
    """Localiza a primeira linha longa do cabeçalho (Candidato), antes de Curso.

    Os dois PDFs têm posições verticais diferentes; usam-se as linhas impressas
    e proporções da página, sem escolher o modelo por nome de arquivo.
    """
    altura, largura = imagem.shape[:2]
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    binaria = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    # Une pequenos intervalos entre os sublinhados do PDF preenchido.
    linhas_unidas = cv2.morphologyEx(binaria, cv2.MORPH_CLOSE,
                                   np.ones((1, max(3, round(largura*.004))), np.uint8))
    horizontais = cv2.morphologyEx(linhas_unidas, cv2.MORPH_OPEN,
                                 np.ones((1, max(30, round(largura * .35))), np.uint8))
    contornos, _ = cv2.findContours(horizontais, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    linhas = sorted((cv2.boundingRect(c) for c in contornos), key=lambda r: r[1])
    linhas = [(x, y, w, h) for x, y, w, h in linhas
              if .10 * altura < y < .37 * altura and w > .50 * largura
              and .14 * largura < x < .30 * largura and x+w > .70 * largura]
    if len(linhas) < 2:
        return None
    x, y, w, h = linhas[0]
    curso_x, curso_y, _, _ = linhas[1]
    # Nos dois modelos o rótulo Candidato é maior que Curso; evita usar outra linha.
    if x < curso_x + .015 * largura or not .015 * altura < curso_y-y < .10 * altura:
        return None
    acima = round(min(.035 * altura, .65 * (curso_y-y)))
    margem = max(2, round(.002 * largura))
    y1, y2 = max(0, y-acima), min(altura, y+h+round(.007*altura))
    x1, x2 = x+margem, min(largura, x+w-margem)
    recorte = cinza[y1:y2, x1:x2].copy()
    # Apaga somente a linha horizontal impressa; conserva possíveis descendentes.
    recorte[horizontais[y1:y2, x1:x2] > 0] = 255
    return recorte


@lru_cache(maxsize=1)
def _motor():
    import rapidocr
    pasta = Path(rapidocr.__file__).parent / "models"
    modelos = {"Det": "PP-OCRv6_det_small.onnx", "Rec": "PP-OCRv6_rec_small.onnx",
               "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx"}
    if any(not (pasta / nome).is_file() for nome in modelos.values()):
        raise RuntimeError("Modelos OCR locais ausentes.")
    # Caminhos explícitos: não usar seleção/download remoto automático de modelos.
    params = {f"{tipo}.model_path": str(pasta / nome) for tipo, nome in modelos.items()}
    params.update({"Global.use_cls": False, "Global.log_level": "error",
                   "Global.text_score": 0.0, "Det.limit_type": "max", "Det.limit_side_len": 1280,
                   "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                   "EngineConfig.onnxruntime.inter_op_num_threads": 1})
    return rapidocr.RapidOCR(params=params)


def _retorno(estado, nome=None, confianca=None):
    mensagens = {
        "nao_identificado": "Nome não identificado. Preencha manualmente.",
        "baixa_confianca": "Leitura do nome sem confiança suficiente. Preencha manualmente.",
        "indisponivel": "OCR local indisponível. Preencha o nome manualmente.",
        "sugerido": "Nome sugerido pelo OCR. Confira e corrija antes de confirmar o salvamento.",
    }
    return {"nome": nome, "estado": estado, "confianca": confianca, "mensagem": mensagens[estado]}


def ler_nome(imagem):
    """Retorna sugestão revisável; falhas de OCR nunca impedem a correção."""
    recorte = recortar_nome(imagem)
    if recorte is None:
        return _retorno("nao_identificado")
    # Campo limpo não deve ser enviado nem ao modelo, evitando alucinação em branco.
    if np.count_nonzero(recorte < 160) < max(12, recorte.size * .001):
        return _retorno("nao_identificado")
    if not _lock.acquire(timeout=10):
        return _retorno("indisponivel")
    try:
        resultado = _motor()(cv2.cvtColor(recorte, cv2.COLOR_GRAY2BGR))
        textos, scores = resultado.txts, resultado.scores
        if not textos or scores is None or len(textos) != len(scores):
            return _retorno("nao_identificado")
        # Usa a ordem de leitura do detector. Não tenta completar letras ou nomes.
        nome = " ".join(" ".join(texto.split()) for texto in textos).strip()
        confianca = min(float(score) for score in scores)
        permitido = all(c in " '-’." or c.isalpha() and "LATIN" in unicodedata.name(c, "") for c in nome)
        rotulos = {"candidato", "curso", "data", "nome", "portugues", "matematica", "senai"}
        valido = (4 <= len(nome) <= 120 and 2 <= len(nome.split()) <= 10 and permitido
                  and not any(palavra.strip(".:").casefold() in rotulos for palavra in nome.split()))
        if not valido or not math.isfinite(confianca) or confianca < LIMIAR_CONFIANCA:
            return _retorno("baixa_confianca")
        return _retorno("sugerido", nome, round(confianca, 4))
    except Exception:
        return _retorno("indisponivel")
    finally:
        _lock.release()
