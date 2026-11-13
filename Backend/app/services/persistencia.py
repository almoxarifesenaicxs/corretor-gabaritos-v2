"""Operações simples de provas, gabaritos e correções com cliente injetado."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import unicodedata
from difflib import SequenceMatcher
from uuid import uuid4
from threading import Lock

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError, Aborted
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1 import transactional

from app.services.correcao import validar_gabarito, corrigir_respostas
from app.services.integridade import conferir_respostas, resumo_canonico


class ErroPersistencia(RuntimeError):
    """Falha de comunicação com o banco."""


class RegistroExistente(ValueError):
    """Tentativa de sobrescrever um registro existente."""


class AlunosAmbiguos(ValueError):
    def __init__(self, alunos):
        super().__init__("Mais de um aluno possui esse nome. Confirme o cadastro correto.")
        self.alunos = [{"id": a["id"], "nome": a["nome"]} for a in alunos]


_LEGADOS = {}
_LEGADOS_LOCK = Lock()


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
    for resumo, maximo in [(resultado["resumo"], 50),
                            *[(r, 25) for r in resultado["disciplinas"].values()]]:
        if (resumo["pontuacao_maxima"] != maximo or resumo["pontuacao"] != resumo["acertos"]
                or sum(resumo[c] for c in ("acertos", "erros", "brancos", "multiplas", "duvidosas")) != maximo
                or resumo["pendentes"] != resumo["multiplas"] + resumo["duvidosas"]
                or resumo["percentual_acertos"] != round(resumo["acertos"] / maximo * 100, 2)):
            raise ValueError("Pontuação ou contagens inconsistentes.")
    if resultado["resumo"]["pendentes"] != len(pendentes):
        raise ValueError("Pendências inconsistentes.")
    for campo in inteiros - {"pontuacao_maxima"}:
        if resultado["resumo"][campo] != sum(r[campo] for r in resultado["disciplinas"].values()):
            raise ValueError("Disciplinas inconsistentes com o total.")


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

    def _alunos_exatos(self, nome_normalizado, tx=None):
        """Consulta indexada; o filtro também participa da transação de salvamento."""
        try:
            consulta = self.cliente.collection("alunos").where(
                filter=FieldFilter("nome_normalizado", "==", nome_normalizado))
            atuais = [s.to_dict() for s in consulta.stream(transaction=tx)]
            legados = []
            ids_atuais = {a["id"] for a in atuais}
            for registro in self._indice_legado().get(nome_normalizado, ()):
                identificador = registro["id"]
                if identificador in ids_atuais:
                    continue
                antigo = self._ler_transacao(self.cliente.collection("alunos").document(identificador), tx) if tx else self.consultar_aluno(identificador)
                if antigo is not None and normalizar_nome(antigo["nome"]) == nome_normalizado:
                    legados.append(antigo)
            return atuais + legados
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível consultar os alunos.") from erro

    def _indice_legado(self):
        """Uma varredura por processo/projeto, sem escrever ou migrar dados antigos."""
        if getattr(self.cliente, "legacy_scan", True) is False:
            return {}
        projeto = self.cliente.project
        chave = projeto if isinstance(projeto, str) else id(self.cliente)
        with _LEGADOS_LOCK:
            if chave not in _LEGADOS:
                encontrados = {}
                try:
                    for snapshot in self.cliente.collection("alunos").stream():
                        aluno = snapshot.to_dict()
                        if "nome_normalizado" not in aluno:
                            encontrados.setdefault(normalizar_nome(aluno["nome"]), []).append(aluno)
                except GoogleAPICallError as erro:
                    raise ErroPersistencia("Não foi possível indexar alunos antigos.") from erro
                _LEGADOS[chave] = encontrados
            return _LEGADOS[chave]

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

    def criar_avaliacao(self, titulo, alternativas, *, operacao_id=None):
        """Cria prova e gabarito juntos, após confirmação na interface."""
        titulo = _texto(titulo, "Título")
        validar_gabarito(alternativas)
        identificador = uuid4().hex
        agora = datetime.now(timezone.utc)
        prova = {"id": identificador, "titulo": titulo, "descricao": None, "criada_em": agora}
        gabarito = {"id": identificador, "prova_id": identificador,
                    "alternativas": deepcopy(alternativas), "criado_em": agora}
        if operacao_id is not None:
            chave = self._operacao("avaliacao", operacao_id)
            assinatura = resumo_canonico([titulo, alternativas])
            def cadastrar(tx):
                anterior = self._ler_transacao(chave, tx)
                if anterior:
                    return self._repeticao(anterior, assinatura)
                tx.create(self.cliente.collection("provas").document(identificador), prova)
                tx.create(self.cliente.collection("gabaritos").document(identificador), gabarito)
                tx.create(chave, {"assinatura": assinatura, "registro": prova})
                return prova
            return self._transacao(cadastrar)
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
                        vincular_aluno=False, novo_homonimo=False, respostas=None,
                        comprovante=None, operacao_id=None, origem_lote=None):
        aluno = _texto(aluno, "Aluno")
        _validar_resultado(resultado)
        if type(permitir_provisorio) is not bool:
            raise ValueError("permitir_provisorio deve ser booleano.")
        if resultado["provisorio"] and not permitir_provisorio:
            raise ValueError("Resultado provisório exige permitir_provisorio=True explícito.")
        if respostas is not None:
            return self._salvar_verificada(prova_id, aluno, resultado, respostas, comprovante,
                                           operacao_id, aluno_id, novo_homonimo, permitir_provisorio,
                                           origem_lote)
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

    def _operacao(self, tipo, operacao_id):
        # UUID obrigatório no HTTP; valida também chamadas diretas do serviço.
        from uuid import UUID
        try:
            chave = UUID(operacao_id).hex
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Identificador de operação inválido.") from None
        return self.cliente.collection("operacoes").document(tipo + "-" + chave)

    def consultar_operacao_correcao(self, operacao_id):
        """Consulta a confirmação durável, sem inferir falha por ausência momentânea."""
        try:
            snapshot = self._operacao("correcao", operacao_id).get()
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível consultar a operação.") from erro
        if not snapshot.exists:
            return {"estado": "nao_encontrada"}
        registro = snapshot.to_dict()["registro"]
        return {"estado": "confirmada", "registro": {"id": registro["id"]}}

    @staticmethod
    def _ler_transacao(ref, tx):
        snapshot = ref.get(transaction=tx)
        return snapshot.to_dict() if snapshot.exists else None

    @staticmethod
    def _repeticao(anterior, assinatura):
        if anterior["assinatura"] != assinatura:
            raise RegistroExistente("Operação já usada com outros dados. Não foi gravado novo registro.")
        return deepcopy(anterior["registro"])

    def _transacao(self, executar):
        try:
            return transactional(executar)(self.cliente.transaction(max_attempts=5))
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível concluir a transação.") from erro
        except ValueError as erro:
            if isinstance(erro.__cause__, Aborted):
                raise ErroPersistencia("Conflito concorrente. Reenvie a mesma operação.") from erro
            raise

    def _salvar_verificada(self, prova_id, nome, resultado, respostas, comprovante,
                          operacao_id, aluno_id, novo_homonimo, permitir_provisorio, origem_lote=None):
        prova_id = _id(prova_id)
        if type(novo_homonimo) is not bool or novo_homonimo and aluno_id is not None:
            raise ValueError("Selecione um aluno ou confirme outra pessoa com o mesmo nome.")
        if aluno_id is not None:
            aluno_id = _id(aluno_id)
        dados = self._dados_aluno(nome, novo_homonimo=novo_homonimo)
        chave = self._operacao("correcao", operacao_id)
        assinatura = resumo_canonico([prova_id, dados["nome_normalizado"], respostas, resultado,
                                     aluno_id, novo_homonimo, permitir_provisorio] +
                                    ([origem_lote] if origem_lote is not None else []))
        controle = self.cliente.collection("nomes_alunos").document(
            hashlib.sha256(dados["nome_normalizado"].encode()).hexdigest())
        correcao_id = uuid4().hex

        def salvar(tx):
            anterior = self._ler_transacao(chave, tx)
            if anterior:
                return self._repeticao(anterior, assinatura)
            prova = self._ler_transacao(self.cliente.collection("provas").document(prova_id), tx)
            oficial = self._ler_transacao(self.cliente.collection("gabaritos").document(prova_id), tx)
            if prova is None or oficial is None:
                raise ValueError("Avaliação ou gabarito oficial inexistente.")
            recalculado = corrigir_respostas(respostas, oficial["alternativas"])
            if resultado != recalculado:
                raise ValueError("Resultado diverge das respostas e do gabarito oficial.")
            conferir_respostas(comprovante, respostas, oficial["alternativas"])
            versao = self._ler_transacao(controle, tx) or {"versao": 0}
            criar = False
            if aluno_id is not None:
                aluno = self._ler_transacao(self.cliente.collection("alunos").document(aluno_id), tx)
                if aluno is None or normalizar_nome(aluno["nome"]) != dados["nome_normalizado"]:
                    raise ValueError("Aluno selecionado não corresponde ao nome confirmado.")
            elif novo_homonimo:
                aluno, criar = dados, True
            else:
                exatos = self._alunos_exatos(dados["nome_normalizado"], tx)
                if len(exatos) > 1:
                    raise AlunosAmbiguos(exatos)
                aluno, criar = (exatos[0], False) if exatos else (dados, True)
            registro = {"id": correcao_id, "prova_id": prova_id, "aluno": aluno["nome"],
                        "aluno_id": aluno["id"], "operacao_id": operacao_id,
                        "resultado": recalculado,
                        "respostas": deepcopy(respostas), "gabarito_hash": resumo_canonico(oficial["alternativas"]),
                        "situacao": "provisoria" if recalculado["provisorio"] else "sem_pendencias",
                        "processada_em": datetime.now(timezone.utc),
                        **({"origem_lote": deepcopy(origem_lote)} if origem_lote is not None else {})}
            # Toda resolução de nome participa do mesmo controle transacional.
            # Uma criação concorrente de homônimo força nova leitura/decisão.
            tx.set(controle, {"versao": versao["versao"] + 1})
            if criar:
                tx.create(self.cliente.collection("alunos").document(aluno["id"]), aluno)
            tx.create(self.cliente.collection("correcoes").document(correcao_id), registro)
            tx.create(chave, {"assinatura": assinatura, "operacao_id": operacao_id,
                              "registro": registro})
            return registro

        return self._transacao(salvar)

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
                exatos = self._alunos_exatos(dados["nome_normalizado"])
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

    def listar_alunos_pagina(self, busca="", *, limite=30, cursor=None):
        if not 1 <= limite <= 100:
            raise ValueError("Limite de página inválido.")
        prefixo = normalizar_nome(busca) if busca.strip() else ""
        legados = sorted((a for nomes in self._indice_legado().values() for a in nomes
                          if normalizar_nome(a["nome"]).startswith(prefixo)),
                         key=lambda a: (chave_busca(a["nome"]), a["id"]))
        if cursor and cursor.startswith("~legado~"):
            try:
                posicao = int(cursor.removeprefix("~legado~"))
            except ValueError:
                raise ValueError("Cursor de alunos inválido.") from None
            if posicao < 0 or posicao >= len(legados):
                raise ValueError("Cursor de alunos inválido.")
            pagina = legados[posicao:posicao + limite]
            proximo = posicao + limite
            return {"alunos": pagina,
                    "proximo_cursor": f"~legado~{proximo}" if proximo < len(legados) else None}
        consulta = self.cliente.collection("alunos")
        if prefixo:
            consulta = consulta.where(filter=FieldFilter("nome_normalizado", ">=", prefixo)).where(
                filter=FieldFilter("nome_normalizado", "<", prefixo + "\uf8ff"))
        consulta = consulta.order_by("nome_normalizado").order_by("__name__")
        try:
            if cursor:
                anterior = self.cliente.collection("alunos").document(_id(cursor)).get()
                if not anterior.exists or "nome_normalizado" not in anterior.to_dict():
                    raise ValueError("Cursor de alunos inválido.")
                consulta = consulta.start_after(anterior)
            documentos = list(consulta.limit(limite + 1).stream())
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível listar a página de alunos.") from erro
        atuais = [s.to_dict() for s in documentos[:limite]]
        if not atuais and legados:
            pagina = legados[:limite]
            return {"alunos": pagina,
                    "proximo_cursor": f"~legado~{limite}" if len(legados) > limite else None}
        proximo = (documentos[limite - 1].to_dict()["id"] if len(documentos) > limite
                   else "~legado~0" if legados else None)
        return {"alunos": atuais, "proximo_cursor": proximo}

    def correspondencias_aluno(self, nome):
        nome_normalizado, busca = normalizar_nome(nome), chave_busca(nome)
        exatos = self._alunos_exatos(nome_normalizado)
        # Sugestões limitadas por prefixo. Nunca associar por semelhança; só
        # nome exato ou seleção explícita pode definir o aluno da correção.
        prefixo = nome_normalizado[:2]
        semelhantes = []
        if prefixo:
            try:
                consulta = self.cliente.collection("alunos").where(
                    filter=FieldFilter("nome_normalizado", ">=", prefixo)).where(
                    filter=FieldFilter("nome_normalizado", "<", prefixo + "\uf8ff")).limit(40)
                semelhantes = [a for s in consulta.stream() if (a := s.to_dict())["id"] not in
                              {e["id"] for e in exatos} and
                              SequenceMatcher(None, busca, chave_busca(a["nome"])).ratio() >= .82]
                semelhantes.extend(a for nomes in self._indice_legado().values() for a in nomes
                                   if a["id"] not in {e["id"] for e in exatos}
                                   and SequenceMatcher(None, busca, chave_busca(a["nome"])).ratio() >= .82)
            except GoogleAPICallError as erro:
                raise ErroPersistencia("Não foi possível consultar nomes semelhantes.") from erro
        return {"exato": exatos[0] if len(exatos) == 1 else None, "exatos": exatos, "semelhantes": semelhantes}

    def historico_aluno(self, aluno_id):
        aluno_id = _id(aluno_id)
        aluno = self.consultar_aluno(aluno_id)
        if aluno is None:
            return None
        vinculadas, legadas = [], []
        try:
            por_id = self.cliente.collection("correcoes").where(
                filter=FieldFilter("aluno_id", "==", aluno_id)).stream()
            por_nome = self.cliente.collection("correcoes").where(
                filter=FieldFilter("aluno", "==", aluno["nome"])).stream()
            vinculadas = [deepcopy(s.to_dict()) for s in por_id]
            legadas = [deepcopy(registro) for s in por_nome
                       if not (registro := s.to_dict()).get("aluno_id")]
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível consultar o histórico.") from erro
        provas = {}
        for registro in (*vinculadas, *legadas):
            prova_id = registro["prova_id"]
            if prova_id not in provas:
                prova = self.consultar_prova(prova_id)
                provas[prova_id] = prova["titulo"] if prova else prova_id
            registro["avaliacao"] = provas[prova_id]
        for registros in (vinculadas, legadas):
            registros.sort(key=lambda c: str(c["processada_em"]), reverse=True)
        return {"aluno": aluno, "correcoes": vinculadas, "legadas_por_nome": legadas}

    def historico_aluno_pagina(self, aluno_id, *, limite=30, cursor=None, somente_legadas=False):
        if not 1 <= limite <= 100:
            raise ValueError("Limite de página inválido.")
        aluno_id = _id(aluno_id)
        aluno = self.consultar_aluno(aluno_id)
        if aluno is None:
            return None
        if somente_legadas:
            try:
                por_nome = self.cliente.collection("correcoes").where(
                    filter=FieldFilter("aluno", "==", aluno["nome"])).stream()
                legadas = [deepcopy(registro) for s in por_nome
                           if not (registro := s.to_dict()).get("aluno_id")]
            except GoogleAPICallError as erro:
                raise ErroPersistencia("Não foi possível consultar o histórico antigo.") from erro
            provas = {}
            for registro in legadas:
                prova_id = registro["prova_id"]
                if prova_id not in provas:
                    prova = self.consultar_prova(prova_id)
                    provas[prova_id] = prova["titulo"] if prova else prova_id
                registro["avaliacao"] = provas[prova_id]
            legadas.sort(key=lambda c: str(c["processada_em"]), reverse=True)
            return {"aluno": aluno, "correcoes": [], "legadas_por_nome": legadas,
                    "proximo_cursor": None}
        consulta = self.cliente.collection("correcoes").where(
            filter=FieldFilter("aluno_id", "==", aluno_id)).order_by(
                "processada_em", direction="DESCENDING").order_by("__name__")
        try:
            if cursor:
                anterior = self.cliente.collection("correcoes").document(_id(cursor)).get()
                if not anterior.exists or anterior.to_dict().get("aluno_id") != aluno_id:
                    raise ValueError("Cursor de histórico inválido.")
                consulta = consulta.start_after(anterior)
            documentos = list(consulta.limit(limite + 1).stream())
            correcoes = [deepcopy(s.to_dict()) for s in documentos[:limite]]
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Não foi possível consultar o histórico.") from erro
        provas = {}
        for registro in correcoes:
            prova_id = registro["prova_id"]
            if prova_id not in provas:
                prova = self.consultar_prova(prova_id)
                provas[prova_id] = prova["titulo"] if prova else prova_id
            registro["avaliacao"] = provas[prova_id]
        return {"aluno": aluno, "correcoes": correcoes, "legadas_por_nome": [],
                "proximo_cursor": documentos[limite - 1].to_dict()["id"] if len(documentos) > limite else None}
