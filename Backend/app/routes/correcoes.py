"""Integração HTTP dos serviços de reconhecimento e correção."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.correcao import corrigir_respostas, validar_gabarito
from app.services.reconhecimento import ErroLeitura, reconhecer_arquivo
from app.services.captura import retificar_captura

router = APIRouter(prefix="/api/correcoes", tags=["Correções"])
LIMITE_UPLOAD = 10 * 1024 * 1024
ASSINATURAS = {".pdf": b"%PDF-", ".png": b"\x89PNG\r\n\x1a\n",
               ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}


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
) -> dict:
    # Rota síncrona: FastAPI executa I/O e OpenCV no pool de threads.
    try:
        conteudo, extensao = ler_upload(arquivo, LIMITE_UPLOAD)
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
                    raise HTTPException(422, "Captura ilegível.") from None
                extensao = ".png"
            caminho = Path(temporario) / f"cartao{extensao}"
            caminho.write_bytes(conteudo)
            try:
                reconhecidas = reconhecer_arquivo(caminho)
            except ErroLeitura:
                raise HTTPException(422, "Não foi possível ler o cartão ou identificar sua grade. Verifique o arquivo e o modelo de respostas.") from None
            return corrigir_respostas(reconhecidas, oficial)
    except HTTPException:
        raise
    except Exception:
        # Não devolver mensagens de bibliotecas, caminhos locais ou rastreamentos.
        raise HTTPException(500, "Falha interna ao processar o cartão. Tente novamente.") from None
