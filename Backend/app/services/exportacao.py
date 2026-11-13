"""Exportação integral e conferência de correções no modo operacional local."""

import csv
from datetime import datetime, timezone
from io import StringIO
from uuid import UUID

from google.api_core.exceptions import GoogleAPICallError
from google.cloud.firestore_v1.base_query import FieldFilter

from app.services.persistencia import ErroPersistencia, _id


PAGINA = 200
MAX_CORRECOES = 20000
MAX_OPERACOES = 40000
CAMPOS = (
    "correcao_id", "operacao_id", "aluno_id", "aluno_nome", "avaliacao_id",
    "avaliacao", "processada_em_utc", "acertos", "erros", "em_branco",
    "pontuacao_total", "portugues_pontuacao", "matematica_pontuacao", "situacao",
    "lote_id", "lote_indice", "imagem_sha256", "arquivo_origem", "pagina_pdf",
)


class LimiteExportacao(ValueError):
    """A exportação deve falhar explicitamente em vez de omitir linhas."""


class AvaliacaoInexistente(ValueError):
    """Não tratar um filtro digitado incorretamente como resultado vazio."""


def _paginar(consulta, *, limite):
    """Lê todas as páginas em ordem estável; uma falha invalida o arquivo inteiro."""
    anterior = None
    total = 0
    try:
        while True:
            pagina = consulta.limit(PAGINA)
            if anterior is not None:
                pagina = pagina.start_after(anterior)
            documentos = list(pagina.stream())
            if len(documentos) > PAGINA:
                raise ErroPersistencia("Página de exportação inválida.")
            total += len(documentos)
            if total > limite:
                raise LimiteExportacao("Limite de exportação excedido; nenhum arquivo foi gerado.")
            yield from documentos
            if len(documentos) < PAGINA:
                break
            anterior = documentos[-1]
    except GoogleAPICallError as erro:
        raise ErroPersistencia("Leitura incompleta; nenhum arquivo foi gerado.") from erro


def _texto_csv(valor):
    """Neutraliza fórmulas, inclusive após espaços ou caracteres de controle."""
    texto = str(valor) if valor is not None else ""
    prefixo = texto.lstrip("\ufeff\t\r\n \v\f")
    if texto and (texto[0].isspace() or ord(texto[0]) < 32 or
                  prefixo.startswith(("=", "+", "-", "@"))):
        return "'" + texto
    return texto


def _pontuacao(registro, disciplina):
    try:
        valor = registro["resultado"]["disciplinas"][disciplina]["pontuacao"]
    except (KeyError, TypeError):
        return ""
    return valor


def exportar_correcoes(repo, prova_id=None):
    """Retorna CSV e manifesto somente após completar todas as leituras."""
    if prova_id is not None:
        prova_id = _id(prova_id)
    cliente = repo.cliente
    provas = {}
    if prova_id is not None:
        try:
            snapshot = cliente.collection("provas").document(prova_id).get()
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Falha ao consultar avaliação; nenhum arquivo foi gerado.") from erro
        if not snapshot.exists:
            raise AvaliacaoInexistente("Avaliação não encontrada; nenhum arquivo foi gerado.")
        provas[prova_id] = snapshot.to_dict().get("titulo", "")
    consulta = cliente.collection("correcoes")
    if prova_id is not None:
        consulta = consulta.where(filter=FieldFilter("prova_id", "==", prova_id))
    consulta = consulta.order_by("__name__")
    registros = []
    for documento in _paginar(consulta, limite=MAX_CORRECOES):
        registro = documento.to_dict()
        if not isinstance(registro, dict) or registro.get("id") != documento.id:
            raise ErroPersistencia("Identificador de correção inconsistente; nenhum arquivo foi gerado.")
        registros.append(registro)
    faltantes = {r["id"] for r in registros if not r.get("operacao_id")}
    operacoes = {}
    if faltantes:
        consulta_operacoes = cliente.collection("operacoes").order_by("__name__")
        for documento in _paginar(consulta_operacoes, limite=MAX_OPERACOES):
            if not documento.id.startswith("correcao-"):
                continue
            registro = documento.to_dict().get("registro") or {}
            identificador = registro.get("id")
            if identificador not in faltantes:
                continue
            try:
                operacao = documento.to_dict().get("operacao_id") or str(
                    UUID(hex=documento.id.removeprefix("correcao-")))
            except ValueError as erro:
                raise ErroPersistencia("Identificador de operação inconsistente; nenhum arquivo foi gerado.") from erro
            if identificador in operacoes and operacoes[identificador] != operacao:
                raise ErroPersistencia("Operações conflitantes; nenhum arquivo foi gerado.")
            operacoes[identificador] = operacao

    for identificador in {r["prova_id"] for r in registros} - provas.keys():
        try:
            snapshot = cliente.collection("provas").document(identificador).get()
        except GoogleAPICallError as erro:
            raise ErroPersistencia("Falha ao consultar avaliação; nenhum arquivo foi gerado.") from erro
        provas[identificador] = snapshot.to_dict().get("titulo", "") if snapshot.exists else ""

    saida = StringIO(newline="")
    saida.write("\ufeff")
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(CAMPOS)
    identificadores = []
    alunos = set()
    sem_operacao = 0
    sem_avaliacao = 0
    sem_aluno_id = 0
    for registro in registros:
        try:
            resumo = registro["resultado"]["resumo"]
            horario = registro["processada_em"]
            if not isinstance(horario, datetime) or horario.tzinfo is None:
                raise ValueError("Data inválida")
            horario = horario.astimezone(timezone.utc).isoformat()
            correcao_id = registro["id"]
            avaliacao_id = registro["prova_id"]
            aluno_id = registro.get("aluno_id") or ""
            operacao_id = registro.get("operacao_id") or operacoes.get(correcao_id, "")
            valores = (correcao_id, operacao_id, aluno_id, registro["aluno"],
                       avaliacao_id, provas[avaliacao_id], horario, resumo["acertos"],
                       resumo["erros"], resumo["brancos"], resumo["pontuacao"],
                       _pontuacao(registro, "portugues"), _pontuacao(registro, "matematica"),
                       registro.get("situacao", ""),
                       (registro.get("origem_lote") or {}).get("lote_id", ""),
                       (registro.get("origem_lote") or {}).get("indice", ""),
                       (registro.get("origem_lote") or {}).get("imagem_sha256", ""),
                       (registro.get("origem_lote") or {}).get("arquivo", ""),
                       (registro.get("origem_lote") or {}).get("pagina", ""))
        except (KeyError, TypeError, ValueError) as erro:
            raise ErroPersistencia("Correção inconsistente; nenhum arquivo foi gerado.") from erro
        escritor.writerow([_texto_csv(valor) for valor in valores])
        identificadores.append({"correcao_id": correcao_id, "operacao_id": operacao_id})
        if aluno_id:
            alunos.add(aluno_id)
        else:
            alunos.add("legado:" + str(registro["aluno"]))
        sem_operacao += not bool(operacao_id)
        sem_avaliacao += not bool(provas[avaliacao_id])
        sem_aluno_id += not bool(aluno_id)
    return {
        "csv": saida.getvalue(),
        "resumo": {
            "exportado_em_utc": datetime.now(timezone.utc).isoformat(),
            "avaliacao_id": prova_id,
            "total_correcoes": len(registros),
            "alunos_distintos": len(alunos),
            "operacoes_sem_id": sem_operacao,
            "avaliacoes_sem_titulo": sem_avaliacao,
            "alunos_sem_id": sem_aluno_id,
            "alunos_distintos_exatos": sem_aluno_id == 0,
            "identificadores": identificadores,
        },
    }
