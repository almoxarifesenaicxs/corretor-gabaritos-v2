from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from google.api_core.exceptions import AlreadyExists, PermissionDenied, Aborted
from google.cloud.firestore_v1 import _helpers
from google.cloud.firestore_v1.base_query import FieldFilter
import pytest

from app.services.correcao import corrigir_respostas, ErroCorrecao
from app.services.persistencia import Persistencia, ErroPersistencia, RegistroExistente


def resultado(provisorio=False):
    respostas = {str(i): {"resposta": "A", "estado": "marcada", "alternativas": ["A"]}
                 for i in range(1, 51)}
    if provisorio:
        respostas["26"] = {"resposta": None, "estado": "multipla", "alternativas": ["A", "B"]}
    return corrigir_respostas(respostas, {str(i): "A" for i in range(1, 51)})


@pytest.fixture
def banco(monkeypatch):
    from app.services.persistencia import _LEGADOS
    _LEGADOS.clear()
    dados = {}
    cliente = MagicMock()

    def snapshot(valor, identificador=None):
        return SimpleNamespace(id=identificador, exists=valor is not None,
                               to_dict=lambda: deepcopy(valor))

    def colecao(nome):
        referencia = MagicMock()

        def documento(identificador):
            ref = MagicMock()
            ref.id = identificador
            ref.colecao = nome
            def criar(valor):
                if (nome, identificador) in dados:
                    raise AlreadyExists("Já existe")
                # Usa o codec real do SDK para simular o armazenamento/recuperação.
                dados[nome, identificador] = _helpers.decode_dict(_helpers.encode_dict(valor), cliente)
            ref.create.side_effect = criar
            def obter(transaction=None):
                chave = (nome, identificador)
                if transaction is not None:
                    transaction.leituras[chave] = deepcopy(dados.get(chave))
                return snapshot(dados.get(chave), identificador)
            ref.get.side_effect = obter
            return ref

        referencia.document.side_effect = documento
        referencia.stream.side_effect = lambda **kwargs: (snapshot(v, i) for (c, i), v in list(dados.items()) if c == nome)
        def filtrar(*, filter):
            consulta = MagicMock()
            filtros = [filter]
            limite = [None]
            ordenacao = []
            cursor = [None]
            consulta.where.side_effect = lambda *, filter: (filtros.append(filter) or consulta)
            consulta.limit.side_effect = lambda tamanho: (limite.__setitem__(0, tamanho) or consulta)
            consulta.order_by.side_effect = lambda campo, direction="ASCENDING": (ordenacao.append((campo, direction)) or consulta)
            consulta.start_after.side_effect = lambda anterior: (cursor.__setitem__(0, anterior.id) or consulta)
            def transmitir(transaction=None):
                def corresponde(chave, valor, filtro):
                    atual = chave[1] if filtro.field_path == "__name__" else valor.get(filtro.field_path)
                    if filtro.op_string == "==":
                        return atual == filtro.value
                    if atual is None:
                        return False
                    return atual >= filtro.value if filtro.op_string == ">=" else atual < filtro.value
                encontrados = [(chave, v) for chave, v in dados.items()
                               if chave[0] == nome and all(corresponde(chave, v, f) for f in filtros)]
                for campo, direction in reversed(ordenacao):
                    encontrados.sort(key=lambda item: item[0][1] if campo == "__name__" else item[1].get(campo),
                                    reverse=direction == "DESCENDING")
                if cursor[0] is not None:
                    indice = next((i for i, (_, valor) in enumerate(encontrados)
                                   if valor["id"] == cursor[0]), None)
                    encontrados = encontrados[indice + 1:] if indice is not None else []
                if limite[0] is not None:
                    encontrados = encontrados[:limite[0]]
                for chave, valor in encontrados:
                    if transaction is not None:
                        transaction.leituras[chave] = deepcopy(valor)
                    yield snapshot(valor, chave[1])
            consulta.stream.side_effect = transmitir
            return consulta
        referencia.where.side_effect = filtrar
        referencia.order_by.side_effect = lambda campo, direction="ASCENDING": filtrar(
            filter=FieldFilter(campo, ">=", "")).order_by(campo, direction)
        return referencia

    cliente.collection.side_effect = colecao
    def batch():
        escritas = []
        lote = MagicMock()
        lote.create.side_effect = lambda ref, valor: escritas.append((ref.colecao, ref.id, deepcopy(valor)))
        def commit():
            if any((c, i) in dados for c, i, _ in escritas):
                raise AlreadyExists('Conflito atômico')
            for c, i, valor in escritas:
                dados[c, i] = _helpers.decode_dict(_helpers.encode_dict(valor), cliente)
        lote.commit.side_effect = commit
        return lote
    cliente.batch.side_effect = batch
    class TransacaoSimulada:
        def __init__(self):
            self.leituras = {}
            self.escritas = []
        def create(self, ref, valor):
            self.escritas.append((True, (ref.colecao, ref.id), deepcopy(valor)))
        def set(self, ref, valor):
            self.escritas.append((False, (ref.colecao, ref.id), deepcopy(valor)))
        def commit(self):
            if any(dados.get(chave) != antes for chave, antes in self.leituras.items()):
                raise Aborted('Leitura modificada por outra transação')
            if any(criar and chave in dados for criar, chave, _ in self.escritas):
                raise AlreadyExists('Conflito atômico')
            for _, chave, valor in self.escritas:
                dados[chave] = _helpers.decode_dict(_helpers.encode_dict(valor), cliente)
    cliente.transaction.side_effect = lambda **kwargs: TransacaoSimulada()
    def executar_transacional(funcao):
        def executar(tx):
            for tentativa in range(5):
                tx.leituras.clear()
                tx.escritas.clear()
                retorno = funcao(tx)
                try:
                    tx.commit()
                    return retorno
                except Aborted:
                    if tentativa == 4:
                        raise
        return executar
    monkeypatch.setattr('app.services.persistencia.transactional', executar_transacional)
    return Persistencia(cliente), dados


def test_criar_consultar_listar_provas(banco):
    repo, _ = banco
    assert repo.listar_provas() == []
    prova = repo.criar_prova("  Prova 1  ", "Descrição")
    outra = repo.criar_prova("Prova 2")
    assert prova["id"] != outra["id"]
    assert prova["titulo"] == "Prova 1"
    assert isinstance(prova["criada_em"], datetime)
    assert prova["criada_em"].utcoffset().total_seconds() == 0
    assert repo.consultar_prova(prova["id"]) == prova
    assert {p["id"] for p in repo.listar_provas()} == {prova["id"], outra["id"]}
    assert repo.consultar_prova("ausente") is None


def test_gabarito_e_protecao_contra_sobrescrita(banco):
    repo, _ = banco
    prova = repo.criar_prova("Teste")
    oficial = {str(i): "A" for i in range(1, 51)}
    assert repo.consultar_gabarito(prova["id"]) is None
    cadastrado = repo.cadastrar_gabarito(prova["id"], oficial)
    assert cadastrado["id"] == prova["id"]
    oficial["1"] = "B"
    with pytest.raises(RegistroExistente):
        repo.cadastrar_gabarito(prova["id"], oficial)
    assert repo.consultar_gabarito(prova["id"])["alternativas"]["1"] == "A"


@pytest.mark.parametrize("oficial", [{}, {str(i): "A" for i in range(1, 50)},
    {str(i): "F" for i in range(1, 51)}, {i: "A" for i in range(1, 51)}])
def test_gabarito_invalido_nao_acessa_banco(oficial):
    cliente = MagicMock()
    with pytest.raises(ErroCorrecao):
        Persistencia(cliente).cadastrar_gabarito("prova", oficial)
    cliente.collection.assert_not_called()


def test_prova_inexistente(banco):
    repo, dados = banco
    with pytest.raises(ValueError, match="Prova inexistente"):
        repo.cadastrar_gabarito("ausente", {str(i): "A" for i in range(1, 51)})
    with pytest.raises(ValueError, match="Prova inexistente"):
        repo.salvar_correcao("ausente", "Aluno", resultado())
    assert dados == {}


def test_correcao_preserva_motor_serializa_e_filtra_por_prova(banco):
    repo, _ = banco
    prova, outra = repo.criar_prova("Um"), repo.criar_prova("Dois")
    entrada = resultado()
    antes = deepcopy(entrada)
    correcao = repo.salvar_correcao(prova["id"], "Aluno A", entrada)
    repo.salvar_correcao(outra["id"], "Aluno B", resultado())
    assert entrada == antes
    assert correcao["resultado"] == antes
    assert correcao["situacao"] == "sem_pendencias"
    assert repo.consultar_correcao(correcao["id"]) == correcao
    assert repo.listar_correcoes(prova["id"]) == [correcao]
    assert repo.listar_correcoes("inexistente") == []
    assert repo.consultar_correcao("inexistente") is None
    entrada["resumo"]["pontuacao"] = 0
    assert repo.consultar_correcao(correcao["id"])["resultado"] == antes


def test_provisorio_exige_decisao_explicita(banco):
    repo, dados = banco
    prova = repo.criar_prova("Provisória")
    entrada = resultado(True)
    with pytest.raises(ValueError, match="permitir_provisorio"):
        repo.salvar_correcao(prova["id"], "Aluno", entrada)
    assert len(dados) == 1
    correcao = repo.salvar_correcao(prova["id"], "Aluno", entrada, permitir_provisorio=True)
    assert correcao["situacao"] == "provisoria"
    assert repo.consultar_correcao(correcao["id"])["resultado"] == entrada


@pytest.mark.parametrize("operacao", ["criar", "consultar", "listar", "stream"])
def test_erros_do_banco(operacao):
    cliente = MagicMock()
    falha = PermissionDenied("mensagem interna do banco")
    repo = Persistencia(cliente)
    if operacao == "stream":
        def stream():
            yield MagicMock()
            raise falha
        cliente.collection.return_value.stream.side_effect = stream
    elif operacao == "criar":
        cliente.collection.return_value.document.return_value.create.side_effect = falha
    elif operacao == "consultar":
        cliente.collection.return_value.document.return_value.get.side_effect = falha
    else:
        cliente.collection.return_value.stream.side_effect = falha
    with pytest.raises(ErroPersistencia) as erro:
        if operacao == "criar":
            repo.criar_prova("Teste")
        elif operacao == "consultar":
            repo.consultar_prova("teste")
        else:
            repo.listar_provas()
    assert "mensagem interna" not in str(erro.value)


@pytest.mark.parametrize("invalido", [None, "", " ", 42])
def test_titulo_invalido(banco, invalido):
    with pytest.raises(ValueError):
        banco[0].criar_prova(invalido)


@pytest.mark.parametrize("invalido", ["a/b", "..", "", "a" * 1501])
def test_id_invalido(banco, invalido):
    with pytest.raises(ValueError):
        banco[0].consultar_prova(invalido)


@pytest.mark.parametrize("invalido", [None, {}, {"provisorio": False}, b"PDF"])
def test_resultado_invalido(banco, invalido):
    with pytest.raises(ValueError):
        banco[0].salvar_correcao("prova", "Aluno", invalido)


def test_sem_aluno_e_sem_descricao_textual(banco):
    with pytest.raises(ValueError):
        banco[0].salvar_correcao("prova", " ", resultado())
    with pytest.raises(ValueError):
        banco[0].criar_prova("Prova", descricao=b"PDF")
