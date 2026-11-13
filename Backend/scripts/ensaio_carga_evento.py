"""Ensaio reproduzível de 1.000 imagens sintéticas pelo ZIP e OCR reais.

Executar a partir de Backend: python scripts/ensaio_carga_evento.py
Não cria clientes Firebase. Os ZIPs e as imagens extraídas ficam em pasta temporária.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.lotes_zip import LotesZIP
from app.services.reconhecimento import carregar_imagem, reconhecer_arquivo
from app.services.correcao import corrigir_respostas
from app.services.correcao_visual import classificar_questoes, preparar_visualizacao
from app.services.integridade import assinar_respostas


QUANTIDADE = 1000
POR_LOTE = 100


def cartao(numero: int) -> tuple[bytes, dict[str, str]]:
    """Grade de 50 questões, com marcas e variações determinísticas."""
    imagem = np.full((1100, 850, 3), 255, dtype=np.uint8)
    esperado = {}
    for bloco in range(2):
        for linha in range(25):
            questao = bloco * 25 + linha + 1
            escolha = (numero + questao) % 5
            # Casos de revisão em 1% dos cartões; o resto contém 50 respostas.
            estado = "branco" if numero % 100 == 0 and questao == 1 else (
                "multipla" if numero % 100 == 1 and questao == 1 else "marcada")
            esperado[str(questao)] = estado
            for alternativa in range(5):
                centro = (100 + bloco * 400 + alternativa * 45, 70 + linha * 40)
                cv2.circle(imagem, centro, 11, (0, 0, 0), 2)
                if estado != "branco" and (alternativa == escolha or
                                           estado == "multipla" and alternativa == (escolha + 1) % 5):
                    cv2.circle(imagem, centro, 8, (0, 0, 0), -1)
    ok, codificada = cv2.imencode(".jpg", imagem, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("Falha ao gerar imagem sintética.")
    return codificada.tobytes(), esperado


def estados_esperados(numero: int) -> dict[str, str]:
    return {str(q): ("branco" if numero % 100 == 0 and q == 1 else
                     "multipla" if numero % 100 == 1 and q == 1 else "marcada")
            for q in range(1, 51)}


def percentil(valores: list[float], p: float) -> float:
    ordenados = sorted(valores)
    posicao = (len(ordenados) - 1) * p / 100
    inferior = int(posicao)
    fracao = posicao - inferior
    return ordenados[inferior] * (1 - fracao) + ordenados[min(inferior + 1, len(ordenados) - 1)] * fracao


def executar() -> dict:
    processo = psutil.Process()
    inicio = time.perf_counter()
    cpu_inicio = sum(processo.cpu_times()[:2])
    pico_rss = processo.memory_info().rss
    latencias, latencias_fluxo, erros, ambiguos, brancos = [], [], [], 0, 0
    total_zip, total_imagens = 0, 0
    primeiro_lote_id = None
    lotes = LotesZIP()
    with tempfile.TemporaryDirectory(prefix="ensaio-gabaritos-") as pasta:
        pasta = Path(pasta)
        # Materializar os dez ZIPs permite testar lotes consecutivos e reimportação.
        geracao_inicio = time.perf_counter()
        for bloco in range(QUANTIDADE // POR_LOTE):
            caminho = pasta / f"lote-{bloco + 1:02}.zip"
            with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as arquivo:
                for posicao in range(POR_LOTE):
                    numero = bloco * POR_LOTE + posicao
                    dados, _ = cartao(numero)
                    arquivo.writestr(f"gabarito-{numero + 1:04}.jpg", dados)
            pico_rss = max(pico_rss, processo.memory_info().rss)
        geracao_s = time.perf_counter() - geracao_inicio
        reconhecimento_inicio = time.perf_counter()
        oficial = {str(q): "A" for q in range(1, 51)}
        for bloco in range(QUANTIDADE // POR_LOTE):
            caminho = pasta / f"lote-{bloco + 1:02}.zip"
            with caminho.open("rb") as arquivo:
                manifesto = lotes.criar(SimpleNamespace(filename=caminho.name, file=arquivo))
            if primeiro_lote_id is None:
                primeiro_lote_id = manifesto["lote_id"]
            total_zip += 1
            assert manifesto["total"] == POR_LOTE
            for item in manifesto["imagens"]:
                numero = bloco * POR_LOTE + item["indice"]
                dados, _, _ = lotes.imagem(manifesto["lote_id"], item["indice"])
                temporaria = pasta / "imagem-em-processamento.jpg"
                temporaria.write_bytes(dados)
                t0 = time.perf_counter()
                try:
                    resposta = reconhecer_arquivo(temporaria)
                    t_reconhecimento = time.perf_counter()
                    resultado = corrigir_respostas(resposta, oficial)
                    comprovante = assinar_respostas(resposta, oficial)
                    marcacoes = classificar_questoes(resposta, oficial)
                    visualizacao = preparar_visualizacao(carregar_imagem(temporaria))
                    if not resultado or not comprovante or len(marcacoes) != 50 or not visualizacao["imagem"]:
                        erros.append({"imagem": numero + 1, "tipo": "fluxo_visual_incompleto"})
                    esperado = estados_esperados(numero)
                    if len(resposta) != 50 or any(resposta[q]["estado"] != estado
                                                   for q, estado in esperado.items()):
                        erros.append({"imagem": numero + 1, "tipo": "resultado_divergente"})
                    ambiguos += sum(item["estado"] in {"duvidosa", "multipla"}
                                     for item in resposta.values())
                    brancos += sum(item["estado"] == "branco" for item in resposta.values())
                except Exception as erro:
                    erros.append({"imagem": numero + 1, "tipo": type(erro).__name__})
                finally:
                    fim = time.perf_counter()
                    latencias.append((t_reconhecimento if "t_reconhecimento" in locals() else fim) - t0)
                    latencias_fluxo.append(fim - t0)
                    if "t_reconhecimento" in locals():
                        del t_reconhecimento
                    temporaria.unlink(missing_ok=True)
                total_imagens += 1
                if total_imagens % 20 == 0:
                    pico_rss = max(pico_rss, processo.memory_info().rss)
                if total_imagens % 100 == 0:
                    print(f"Processadas {total_imagens}/{QUANTIDADE}", flush=True)
            lotes.cancelar(manifesto["lote_id"])
        reconhecimento_s = time.perf_counter() - reconhecimento_inicio
        # Reimportar não substitui nem recupera um lote antigo: novo ID e sem
        # persistência automática. Não se repete OCR para não inflar a amostra.
        with (pasta / "lote-01.zip").open("rb") as arquivo:
            reimportado = lotes.criar(SimpleNamespace(filename="lote-01.zip", file=arquivo))
        reimportacao_novo_id = reimportado["lote_id"] != primeiro_lote_id
        lotes.cancelar(reimportado["lote_id"])
    cpu_s = sum(processo.cpu_times()[:2]) - cpu_inicio
    total_s = time.perf_counter() - inicio
    pico_sistema = getattr(processo.memory_info(), "peak_wset", pico_rss)
    pico_rss = max(pico_rss, pico_sistema)
    return {
        "imagens": total_imagens, "zips": total_zip, "questoes_por_imagem": 50,
        "geracao_s": round(geracao_s, 3), "reconhecimento_s": round(reconhecimento_s, 3),
        "total_s": round(total_s, 3), "mediana_s": round(statistics.median(latencias), 4),
        "p95_s": round(percentil(latencias, 95), 4), "p99_s": round(percentil(latencias, 99), 4),
        "fluxo_mediana_s": round(statistics.median(latencias_fluxo), 4),
        "fluxo_p95_s": round(percentil(latencias_fluxo, 95), 4),
        "fluxo_p99_s": round(percentil(latencias_fluxo, 99), 4),
        "min_s": round(min(latencias), 4), "max_s": round(max(latencias), 4),
        "pico_rss_mib": round(pico_rss / 1024**2, 1), "cpu_processo_s": round(cpu_s, 2),
        "cpu_um_nucleo_percentual": round(100 * cpu_s / total_s, 1),
        "erros": len(erros), "erros_amostra": erros[:20], "questoes_ambiguas": ambiguos,
        "questoes_branco": brancos,
        "reimportacao_novo_id": reimportacao_novo_id,
        "processador": processo.cpu_affinity() if hasattr(processo, "cpu_affinity") else [],
    }


if __name__ == "__main__":
    print(json.dumps(executar(), ensure_ascii=False, indent=2), flush=True)
