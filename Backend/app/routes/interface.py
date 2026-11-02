"""Rotas dos fluxos da interface web, com persistência explícita."""

from pathlib import Path
from ipaddress import ip_address
from tempfile import TemporaryDirectory
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.database.firestore import conectar_firestore, usar_emulador_configurado
from app.routes.correcoes import ler_upload, LIMITE_UPLOAD
from app.services.captura import analisar_folha, decodificar_captura, retificar_captura
from app.services.persistencia import Persistencia, ErroPersistencia, RegistroExistente
from app.services.persistencia import AlunosAmbiguos
from app.services.reconhecimento import ErroLeitura, reconhecer_arquivo
from app.services.reconhecimento import carregar_imagem
from app.services.nome_aluno import ler_nome
from app.services.correcao import corrigir_respostas
from app.services.correcao_visual import classificar_questoes

router = APIRouter(prefix="/api", tags=["Interface"])


def exigir_acesso_local(request: Request):
    """Restringe o uso administrativo real à própria máquina, sem proxy."""
    try:
        local = request.client is not None and ip_address(request.client.host).is_loopback
        host_local = request.url.hostname in {"localhost", "127.0.0.1", "::1"}
        encaminhada = any(nome in request.headers for nome in (
            "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"))
        origem = request.headers.get("origin")
        mesma_origem = not origem or (
            urlsplit(origem).scheme == request.url.scheme
            and urlsplit(origem).netloc == request.url.netloc
            and urlsplit(origem).path == ""
            and not urlsplit(origem).query and not urlsplit(origem).fragment)
    except ValueError:
        local = host_local = mesma_origem = False
        encaminhada = True
    if not local or not host_local or encaminhada or not mesma_origem:
        raise HTTPException(403, "Firestore real disponível somente para acesso local direto à API.")


def obter_persistencia(request: Request):
    try:
        emulador = usar_emulador_configurado()
    except ValueError:
        raise HTTPException(503, "Persistência indisponível. Confira FIRESTORE_MODO e a configuração do Firestore no backend.") from None
    if not emulador:
        exigir_acesso_local(request)
    iniciado = False
    try:
        with conectar_firestore(emulador=emulador) as cliente:
            iniciado = True
            yield Persistencia(cliente)
    except HTTPException:
        raise
    except RegistroExistente:
        raise HTTPException(409, "Registro já existente; sobrescrita não permitida.") from None
    except ErroPersistencia:
        raise HTTPException(503, "Banco de dados indisponível. Tente novamente.") from None
    except ValueError:
        raise HTTPException(422 if iniciado else 503, "Dados inválidos para persistência." if iniciado else "Não foi possível conectar ao banco.") from None
    except Exception:
        raise HTTPException(500 if iniciado else 503, "Não foi possível concluir a operação de persistência.") from None


Repo = Annotated[Persistencia, Depends(obter_persistencia)]


class AvaliacaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: str = Field(min_length=1, max_length=160)
    alternativas: dict
    confirmado: StrictBool


class CorrecaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prova_id: str = Field(min_length=1, max_length=1500)
    aluno: str = Field(min_length=1, max_length=200)
    resultado: dict
    confirmado: StrictBool
    permitir_provisorio: StrictBool = False
    aluno_id: str | None = Field(default=None, min_length=1, max_length=1500)
    novo_homonimo: StrictBool = False


class RevisaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    respostas: dict
    gabarito: dict


@router.get("/alunos")
def listar_alunos(repo: Repo, busca: str = ""):
    return repo.listar_alunos(busca)


@router.get("/alunos/correspondencias")
def correspondencias_aluno(repo: Repo, nome: str):
    return repo.correspondencias_aluno(nome)


@router.get("/alunos/{aluno_id}/correcoes")
def historico_aluno(aluno_id: str, repo: Repo):
    historico = repo.historico_aluno(aluno_id)
    if historico is None:
        raise HTTPException(404, "Aluno não encontrado.")
    return historico


@router.post("/correcoes/recalcular")
def recalcular_correcao(entrada: RevisaoEntrada):
    try:
        return {"resultado": corrigir_respostas(entrada.respostas, entrada.gabarito),
                "marcacoes": classificar_questoes(entrada.respostas, entrada.gabarito)}
    except ValueError:
        raise HTTPException(422, "Respostas ou gabarito inválidos para revisão.") from None


@router.get("/avaliacoes")
def listar_avaliacoes(repo: Repo):
    return repo.listar_provas()


@router.post("/avaliacoes", status_code=201)
def criar_avaliacao(entrada: AvaliacaoEntrada, repo: Repo):
    if not entrada.confirmado:
        raise HTTPException(422, "Confirme as 50 alternativas antes de cadastrar a avaliação.")
    return repo.criar_avaliacao(entrada.titulo, entrada.alternativas)


@router.get("/avaliacoes/{prova_id}/gabarito")
def consultar_gabarito(prova_id: str, repo: Repo):
    registro = repo.consultar_gabarito(prova_id)
    if registro is None:
        raise HTTPException(404, "Gabarito da avaliação não encontrado.")
    return registro


@router.post("/correcoes/salvar", status_code=201)
def salvar_correcao(entrada: CorrecaoEntrada, repo: Repo):
    if not entrada.confirmado:
        raise HTTPException(422, "Confira e confirme o resultado antes de salvar.")
    vinculo = {"aluno_id": entrada.aluno_id} if entrada.aluno_id is not None else {}
    try:
        return repo.salvar_correcao(entrada.prova_id, entrada.aluno, entrada.resultado,
                                   permitir_provisorio=entrada.permitir_provisorio,
                                   vincular_aluno=True, novo_homonimo=entrada.novo_homonimo, **vinculo)
    except AlunosAmbiguos as erro:
        raise HTTPException(409, {"codigo": "aluno_ambiguo", "mensagem": str(erro), "alunos": erro.alunos}) from None


@router.post("/gabaritos/reconhecer")
def reconhecer_gabarito(arquivo: Annotated[UploadFile, File()], captura: Annotated[bool, Form()] = False):
    try:
        conteudo, extensao = ler_upload(arquivo, LIMITE_UPLOAD)
        if captura:
            if extensao == ".pdf":
                raise HTTPException(422, "Captura de câmera deve ser JPG ou PNG.")
            conteudo, extensao = retificar_captura(conteudo), ".png"
        with TemporaryDirectory(prefix="gabarito-") as temporario:
            caminho = Path(temporario) / f"cartao{extensao}"
            caminho.write_bytes(conteudo)
            # Somente candidato: esta rota nunca cadastra gabarito oficial.
            return reconhecer_arquivo(caminho)
    except HTTPException:
        raise
    except ErroLeitura:
        raise HTTPException(422, "Não foi possível ler a grade. Confira o arquivo e o enquadramento.") from None
    except Exception:
        raise HTTPException(500, "Falha ao reconhecer o cartão.") from None


@router.post("/capturas/analisar")
def analisar_captura(arquivo: Annotated[UploadFile, File()]):
    try:
        conteudo, extensao = ler_upload(arquivo, LIMITE_UPLOAD)
        if extensao == ".pdf":
            raise HTTPException(415, "A análise de enquadramento aceita somente JPG ou PNG.")
        return analisar_folha(decodificar_captura(conteudo))
    except HTTPException:
        raise
    except ErroLeitura:
        raise HTTPException(422, "Frame da câmera ilegível.") from None
    except Exception:
        raise HTTPException(500, "Falha ao analisar enquadramento.") from None


@router.post("/alunos/reconhecer-nome")
def reconhecer_nome(arquivo: Annotated[UploadFile, File()], captura: Annotated[bool, Form()] = False):
    """Mesma captura do cartão; OCR local sem persistir imagem ou nome."""
    try:
        conteudo, extensao = ler_upload(arquivo, LIMITE_UPLOAD)
        if captura:
            if extensao == ".pdf":
                raise HTTPException(422, "Captura de câmera deve ser JPG ou PNG.")
            conteudo, extensao = retificar_captura(conteudo), ".png"
        with TemporaryDirectory(prefix="nome-aluno-") as temporario:
            caminho = Path(temporario) / f"cartao{extensao}"
            caminho.write_bytes(conteudo)
            return ler_nome(carregar_imagem(caminho))
    except HTTPException:
        raise
    except ErroLeitura:
        raise HTTPException(422, "Imagem do cartão ilegível. Preencha o nome manualmente.") from None
    except Exception:
        raise HTTPException(500, "Não foi possível ler o nome. Preencha manualmente.") from None
