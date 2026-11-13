"""API pública demonstrativa: somente dados fixos e processamento sem persistência."""

from fastapi import APIRouter, HTTPException

from app.routes.correcoes import processar
from app.routes.interface import recalcular_correcao, reconhecer_nome


router = APIRouter(prefix="/api", tags=["Demonstração"])
PROVA_ID = "demonstracao-50"
GABARITO = {str(numero): "ABCDE"[(numero - 1) % 5] for numero in range(1, 51)}
PROVA = {"id": PROVA_ID, "titulo": "Avaliação fictícia — Português e Matemática",
         "descricao": "Demonstração sem armazenamento", "criada_em": "2026-11-01T00:00:00Z"}


@router.get("/demo/info")
def informacoes_demo():
    return {"modo": "publico_demo", "persistencia": False,
            "aviso": "Use somente gabaritos fictícios. Nenhum resultado é salvo.",
            "zip": False, "exportacao": False}


@router.get("/avaliacoes")
def avaliacoes_demo():
    return [PROVA]


@router.get("/avaliacoes/{prova_id}/gabarito")
def gabarito_demo(prova_id: str):
    if prova_id != PROVA_ID:
        raise HTTPException(404, "Avaliação demonstrativa inexistente.")
    return {"id": PROVA_ID, "prova_id": PROVA_ID, "alternativas": GABARITO}


@router.get("/alunos")
def alunos_demo(pagina: bool = False):
    # Não há documentos reais ou cadastro de visitantes neste modo.
    return {"alunos": [], "proximo_cursor": None} if pagina else []


@router.get("/alunos/correspondencias")
def correspondencias_demo(nome: str = ""):
    return {"exato": None, "exatos": [], "semelhantes": []}


router.add_api_route("/correcoes/processar", processar, methods=["POST"])
router.add_api_route("/correcoes/recalcular", recalcular_correcao, methods=["POST"])
router.add_api_route("/alunos/reconhecer-nome", reconhecer_nome, methods=["POST"])
