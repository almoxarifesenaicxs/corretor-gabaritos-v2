"""Leitura de cartões A–E: tabelas reais ou círculos do modelo sintético."""

from pathlib import Path

import cv2
import numpy as np
import pymupdf
import math

from app.services.limites_imagem import validar_cabecalho, validar_dimensoes
from app.services.geometria_referencia import identificar_tabelas_modelo


class ErroLeitura(ValueError):
    """Arquivo ilegível ou grade incompatível com o modelo suportado."""


def carregar_imagem(caminho: str | Path) -> np.ndarray:
    """Retorna imagem BGR; PDFs são renderizados na primeira página a 150 dpi."""
    caminho = Path(caminho)
    if not caminho.is_file():
        raise FileNotFoundError(caminho)
    if caminho.suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png"}:
        raise ErroLeitura("Formato incompatível: use PDF, JPG ou PNG.")
    try:
        if caminho.suffix.lower() == ".pdf":
            return converter_pagina_pdf(caminho, 0)
        conteudo = caminho.read_bytes()
        validar_cabecalho(conteudo)
        imagem = cv2.imdecode(np.frombuffer(conteudo, dtype=np.uint8), cv2.IMREAD_COLOR)
        if imagem is None:
            raise ErroLeitura("Imagem corrompida ou ilegível.")
        return imagem
    except ErroLeitura:
        raise
    except Exception as erro:
        raise ErroLeitura("Não foi possível decodificar o arquivo.") from erro


def converter_pagina_pdf(caminho: str | Path, indice: int) -> np.ndarray:
    """Renderiza somente uma página PDF usando o conversor e limites existentes."""
    try:
        # Abrir por stream evita bloqueio do arquivo temporário no Windows
        # quando o construtor falha em um PDF corrompido.
        with pymupdf.open(stream=Path(caminho).read_bytes(), filetype="pdf") as documento:
            if documento.needs_pass or not documento.page_count:
                raise ErroLeitura("PDF protegido ou sem páginas.")
            if not 0 <= indice < documento.page_count:
                raise ErroLeitura("Página PDF inexistente.")
            pagina = documento[indice]
            validar_dimensoes(math.ceil(pagina.rect.width * 150 / 72),
                              math.ceil(pagina.rect.height * 150 / 72))
            pix = pagina.get_pixmap(dpi=150, colorspace=pymupdf.csRGB, alpha=False)
            rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except ErroLeitura:
        raise
    except Exception as erro:
        raise ErroLeitura("Não foi possível converter a página PDF.") from erro


def binarizar(imagem: np.ndarray) -> np.ndarray:
    """Compensa iluminação local antes de separar tinta por Otsu (tinta = 255)."""
    if not isinstance(imagem, np.ndarray) or imagem.dtype != np.uint8 or imagem.size == 0:
        raise ErroLeitura("Esperada imagem não vazia com pixels uint8.")
    if imagem.ndim == 2:
        cinza = imagem
    elif imagem.ndim == 3 and imagem.shape[2] == 3:
        cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    else:
        raise ErroLeitura("Esperada imagem em cinza ou BGR.")
    # Estima o papel ao fechar marcas escuras com uma janela proporcional à
    # página. Dividir pelo fundo evita interpretar regiões sombreadas como tinta.
    # A mesma imagem binária alimenta leitura e sobreposição das alternativas.
    janela = max(3, round(min(cinza.shape) * 0.04)) | 1
    fundo = cv2.morphologyEx(cinza, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (janela, janela)))
    normalizada = cv2.divide(cinza, np.maximum(fundo, 1), scale=255)
    return cv2.threshold(normalizada, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]


def _recortar_folha(imagem: np.ndarray) -> np.ndarray:
    """Retifica contorno de papel comprovado; mantém a resolução observada."""
    # Importação tardia evita o ciclo captura -> reconhecimento -> captura.
    from app.services.captura import analisar_folha

    altura, largura = imagem.shape[:2]
    analise = analisar_folha(imagem, area_minima=0.08)
    if not analise["folha_visivel"]:
        return imagem
    origem = (np.float32(analise["cantos"]) * np.float32([largura, altura])).astype(np.float32)
    topo = np.linalg.norm(origem[1] - origem[0])
    base = np.linalg.norm(origem[2] - origem[3])
    esquerda = np.linalg.norm(origem[3] - origem[0])
    direita = np.linalg.norm(origem[2] - origem[1])
    nova_largura, nova_altura = round(max(topo, base)), round(max(esquerda, direita))
    # Ampliar não recria um X pequeno. Papel menor que isto exige nova foto.
    if nova_largura < 500 or nova_altura < 700:
        return imagem
    try:
        validar_dimensoes(nova_largura, nova_altura)
    except ValueError:
        return imagem
    destino = np.float32([[0, 0], [nova_largura - 1, 0],
                          [nova_largura - 1, nova_altura - 1], [0, nova_altura - 1]])
    matriz = cv2.getPerspectiveTransform(origem, destino)
    return cv2.warpPerspective(imagem, matriz, (nova_largura, nova_altura),
                               borderValue=(255, 255, 255) if imagem.ndim == 3 else 255)


def _alinhar_grade(imagem: np.ndarray) -> np.ndarray:
    """Corrige uma pequena inclinação somente quando linhas da grade concordam."""
    altura, largura = imagem.shape[:2]
    escala = min(1.0, 1200 / max(altura, largura))
    amostra = (cv2.resize(imagem, None, fx=escala, fy=escala,
                         interpolation=cv2.INTER_AREA) if escala < 1 else imagem)
    binaria = binarizar(amostra)
    minimo = max(60, round(binaria.shape[1] * 0.15))
    linhas = cv2.HoughLinesP(binaria, 1, np.pi / 900, threshold=50,
                             minLineLength=minimo, maxLineGap=12)
    if linhas is None:
        return imagem
    angulos = []
    for x1, y1, x2, y2 in linhas.reshape(-1, 4):
        angulo = math.degrees(math.atan2(int(y2) - int(y1), int(x2) - int(x1)))
        if abs(angulo) <= 7:
            angulos.append(angulo)
    if len(angulos) < 12:
        return imagem
    centro = float(np.median(angulos))
    # Texto ou uma única borda não bastam para girar a folha inteira.
    if not 0.35 <= abs(centro) <= 6 or np.mean(np.abs(np.array(angulos) - centro) <= 0.8) < 0.80:
        return imagem
    # A rasterização pode deslocar a estimativa em décimos de grau. Aceitar
    # somente uma rotação cuja grade completa passe nas validações existentes.
    for ajuste in (0, -0.1, 0.1, -0.2, 0.2):
        matriz = cv2.getRotationMatrix2D((largura / 2, altura / 2), centro + ajuste, 1)
        alinhada = cv2.warpAffine(imagem, matriz, (largura, altura),
                                  flags=cv2.INTER_LINEAR,
                                  borderValue=(255, 255, 255) if imagem.ndim == 3 else 255)
        try:
            binaria = binarizar(alinhada)
            if (len(identificar_tabelas(binaria)) == 2
                    or len(identificar_tabelas_modelo(binaria)) == 2):
                return alinhada
        except ErroLeitura:
            if len(identificar_tabelas_modelo(binarizar(alinhada))) == 2:
                return alinhada
    return imagem


def alinhar_imagem(imagem: np.ndarray) -> np.ndarray:
    """Tenta folha e inclinação, aceitando somente uma grade completa."""
    folha = _recortar_folha(imagem)
    for candidata in ((folha, imagem) if folha is not imagem else (imagem,)):
        if candidata is not imagem:
            try:
                binaria = binarizar(candidata)
                if (len(identificar_tabelas(binaria)) == 2
                        or len(identificar_tabelas_modelo(binaria)) == 2):
                    return candidata
            except ErroLeitura:
                if len(identificar_tabelas_modelo(binarizar(candidata))) == 2:
                    return candidata
        alinhada = _alinhar_grade(candidata)
        if alinhada is not candidata:
            return alinhada
    return imagem


def identificar_grade(binaria: np.ndarray) -> list[list[tuple[float, float, float]]]:
    """Localiza 25 linhas de dez círculos; rejeita grades incompletas/desalinhadas."""
    contornos, _ = cv2.findContours(binaria, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    altura, largura = binaria.shape
    circulos = []
    for contorno in contornos:
        area = cv2.contourArea(contorno)
        perimetro = cv2.arcLength(contorno, True)
        _, _, w, h = cv2.boundingRect(contorno)
        # Limites relativos à página, sem coordenadas absolutas do cartão.
        if not (0.006 * min(altura, largura) <= w <= 0.04 * min(altura, largura)):
            continue
        if perimetro == 0 or not 0.8 <= w / h <= 1.2:
            continue
        # Rasterização de PDF cria pequenos degraus no perímetro circular.
        if 4 * np.pi * area / perimetro**2 < 0.68:
            continue
        (cx, cy), raio = cv2.minEnclosingCircle(contorno)
        circulos.append((cx, cy, raio))
    if len(circulos) != 250:
        raise ErroLeitura(f"Grade não identificada: encontrados {len(circulos)} círculos; esperados 250.")
    circulos.sort(key=lambda c: c[1])
    linhas = [sorted(circulos[i:i + 10], key=lambda c: c[0]) for i in range(0, 250, 10)]
    raio = float(np.median([c[2] for c in circulos]))
    centros = np.array([[(c[0], c[1]) for c in linha] for linha in linhas])
    if any(abs(c[2] - raio) > raio * 0.25 for c in circulos):
        raise ErroLeitura("Círculos com tamanhos inconsistentes.")
    if np.max(np.ptp(centros[:, :, 1], axis=1)) > raio * 0.6:
        raise ErroLeitura("Linhas desalinhadas; alinhe o cartão.")
    if np.max(np.ptp(centros[:, :, 0], axis=0)) > raio * 0.6:
        raise ErroLeitura("Colunas desalinhadas; alinhe o cartão.")
    passos_y = np.diff(np.mean(centros[:, :, 1], axis=1))
    passos_x = np.diff(np.mean(centros[:, :, 0], axis=0))
    internos = np.delete(passos_x, 4)
    if (np.min(passos_y) < 2.5 * raio or np.ptp(passos_y) > raio * 0.6
            or np.min(internos) < 2.5 * raio or np.ptp(internos) > raio * 0.6
            or passos_x[4] < np.median(internos) * 1.5):
        raise ErroLeitura("Espaçamento incompatível com os dois blocos de alternativas.")
    return linhas


def reconhecer_imagem(imagem: np.ndarray) -> dict[str, dict]:
    """Retorna 50 questões, com resposta, estado e alternativas candidatas."""
    binaria = binarizar(imagem)
    try:
        tabelas = identificar_tabelas(binaria)
        if tabelas:
            return reconhecer_tabelas(binaria, tabelas)
        linhas = identificar_grade(binaria)
    except ErroLeitura:
        # O caminho comum de scanner mantém custo e pixels originais. Corrigir
        # inclinação somente quando a grade já falhou e há evidência de linhas.
        alinhada = alinhar_imagem(imagem)
        if alinhada is not imagem:
            binaria = binarizar(alinhada)
            try:
                tabelas = identificar_tabelas(binaria)
                if tabelas:
                    return reconhecer_tabelas(binaria, tabelas)
                linhas = identificar_grade(binaria)
            except ErroLeitura:
                tabelas = identificar_tabelas_modelo(binaria)
                if tabelas:
                    return reconhecer_tabelas(binaria, tabelas)
                raise
        else:
            tabelas = identificar_tabelas_modelo(binaria)
            if tabelas:
                return reconhecer_tabelas(binaria, tabelas)
            raise
    resultado = {}
    for bloco in range(2):
        for indice, linha in enumerate(linhas):
            preenchimentos = []
            for x, y, raio in linha[bloco * 5:(bloco + 1) * 5]:
                # Mede apenas o miolo (60% do raio), excluindo a borda impressa.
                r = max(1, int(raio * 0.6))
                cx, cy = round(x), round(y)
                recorte = binaria[cy - r:cy + r + 1, cx - r:cx + r + 1]
                yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
                preenchimentos.append(float(np.mean(recorte[xx * xx + yy * yy <= r * r] > 0)))
            marcadas = ["ABCDE"[i] for i, taxa in enumerate(preenchimentos) if taxa >= 0.55]
            duvidosas = any(0.20 < taxa < 0.55 for taxa in preenchimentos)
            if len(marcadas) > 1:
                estado = "multipla"
            elif duvidosas:
                estado = "duvidosa"
            elif marcadas:
                estado = "marcada"
            else:
                estado = "branco"
            candidatas = ["ABCDE"[i] for i, taxa in enumerate(preenchimentos) if taxa > 0.20]
            resultado[str(bloco * 25 + indice + 1)] = {
                "resposta": marcadas[0] if estado == "marcada" else None,
                "estado": estado,
                "alternativas": candidatas,
            }
    return resultado


def identificar_tabelas(binaria: np.ndarray) -> list[tuple[list[int], list[int]]]:
    """Detecta dois blocos com coluna numérica, A–E, cabeçalho e 25 linhas."""
    altura, largura = binaria.shape
    horizontal = cv2.morphologyEx(binaria, cv2.MORPH_OPEN,
                                 np.ones((1, max(10, largura // 40)), np.uint8))
    vertical = cv2.morphologyEx(binaria, cv2.MORPH_OPEN,
                               np.ones((max(10, altura // 60), 1), np.uint8))
    # Uma ondulação curta desloca a linha alguns pixels; o orçamento é
    # proporcional à folha e muito menor que a largura de uma célula.
    faixa = max(3, round(min(altura, largura) * 0.006)) | 1
    horizontal = cv2.dilate(horizontal, np.ones((faixa, 1), np.uint8))
    vertical = cv2.dilate(vertical, np.ones((1, faixa), np.uint8))
    malha = cv2.bitwise_or(horizontal, vertical)
    contornos, _ = cv2.findContours(malha, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tabelas = []

    def centros(projecao, limiar):
        indices = np.flatnonzero(projecao >= limiar)
        grupos = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
        picos = [int(round(float(np.mean(g)))) for g in grupos if g.size]
        # Uma linha fina ondulada pode produzir dois picos adjacentes na
        # projeção. Eles representam o mesmo limite de célula: a distância
        # é menor que a faixa usada para conectar a malha, não um passo real.
        unidos = []
        for pico in picos:
            if unidos and pico - unidos[-1] <= faixa:
                unidos[-1] = round((unidos[-1] + pico) / 2)
            else:
                unidos.append(pico)
        return unidos

    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if w < largura * 0.25 or h < altura * 0.30:
            continue
        xs = centros(np.count_nonzero(vertical[y:y+h, x:x+w], axis=0), h * 0.7)
        ys = centros(np.count_nonzero(horizontal[y:y+h, x:x+w], axis=1), w * 0.7)
        if len(xs) != 7 or len(ys) != 27:
            raise ErroLeitura("Tabela incompleta: esperadas seis colunas e 26 linhas com cabeçalho.")
        # A coluna de numeração pode ser mais estreita que as cinco alternativas.
        # Compare a regularidade somente entre A–E; preserve a validação de
        # largura mínima para todas as colunas e de espaçamento entre linhas.
        if np.min(np.diff(xs)) <= 3:
            raise ErroLeitura("Tabela com coluna estreita demais.")
        for passos in (np.diff(xs)[1:], np.diff(ys)):
            if np.min(passos) <= 3 or np.ptp(passos) > np.median(passos) * 0.15:
                raise ErroLeitura("Tabela com espaçamento irregular.")
        # Cada limite precisa existir em quase toda a extensão da tabela.
        for xx in xs:
            esquerda = max(x, x + xx - faixa)
            direita = min(x + w, x + xx + faixa + 1)
            if np.count_nonzero(np.any(vertical[y:y+h, esquerda:direita], axis=1)) < h * 0.90:
                raise ErroLeitura("Tabela com linha vertical interrompida.")
        for indice, yy in enumerate(ys):
            # A borda superior não cobre a coluna de numeração.
            minimo = 0.78 if indice == 0 else 0.95
            topo = max(y, y + yy - faixa)
            base = min(y + h, y + yy + faixa + 1)
            if np.count_nonzero(np.any(horizontal[topo:base, x:x+w], axis=0)) < w * minimo:
                raise ErroLeitura("Tabela com linha horizontal interrompida.")
        tabelas.append(([x + xx for xx in xs], [y + yy for yy in ys]))
    if not tabelas:
        return []
    tabelas.sort(key=lambda tabela: tabela[0][0])
    if len(tabelas) != 2 or tabelas[0][0][-1] >= tabelas[1][0][0]:
        raise ErroLeitura("Esperadas duas tabelas de respostas lado a lado.")
    # Os documentos reais têm pequenos deslocamentos entre as duas tabelas.
    if not np.allclose(tabelas[0][1], tabelas[1][1], atol=altura * 0.01, rtol=0):
        raise ErroLeitura("Tabelas de respostas desalinhadas.")
    return tabelas


def reconhecer_tabelas(binaria: np.ndarray, tabelas: list) -> dict[str, dict]:
    """Mede tinta dentro das células; não interpreta letras nem usa OCR."""
    resultado = {}
    for bloco, (xs, ys) in enumerate(tabelas):
        for linha in range(25):
            taxas = []
            for coluna in range(1, 6):
                x1, x2 = xs[coluna:coluna + 2]
                y1, y2 = ys[linha + 1:linha + 3]
                # Margem relativa de 10% exclui as bordas sem perder o X à esquerda.
                mx, my = max(2, round((x2-x1)*0.10)), max(2, round((y2-y1)*0.10))
                celula = binaria[y1+my:y2-my, x1+mx:x2-mx]
                taxas.append(float(np.mean(celula > 0)))
            marcadas = ["ABCDE"[i] for i, taxa in enumerate(taxas) if taxa >= 0.015]
            duvidosa = any(0.003 < taxa < 0.015 for taxa in taxas)
            estado = ("multipla" if len(marcadas) > 1 else "duvidosa" if duvidosa
                      else "marcada" if marcadas else "branco")
            resultado[str(bloco * 25 + linha + 1)] = {
                "resposta": marcadas[0] if estado == "marcada" else None,
                "estado": estado,
                "alternativas": ["ABCDE"[i] for i, taxa in enumerate(taxas) if taxa > 0.003],
            }
    return resultado


def reconhecer_arquivo(caminho: str | Path) -> dict[str, dict]:
    """Carrega um arquivo e reconhece as 50 questões, sem calcular notas."""
    return reconhecer_imagem(carregar_imagem(caminho))
