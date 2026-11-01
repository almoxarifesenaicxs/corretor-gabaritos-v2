"""Operações simples de provas, gabaritos e correções com cliente injetado."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import unicodedata
from difflib import SequenceMatcher
from uuid import uuid4

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError
from google.cloud.firestore_v1.base_query import FieldFilter

from app.services.correcao import validar_gabarito


class ErroPersistencia(RuntimeError):
    """Falha de comunicação com o banco."""


class RegistroExistente(ValueError):
    """Tentativa de sobrescrever um registro existente."""


class AlunosAmbiguos(ValueError):
    def __init__(self, alunos):
        super().__init__("Mais de um aluno possui esse nome. Confirme o cadastro correto.")
        self.alunos = [{"id": a["id"], "nome": a["nome"]} for a in alunos]


def _texto(valor, nome):
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{nome} deve ser um texto não vazio.")
    return valor.strip()


def _id(valor):
    valor = _texto(valor, "Identificador")
    if "/" in valor or valor in {".", ".."} or len(valor.encode("utf-8")) > 1500:
        raise ValueError("Identificador inválido.")
    return valor


def normalizar_nome(nome):
    return unicodedata.normalize("NFC", " ".join(_texto(nome, "Nome").split())).casefold()


def chave_busca(nome):
    return "".join(c for c in unicodedata.normalize("NFKD", normalizar_nome(nome))
                   if not unicodedata.combining(c))


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

    def criar_avaliacao(self, titulo, alternativas):
        """Cria prova e gabarito juntos, após confirmação na interface."""
        titulo = _texto(titulo, "Título")
        validar_gabarito(alternativas)
        identificador = uuid4().hex
        agora = datetime.now(timezone.utc)
        prova = {"id": identificador, "titulo": titulo, "descricao": None, "criada_em": agora}
        gabarito = {"id": identificador, "prova_id": identificador,
                    "alternativas": deepcopy(alternativas), "criado_em": agora}
        try:
            lote = self.cliente.batch()
            lote.create(self.cliente.collection("provas").document(identificador), prova)
            lote.create(self.cliente.collection("gabaritos").document(identificador), gabarito)
            lote.commit()
            return prova
        except AlreadyExists as erro:
            raise RegistroExistente("Avaliação já cadastrada.") from erro
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível cadastrar a avaliação.") from erro

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

    def salvar_correcao(self, prova_id, aluno, resultado, *, permitir_provisorio=False, aluno_id=None,
                        vincular_aluno=False, novo_homonimo=False):
        aluno = _texto(aluno, "Aluno")
        _validar_resultado(resultado)
        if type(permitir_provisorio) is not bool:
            raise ValueError("permitir_provisorio deve ser booleano.")
        if resultado["provisorio"] and not permitir_provisorio:
            raise ValueError("Resultado provisório exige permitir_provisorio=True explícito.")
        prova_id = self._exigir_prova(prova_id)
        if vincular_aluno:
            return self._salvar_com_aluno(prova_id, aluno, resultado, aluno_id, novo_homonimo)
        vinculo = {}
        if aluno_id is not None:
            aluno_id = _id(aluno_id)
            cadastrado = self.consultar_aluno(aluno_id)
            if cadastrado is None:
                raise ValueError("Aluno inexistente.")
            if normalizar_nome(aluno) != normalizar_nome(cadastrado["nome"]):
                raise ValueError("Nome não corresponde ao aluno selecionado.")
            aluno = cadastrado["nome"]
            vinculo["aluno_id"] = aluno_id
        identificador = uuid4().hex
        return self._criar("correcoes", identificador, {
            "id": identificador, "prova_id": prova_id, "aluno": aluno,
            "resultado": deepcopy(resultado),
            "situacao": "provisoria" if resultado["provisorio"] else "sem_pendencias",
            "processada_em": datetime.now(timezone.utc),
            **vinculo,
        })

    def consultar_correcao(self, correcao_id):
        return self._consultar("correcoes", correcao_id)

    def listar_correcoes(self, prova_id):
        return self._listar("correcoes", prova_id)

    def cadastrar_aluno(self, nome):
        dados = self._dados_aluno(nome)
        return self._criar("alunos", dados["id"], dados)

    def _dados_aluno(self, nome, *, novo_homonimo=False):
        nome = unicodedata.normalize("NFC", " ".join(_texto(nome, "Nome").split()))
        if len(nome) > 200 or not any(c.isalpha() for c in nome):
            raise ValueError("Nome inválido: use até 200 caracteres e inclua letras.")
        normalizado = normalizar_nome(nome)
        # create é atômico: duas requisições do mesmo nome não criam duplicatas.
        identificador = uuid4().hex if novo_homonimo else hashlib.sha256(normalizado.encode("utf-8")).hexdigest()
        return {
            "id": identificador, "nome": nome, "nome_normalizado": normalizado,
            "criado_em": datetime.now(timezone.utc),
        }

    def _salvar_com_aluno(self, prova_id, nome, resultado, aluno_id, novo_homonimo):
        if type(novo_homonimo) is not bool or novo_homonimo and aluno_id is not None:
            raise ValueError("Selecione um aluno ou confirme outra pessoa com o mesmo nome.")
        dados = self._dados_aluno(nome, novo_homonimo=novo_homonimo)
        correcao_id = uuid4().hex
        for tentativa in range(2):
            criar = False
            if aluno_id is not None:
                aluno = self.consultar_aluno(_id(aluno_id))
                if aluno is None or normalizar_nome(aluno["nome"]) != dados["nome_normalizado"]:
                    raise ValueError("Aluno selecionado não corresponde ao nome confirmado.")
            elif novo_homonimo:
                aluno, criar = dados, True
            else:
                exatos = self.correspondencias_aluno(nome)["exatos"]
                if len(exatos) > 1:
                    raise AlunosAmbiguos(exatos)
                aluno, criar = (exatos[0], False) if exatos else (dados, True)
            correcao = {"id": correcao_id, "prova_id": prova_id, "aluno": aluno["nome"],
                        "aluno_id": aluno["id"], "resultado": deepcopy(resultado),
                        "situacao": "provisoria" if resultado["provisorio"] else "sem_pendencias",
                        "processada_em": datetime.now(timezone.utc)}
            try:
                lote = self.cliente.batch()
                if criar:
                    lote.create(self.cliente.collection("alunos").document(aluno["id"]), aluno)
                lote.create(self.cliente.collection("correcoes").document(correcao_id), correcao)
                lote.commit()
                return correcao
            except AlreadyExists as erro:
                # Outro salvamento criou o ID determinístico. Reconsulta e reutiliza;
                # o lote que falhou não deixou aluno ou correção parcialmente gravados.
                if tentativa or not criar or novo_homonimo:
                    raise RegistroExistente("Conflito ao salvar. Confira o histórico antes de repetir.") from erro
            except GoogleAPICallError as erro:
                raise ErroPersistencia("Não foi possível salvar aluno e correção.") from erro

    def consultar_aluno(self, aluno_id):
        return self._consultar("alunos", aluno_id)

    def listar_alunos(self, busca=""):
        alunos = self._listar("alunos")
        if busca.strip():
            termo = chave_busca(busca)
            alunos = [a for a in alunos if termo in chave_busca(a["nome"])]
        return sorted(alunos, key=lambda a: (chave_busca(a["nome"]), a["id"]))

    def correspondencias_aluno(self, nome):
        nome_normalizado, busca = normalizar_nome(nome), chave_busca(nome)
        exatos, semelhantes = [], []
        for aluno in self.listar_alunos():
            if normalizar_nome(aluno["nome"]) == nome_normalizado:
                exatos.append(aluno)
            elif SequenceMatcher(None, busca, chave_busca(aluno["nome"])).ratio() >= .82:
                semelhantes.append(aluno)
        return {"exato": exatos[0] if len(exatos) == 1 else None, "exatos": exatos, "semelhantes": semelhantes}

    def historico_aluno(self, aluno_id):
        aluno_id = _id(aluno_id)
        aluno = self.consultar_aluno(aluno_id)
        if aluno is None:
            return None
        provas = {p["id"]: p["titulo"] for p in self.listar_provas()}
        vinculadas, legadas = [], []
        for original in self._listar("correcoes"):
            por_id = original.get("aluno_id") == aluno_id
            por_nome = (not original.get("aluno_id")
                        and normalizar_nome(original["aluno"]) == normalizar_nome(aluno["nome"]))
            if por_id or por_nome:
                registro = deepcopy(original)
                registro["avaliacao"] = provas.get(registro["prova_id"], registro["prova_id"])
                (vinculadas if por_id else legadas).append(registro)
        for registros in (vinculadas, legadas):
            registros.sort(key=lambda c: str(c["processada_em"]), reverse=True)
        return {"aluno": aluno, "correcoes": vinculadas, "legadas_por_nome": legadas}
