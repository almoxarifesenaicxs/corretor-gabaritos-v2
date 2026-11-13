"""Integração HTTP dos serviços de reconhecimento e correção."""

import json
import logging
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image

from app.services.correcao import corrigir_respostas, validar_gabarito
from app.services.reconhecimento import ErroLeitura, reconhecer_arquivo
from app.services.captura import retificar_captura
from app.services.reconhecimento import carregar_imagem
from app.services.correcao_visual import preparar_visualizacao, classificar_questoes
from app.services.integridade import assinar_respostas

router = APIRouter(prefix="/api/correcoes", tags=["Correções"])
logger = logging.getLogger(__name__)
LIMITE_UPLOAD = 10 * 1024 * 1024
ASSINATURAS = {".pdf": b"%PDF-", ".png": b"\x89PNG\r\n\x1a\n",
               ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}


def _dimensoes_cabecalho(conteudo):
    """Lê somente metadados da imagem; nunca registra pixels ou nomes."""
    try:
        with Image.open(BytesIO(conteudo)) as imagem:
            return imagem.size
    except (OSError, ValueError):
        return (0, 0)


def _etapa_rejeicao(erro):
    """Código estável para diagnóstico, sem enviar detalhes internos ao cliente."""
    motivo = str(erro)
    if motivo.startswith("Tabela incompleta"):
        return "tabela_contagem_linhas_colunas"
    if motivo.startswith("Tabela com linha vertical interrompida"):
        return "tabela_continuidade_vertical"
    if motivo.startswith("Tabela com linha horizontal interrompida"):
        return "tabela_continuidade_horizontal"
    if motivo.startswith("Tabela com espaçamento irregular") or motivo.startswith("Tabela com coluna estreita"):
        return "tabela_espacamento"
    if motivo.startswith("Esperadas duas tabelas") or motivo.startswith("Tabelas de respostas desalinhadas"):
        return "tabelas_posicionamento"
    if motivo.startswith("Grade") or motivo.startswith("Círculos") or motivo.startswith("Linhas") or motivo.startswith("Colunas"):
        return "grade_circular"
    if motivo.startswith("Espaçamento"):
        return "espacamento"
    if motivo.startswith("Imagem") or motivo.startswith("Não foi possível decodificar"):
        return "decodificacao"
    if motivo.startswith("PDF") or motivo.startswith("Não foi possível converter"):
        return "pdf"
    return "nao_classificada"


def _objeto_sem_duplicatas(pares):
    objeto = {}
    for chave, valor in pares:
        if chave in objeto:
            raise ValueError("Chave JSON duplicada.")
        objeto[chave] = valor
    return objeto


def ler_upload(arquivo, limite):
    """Valida upload para reutilização nas rotas da interface."""
    extensao = Path(arquivo.filename or "").suffix.lower()
    if extensao not in ASSINATURAS:
        raise HTTPException(415, "Formato não suportado. Use PDF, JPG ou PNG.")
    if arquivo.size is not None and arquivo.size > limite:
        raise HTTPException(413, "O arquivo excede o limite de 10 MiB.")
    conteudo = arquivo.file.read(limite + 1)
    if len(conteudo) > limite:
        raise HTTPException(413, "O arquivo excede o limite de 10 MiB.")
    if not conteudo:
        raise HTTPException(400, "O arquivo está vazio.")
    if not conteudo.startswith(ASSINATURAS[extensao]):
        raise HTTPException(415, "O conteúdo do arquivo não corresponde ao formato informado.")
    return conteudo, extensao


@router.post("/processar")
def processar(
    arquivo: Annotated[UploadFile, File(description="Cartão PDF, JPG ou PNG, até 10 MiB.")],
    gabarito: Annotated[str, Form(description='JSON com as chaves "1" a "50" e alternativas A–E.')],
    captura: Annotated[bool, Form()] = False,
    visual: Annotated[bool, Form()] = False,
) -> dict:
    # Rota síncrona: FastAPI executa I/O e OpenCV no pool de threads.
    try:
        conteudo, extensao = ler_upload(arquivo, LIMITE_UPLOAD)
        bytes_entrada = len(conteudo)
        dimensoes_entrada = _dimensoes_cabecalho(conteudo) if extensao != ".pdf" else (0, 0)
        try:
            oficial = json.loads(gabarito, object_pairs_hook=_objeto_sem_duplicatas)
            validar_gabarito(oficial)
        except (ValueError, RecursionError):
            raise HTTPException(422, "Gabarito inválido: envie um objeto JSON com exatamente 50 questões (1–50) e alternativas A–E, sem chaves duplicadas.") from None

        # Nome e caminho enviados pelo cliente nunca são usados na gravação.
        # O contexto remove o diretório mesmo quando reconhecimento/correção falham.
        with TemporaryDirectory(prefix="correcao-") as temporario:
            if captura:
                if extensao == ".pdf":
                    raise HTTPException(422, "Captura de câmera deve ser JPG ou PNG.")
                try:
                    conteudo = retificar_captura(conteudo)
                except ErroLeitura:
                    logger.warning("cartao_rejeitado etapa=retificacao tipo=%s bytes=%d entrada_px=%dx%d",
                                   extensao, bytes_entrada, *dimensoes_entrada)
                    raise HTTPException(422, "Captura ilegível.") from None
                extensao = ".png"
            dimensoes_processadas = _dimensoes_cabecalho(conteudo) if extensao != ".pdf" else (0, 0)
            if captura:
                logger.info("cartao_captura tipo_entrada=%s bytes_entrada=%d entrada_px=%dx%d processado_px=%dx%d",
                            Path(arquivo.filename or "").suffix.lower(), bytes_entrada,
                            *dimensoes_entrada, *dimensoes_processadas)
            caminho = Path(temporario) / f"cartao{extensao}"
            caminho.write_bytes(conteudo)
            try:
                reconhecidas = reconhecer_arquivo(caminho)
            except ErroLeitura as erro:
                logger.warning("cartao_rejeitado etapa=%s captura=%s entrada_px=%dx%d processado_px=%dx%d bytes=%d",
                               _etapa_rejeicao(erro), captura, *dimensoes_entrada,
                               *dimensoes_processadas, bytes_entrada)
                raise HTTPException(422, "Não foi possível ler o cartão ou identificar sua grade. Verifique o arquivo e o modelo de respostas.") from None
            resultado = corrigir_respostas(reconhecidas, oficial)
            if visual:
                return {"resultado": resultado, "respostas": reconhecidas,
                        "comprovante": assinar_respostas(reconhecidas, oficial),
                        "marcacoes": classificar_questoes(reconhecidas, oficial),
                        "visualizacao": preparar_visualizacao(carregar_imagem(caminho))}
            return resultado
    except HTTPException:
        raise
    except Exception:
        # Não devolver mensagens de bibliotecas, caminhos locais ou rastreamentos.
        raise HTTPException(500, "Falha interna ao processar o cartão. Tente novamente.") from None
