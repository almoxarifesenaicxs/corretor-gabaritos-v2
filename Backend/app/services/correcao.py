"""Correção de 50 questões com gabarito explícito, sem dependências externas."""

ALTERNATIVAS = frozenset("ABCDE")
QUESTOES = frozenset(str(i) for i in range(1, 51))
ESTADOS = frozenset({"marcada", "branco", "multipla", "duvidosa"})


class ErroCorrecao(ValueError):
    """Gabarito ou respostas incompatíveis com o contrato da correção."""


def _validar_questoes(dados, nome):
    if not isinstance(dados, dict) or dados.keys() != QUESTOES:
        raise ErroCorrecao(f"{nome} deve conter exatamente as chaves textuais de 1 a 50.")


def _validar_resposta(numero, item):
    if not isinstance(item, dict) or item.keys() != {"resposta", "estado", "alternativas"}:
        raise ErroCorrecao(f"Questão {numero}: esperados resposta, estado e alternativas.")
    resposta, estado, candidatas = item["resposta"], item["estado"], item["alternativas"]
    if not isinstance(estado, str) or estado not in ESTADOS:
        raise ErroCorrecao(f"Questão {numero}: estado inválido.")
    if (not isinstance(candidatas, list)
            or any(not isinstance(a, str) or a not in ALTERNATIVAS for a in candidatas)
            or len(set(candidatas)) != len(candidatas)):
        raise ErroCorrecao(f"Questão {numero}: alternativas candidatas inválidas.")
    if estado == "marcada":
        consistente = isinstance(resposta, str) and resposta in ALTERNATIVAS and candidatas == [resposta]
    else:
        minimo = {"branco": 0, "multipla": 2, "duvidosa": 1}[estado]
        consistente = resposta is None and len(candidatas) >= minimo
        if estado == "branco":
            consistente = consistente and not candidatas
    if not consistente:
        raise ErroCorrecao(f"Questão {numero}: resposta e alternativas inconsistentes com o estado.")


def validar_gabarito(gabarito_oficial: dict) -> None:
    """Valida um gabarito explícito sem exigir respostas reconhecidas."""
    _validar_questoes(gabarito_oficial, "Gabarito oficial")
    for numero, alternativa in gabarito_oficial.items():
        if not isinstance(alternativa, str) or alternativa not in ALTERNATIVAS:
            raise ErroCorrecao(f"Gabarito oficial: alternativa inválida na questão {numero}.")


def corrigir_respostas(respostas: dict, gabarito_oficial: dict) -> dict:
    """Compara o retorno do reconhecimento com um gabarito A–E de 50 questões.

    Erros são apenas marcações válidas incorretas. Brancos e pendências ficam
    separados. Percentuais usam todas as questões, inclusive as pendentes.
    As entradas não são modificadas e não há inferência de gabarito.
    """
    validar_gabarito(gabarito_oficial)
    _validar_questoes(respostas, "Respostas")
    for numero, item in respostas.items():
        _validar_resposta(numero, item)

    def contabilizar(numeros):
        contagem = dict.fromkeys(("acertos", "erros", "brancos", "multiplas", "duvidosas"), 0)
        for numero in numeros:
            chave = str(numero)
            item = respostas[chave]
            if item["estado"] == "marcada":
                categoria = "acertos" if item["resposta"] == gabarito_oficial[chave] else "erros"
            else:
                categoria = {"branco": "brancos", "multipla": "multiplas", "duvidosa": "duvidosas"}[item["estado"]]
            contagem[categoria] += 1
        contagem["pendentes"] = contagem["multiplas"] + contagem["duvidosas"]
        contagem["pontuacao"] = contagem["acertos"]
        contagem["pontuacao_maxima"] = len(numeros)
        contagem["percentual_acertos"] = round(contagem["acertos"] / len(numeros) * 100, 2)
        return contagem

    pendentes = [str(i) for i in range(1, 51) if respostas[str(i)]["estado"] in {"multipla", "duvidosa"}]
    return {
        "provisorio": bool(pendentes),
        "resumo": contabilizar(range(1, 51)),
        "disciplinas": {
            "portugues": contabilizar(range(1, 26)),
            "matematica": contabilizar(range(26, 51)),
        },
        "questoes_pendentes": pendentes,
    }
