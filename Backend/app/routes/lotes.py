"""Importação temporária de imagens ZIP, restrita ao modo operacional local."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, Request
from fastapi.responses import Response
from hashlib import sha256

from app.routes.interface import exigir_acesso_local, exigir_modo_operacional
from app.services.lotes_zip import lotes_zip


def exigir_acesso_lote(request: Request):
    if request.app.state.ambiente == "local_operacional":
        exigir_acesso_local(request)


router = APIRouter(prefix="/api/lotes", tags=["Lotes"],
                   dependencies=[Depends(exigir_modo_operacional), Depends(exigir_acesso_lote)])


@router.post("/zip")
def importar_zip(arquivo: Annotated[UploadFile, File()]):
    return lotes_zip.criar(arquivo)


@router.get("/{lote_id}")
def consultar_lote(lote_id: str):
    return lotes_zip.manifesto(lote_id)


@router.get("/{lote_id}/imagens/{indice}")
def obter_imagem(lote_id: str, indice: int):
    conteudo, nome, tipo = lotes_zip.imagem(lote_id, indice)
    return Response(conteudo, media_type=tipo, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "X-Image-SHA256": sha256(conteudo).hexdigest(),
        "Content-Disposition": f'inline; filename="imagem{indice}{".png" if tipo == "image/png" else ".jpg"}"',
    })


@router.delete("/{lote_id}", status_code=204)
def cancelar_lote(lote_id: str):
    lotes_zip.cancelar(lote_id)
