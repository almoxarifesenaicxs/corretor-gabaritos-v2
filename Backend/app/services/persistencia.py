"""Operações simples de provas, gabaritos e correções com cliente injetado."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import uuid4

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError
from google.cloud.firestore_v1.base_query import FieldFilter

from app.services.correcao import validar_gabarito


class ErroPersistencia(RuntimeError):
    """Falha de comunicação com o banco."""


class RegistroExistente(ValueError):
    """Tentativa de sobrescrever um registro existente."""


def _texto(valor, nome):
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{nome} deve ser um texto não vazio.")
    return valor.strip()


def _id(valor):
    valor = _texto(valor, "Identificador")
    if "/" in valor or valor in {".", ".."} or len(valor.encode("utf-8")) > 1500:
        raise ValueError("Identificador inválido.")
    return valor


def _validar_resultado(resultado):
    """Valida o contrato de transporte, sem recalcular ou corrigir pontuação."""
    if (not isinstance(resultado, dict)
            or resultado.keys() != {"provisorio", "resumo", "disciplinas", "questoes_pendentes"}
            or type(resultado["provisorio"]) is not bool
            or not isinstance(resultado["disciplinas"], dict)
            or resultado["disciplinas"].keys() != {"portugues", "matematica"}):
        raise ValueError("Resultado incompatível com o contrato do motor.")
    pendentes = resultado["questoes_pendentes"]
    if (not isinstance(pendentes, list)
            or any(not isinstance(q, str) or q not in {str(i) for i in range(1, 51)} for q in pendentes)
            or len(set(pendentes)) != len(pendentes)
            or bool(pendentes) != resultado["provisorio"]):
        raise ValueError("Pendências inconsistentes.")
    inteiros = {"acertos", "erros", "brancos", "multiplas", "duvidosas", "pendentes", "pontuacao", "pontuacao_maxima"}
    for resumo in [resultado["resumo"], *resultado["disciplinas"].values()]:
        if (not isinstance(resumo, dict) or resumo.keys() != inteiros | {"percentual_acertos"}
                or any(type(resumo[campo]) is not int or resumo[campo] < 0 for campo in inteiros)
                or type(resumo["percentual_acertos"]) not in {int, float}
                or not 0 <= resumo["percentual_acertos"] <= 100):
            raise ValueError("Resumo incompatível com o contrato do motor.")
    # Não admitir objetos, bytes, PDFs ou NaN no documento de resultado.
    json.dumps(resultado, allow_nan=False)


class Persistencia:
    """Recebe cliente Firestore (ou substituto em testes); nunca cria conexão."""

    def __init__(self, cliente):
        self.cliente = cliente

    def _consultar(self, colecao, identificador):
        try:
            snapshot = self.cliente.collection(colecao).document(_id(identificador)).get()
            return snapshot.to_dict() if snapshot.exists else None
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível consultar o registro.") from erro

    def _criar(self, colecao, identificador, dados):
        try:
            self.cliente.collection(colecao).document(identificador).create(dados)
            return deepcopy(dados)
        except AlreadyExists as erro:
            raise RegistroExistente("Registro já cadastrado; sobrescrita não permitida.") from erro
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível salvar o registro.") from erro

    def _listar(self, colecao, prova_id=None):
        try:
            consulta = self.cliente.collection(colecao)
            if prova_id is not None:
                consulta = consulta.where(filter=FieldFilter("prova_id", "==", _id(prova_id)))
            return [snapshot.to_dict() for snapshot in consulta.stream()]
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível listar os registros.") from erro

    def criar_prova(self, titulo, descricao=None):
        titulo = _texto(titulo, "Título")
        if descricao is not None and not isinstance(descricao, str):
            raise ValueError("Descrição deve ser texto ou None.")
        identificador = uuid4().hex
        return self._criar("provas", identificador, {
            "id": identificador, "titulo": titulo, "descricao": descricao,
            "criada_em": datetime.now(timezone.utc),
        })

    def consultar_prova(self, prova_id):
        return self._consultar("provas", prova_id)

    def listar_provas(self):
        return self._listar("provas")

    def _exigir_prova(self, prova_id):
        prova_id = _id(prova_id)
        if self.consultar_prova(prova_id) is None:
            raise ValueError("Prova inexistente.")
        return prova_id

    def cadastrar_gabarito(self, prova_id, alternativas):
        validar_gabarito(alternativas)
        prova_id = self._exigir_prova(prova_id)
        # Um documento por prova + create atômico impede sobrescrita concorrente.
        return self._criar("gabaritos", prova_id, {
            "id": prova_id, "prova_id": prova_id, "alternativas": deepcopy(alternativas),
            "criado_em": datetime.now(timezone.utc),
        })

    def consultar_gabarito(self, prova_id):
        return self._consultar("gabaritos", prova_id)

    def salvar_correcao(self, prova_id, aluno, resultado, *, permitir_provisorio=False):
        aluno = _texto(aluno, "Aluno")
        _validar_resultado(resultado)
        if type(permitir_provisorio) is not bool:
            raise ValueError("permitir_provisorio deve ser booleano.")
        if resultado["provisorio"] and not permitir_provisorio:
            raise ValueError("Resultado provisório exige permitir_provisorio=True explícito.")
        prova_id = self._exigir_prova(prova_id)
        identificador = uuid4().hex
        return self._criar("correcoes", identificador, {
            "id": identificador, "prova_id": prova_id, "aluno": aluno,
            "resultado": deepcopy(resultado),
            "situacao": "provisoria" if resultado["provisorio"] else "sem_pendencias",
            "processada_em": datetime.now(timezone.utc),
        })

    def consultar_correcao(self, correcao_id):
        return self._consultar("correcoes", correcao_id)

    def listar_correcoes(self, prova_id):
        return self._listar("correcoes", prova_id)
