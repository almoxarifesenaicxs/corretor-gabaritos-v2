"""Arquivo ZIP temporário para correção sequencial no computador operacional."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from threading import RLock
from time import monotonic
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED, ZIP_STORED
import math
import os

import cv2
import pymupdf
from fastapi import HTTPException
from app.services.limites_imagem import validar_dimensoes
from app.services.reconhecimento import ErroLeitura, converter_pagina_pdf


def _limite(nome: str, padrao: int, minimo: int, maximo: int) -> int:
    try:
        valor = int(os.environ.get(nome, str(padrao)))
    except ValueError:
        raise ValueError(f"{nome} deve ser um número inteiro.") from None
    if not minimo <= valor <= maximo:
        raise ValueError(f"{nome} fora do intervalo permitido.")
    return valor


def limites() -> dict:
    return {
        "zip": _limite("LOTE_ZIP_MAX_MIB", 32, 1, 32) * 1024 * 1024,
        "imagens": _limite("LOTE_MAX_IMAGENS", 100, 1, 100),
        "total": _limite("LOTE_TOTAL_MAX_MIB", 250, 10, 250) * 1024 * 1024,
        "imagem": 10 * 1024 * 1024,
        "paginas_pdf": _limite("LOTE_PDF_MAX_PAGINAS", 30, 1, 100),
    }


@contextmanager
def _pdf_extraido(zip_arquivo, info, pasta, limite):
    """Extrai somente o PDF solicitado em blocos para arquivo privado temporário."""
    with TemporaryDirectory(prefix="pagina-pdf-", dir=pasta) as temporario:
        caminho = Path(temporario) / "documento.pdf"
        total = 0
        with zip_arquivo.open(info) as origem, caminho.open("wb") as destino:
            while bloco := origem.read(1024 * 1024):
                total += len(bloco)
                if total > limite:
                    raise HTTPException(413, "PDF do ZIP excede 10 MiB.")
                destino.write(bloco)
        yield caminho


@dataclass
class Lote:
    pasta: TemporaryDirectory
    criado: float
    imagens: list[dict]
    owner: str | None = None

    @property
    def caminho(self) -> Path:
        return Path(self.pasta.name) / "imagens.zip"


class LotesZIP:
    def __init__(self):
        self._lotes: dict[str, Lote] = {}
        self._lock = RLock()

    def _limpar_expirados(self):
        for identificador, lote in list(self._lotes.items()):
            if monotonic() - lote.criado > 2 * 60 * 60:
                lote.pasta.cleanup()
                del self._lotes[identificador]

    def criar(self, arquivo, owner: str | None = None) -> dict:
        regras = limites()
        if owner is not None:
            regras = {**regras, "zip": min(regras["zip"], 8 * 1024 * 1024),
                      "imagens": min(regras["imagens"], 20),
                      "total": min(regras["total"], 50 * 1024 * 1024),
                      "paginas_pdf": min(regras["paginas_pdf"], 10)}
        if Path(arquivo.filename or "").suffix.lower() != ".zip":
            raise HTTPException(415, "Selecione um arquivo ZIP.")
        with self._lock:
            self._limpar_expirados()
            if len(self._lotes) >= 2:
                raise HTTPException(429, "Há dois lotes ativos. Conclua ou cancele um deles.")
            pasta = TemporaryDirectory(prefix="corretor-lote-")
            caminho = Path(pasta.name) / "imagens.zip"
            try:
                tamanho = 0
                with caminho.open("wb") as destino:
                    while bloco := arquivo.file.read(1024 * 1024):
                        tamanho += len(bloco)
                        if tamanho > regras["zip"]:
                            raise HTTPException(413, "ZIP excede o limite configurado.")
                        destino.write(bloco)
                if not tamanho:
                    raise HTTPException(400, "ZIP vazio.")
                imagens = self._manifesto(caminho, regras)
                identificador = uuid4().hex
                self._lotes[identificador] = Lote(pasta, monotonic(), imagens, owner)
                return {"lote_id": identificador, "total": len(imagens), "imagens": imagens}
            except Exception:
                pasta.cleanup()
                raise

    @staticmethod
    def _manifesto(caminho: Path, regras: dict) -> list[dict]:
        # zipfile indexa o diretório central inteiro: limite antes de instanciá-lo.
        with caminho.open("rb") as arquivo:
            arquivo.seek(0, 2)
            tamanho = arquivo.tell()
            arquivo.seek(max(0, tamanho - 65557))
            cauda = arquivo.read()
        fim = cauda.rfind(b"PK\x05\x06")
        if fim < 0 or fim + 22 > len(cauda):
            raise HTTPException(400, "Diretório ZIP inválido.")
        entradas = int.from_bytes(cauda[fim + 10:fim + 12], "little")
        diretorio = int.from_bytes(cauda[fim + 12:fim + 16], "little")
        comentario = int.from_bytes(cauda[fim + 20:fim + 22], "little")
        if fim + 22 + comentario != len(cauda):
            raise HTTPException(400, "Diretório ZIP inválido.")
        if entradas > regras["imagens"] + 50 or diretorio > 256 * 1024 or entradas == 0xffff:
            raise HTTPException(413, "Diretório ZIP excede o limite de entradas.")
        try:
            with ZipFile(caminho) as zip_arquivo:
                infos = zip_arquivo.infolist()
                if len(infos) > regras["imagens"] + 50:
                    raise HTTPException(413, "ZIP contém entradas demais.")
                imagens, vistos, total, arquivos = [], set(), 0, 0
                for info in infos:
                    nome = info.filename
                    partes = PurePosixPath(nome).parts
                    if (not nome or len(nome) > 240 or "\\" in nome or nome.startswith("/") or ":" in nome
                            or ".." in partes or not partes or any(p == "" for p in partes)
                            or (info.external_attr >> 16) & 0o170000 == 0o120000):
                        raise HTTPException(400, "ZIP contém caminho inseguro.")
                    if info.flag_bits & 1:
                        raise HTTPException(400, "ZIP criptografado não é permitido.")
                    if info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                        raise HTTPException(415, "Método de compressão não suportado.")
                    if info.is_dir():
                        continue
                    chave = nome.casefold()
                    if chave in vistos:
                        raise HTTPException(400, "ZIP contém nomes duplicados.")
                    vistos.add(chave)
                    arquivos += 1
                    if arquivos > regras["imagens"]:
                        raise HTTPException(413, "ZIP contém arquivos demais. Divida em lotes menores.")
                    total += info.file_size
                    if (info.file_size > regras["imagem"] or total > regras["total"]
                            or info.file_size > max(info.compress_size, 1) * 100):
                        raise HTTPException(413, "ZIP excede limites de tamanho ou compressão.")
                    extensao = Path(nome).suffix.lower()
                    erro = None
                    if extensao not in {".jpg", ".jpeg", ".png", ".pdf"}:
                        erro = "Formato não suportado. Use PDF, JPG ou PNG."
                    else:
                        with zip_arquivo.open(info) as entrada:
                            assinatura = entrada.read(8)
                        esperado = (b"%PDF-" if extensao == ".pdf" else
                                    b"\x89PNG\r\n\x1a\n" if extensao == ".png" else b"\xff\xd8\xff")
                        if not assinatura.startswith(esperado):
                            erro = "Extensão não corresponde ao conteúdo."
                    if extensao == ".pdf" and erro is None:
                        try:
                            with _pdf_extraido(zip_arquivo, info, caminho.parent, regras["imagem"]) as pdf:
                                with pymupdf.open(stream=pdf.read_bytes(), filetype="pdf") as documento:
                                    if documento.needs_pass or not documento.page_count:
                                        erro = "PDF protegido, corrompido ou sem páginas."
                                    elif documento.page_count > regras["paginas_pdf"]:
                                        raise HTTPException(413, "PDF excede o limite de páginas por arquivo.")
                                    elif len(imagens) + documento.page_count > regras["imagens"]:
                                        raise HTTPException(413, "ZIP excede o limite de gabaritos/páginas. Divida em lotes menores.")
                                    else:
                                        for pagina in range(documento.page_count):
                                            try:
                                                retangulo = documento[pagina].rect
                                                validar_dimensoes(math.ceil(retangulo.width * 150 / 72),
                                                                  math.ceil(retangulo.height * 150 / 72))
                                                erro_pagina = None
                                            except Exception:
                                                erro_pagina = "Página PDF excede o limite de pixels ou está ilegível."
                                            imagens.append({"indice": len(imagens), "nome": nome,
                                                            "pagina": pagina + 1,
                                                            "estado": "falha" if erro_pagina else "pendente",
                                                            "erro": erro_pagina})
                        except HTTPException:
                            raise
                        except Exception:
                            erro = "PDF protegido, corrompido ou ilegível."
                        if erro is None:
                            continue
                    if len(imagens) >= regras["imagens"]:
                        raise HTTPException(413, "ZIP excede o limite de gabaritos/páginas. Divida em lotes menores.")
                    imagens.append({"indice": len(imagens), "nome": nome,
                                    "estado": "falha" if erro else "pendente", "erro": erro})
                if not imagens:
                    raise HTTPException(400, "ZIP não contém PDF, JPG ou PNG.")
                return imagens
        except BadZipFile:
            raise HTTPException(400, "Arquivo ZIP inválido.") from None

    def manifesto(self, identificador: str, owner: str | None = None) -> dict:
        with self._lock:
            self._limpar_expirados()
            lote = self._lotes.get(identificador)
            if lote is None or lote.owner != owner:
                raise HTTPException(404, "Lote inexistente ou expirado.")
            return {"lote_id": identificador, "total": len(lote.imagens), "imagens": lote.imagens}

    def imagem(self, identificador: str, indice: int, owner: str | None = None) -> tuple[bytes, str, str]:
        with self._lock:
            manifesto = self.manifesto(identificador, owner)
            if not 0 <= indice < manifesto["total"]:
                raise HTTPException(404, "Imagem não encontrada.")
            item = manifesto["imagens"][indice]
            if item["estado"] == "falha":
                raise HTTPException(415, item["erro"])
            lote = self._lotes[identificador]
            extensao = Path(item["nome"]).suffix.lower()
            if extensao == ".pdf":
                try:
                    with ZipFile(lote.caminho) as zip_arquivo:
                        info = zip_arquivo.getinfo(item["nome"])
                        with _pdf_extraido(zip_arquivo, info, lote.pasta.name, limites()["imagem"]) as pdf:
                            imagem = converter_pagina_pdf(pdf, item["pagina"] - 1)
                            sucesso, convertido = cv2.imencode(".jpg", imagem,
                                [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if not sucesso:
                        raise ErroLeitura("Página PDF ilegível.")
                    conteudo = convertido.tobytes()
                except HTTPException:
                    raise
                except (BadZipFile, OSError, RuntimeError, KeyError, ErroLeitura):
                    raise HTTPException(422, "Página PDF ilegível ou corrompida.") from None
                if len(conteudo) > limites()["imagem"]:
                    raise HTTPException(413, "Página PDF convertida excede 10 MiB.")
                return conteudo, f"pagina-{item['pagina']}.jpg", "image/jpeg"
            try:
                with ZipFile(lote.caminho) as zip_arquivo, zip_arquivo.open(item["nome"]) as entrada:
                    conteudo = entrada.read(limites()["imagem"] + 1)
            except (BadZipFile, OSError, RuntimeError):
                raise HTTPException(422, "Imagem do ZIP ilegível.") from None
            if len(conteudo) > limites()["imagem"]:
                raise HTTPException(413, "Imagem excede 10 MiB.")
            assinatura = b"\x89PNG\r\n\x1a\n" if extensao == ".png" else b"\xff\xd8\xff"
            if not conteudo.startswith(assinatura):
                raise HTTPException(415, "Conteúdo da imagem não corresponde à extensão.")
            return conteudo, Path(item["nome"]).name, "image/png" if extensao == ".png" else "image/jpeg"

    def cancelar(self, identificador: str, owner: str | None = None):
        with self._lock:
            lote = self._lotes.get(identificador)
            if lote is None or lote.owner != owner:
                raise HTTPException(404, "Lote inexistente ou expirado.")
            del self._lotes[identificador]
            lote.pasta.cleanup()


lotes_zip = LotesZIP()
