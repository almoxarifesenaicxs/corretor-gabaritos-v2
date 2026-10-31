from copy import deepcopy

import pytest

from app.services.correcao import ErroCorrecao, corrigir_respostas
from app.services.reconhecimento import reconhecer_imagem
from test_reconhecimento import cartao


def gabarito():
    # Gabarito fictício explícito para testes, sem relação com PDFs locais.
    return {str(i): "A" for i in range(1, 51)}


def respostas(estado="marcada", alternativa="A"):
    candidatas = {"marcada": [alternativa], "branco": [],
                  "multipla": ["A", "B"], "duvidosa": ["A"]}[estado]
    return {str(i): {"resposta": alternativa if estado == "marcada" else None,
                     "estado": estado, "alternativas": candidatas.copy()} for i in range(1, 51)}


@pytest.mark.parametrize("estado,alternativa,categoria,pontos,provisorio", [
    ("marcada", "A", "acertos", 50, False),
    ("marcada", "B", "erros", 0, False),
    ("branco", "A", "brancos", 0, False),
    ("multipla", "A", "multiplas", 0, True),
    ("duvidosa", "A", "duvidosas", 0, True),
])
def test_cinquenta_respostas(estado, alternativa, categoria, pontos, provisorio):
    resultado = corrigir_respostas(respostas(estado, alternativa), gabarito())
    resumo = resultado["resumo"]
    assert resumo[categoria] == 50
    assert sum(resumo[c] for c in ("acertos", "erros", "brancos", "multiplas", "duvidosas")) == 50
    assert resumo["pontuacao"] == pontos
    assert resumo["pontuacao_maxima"] == 50
    assert resumo["percentual_acertos"] == pontos * 2
    assert resultado["provisorio"] is provisorio
    assert resultado["questoes_pendentes"] == ([str(i) for i in range(1, 51)] if provisorio else [])
    for disciplina in resultado["disciplinas"].values():
        assert disciplina[categoria] == 25
        assert disciplina["pontuacao"] == pontos // 2
        assert disciplina["pontuacao_maxima"] == 25
        assert disciplina["percentual_acertos"] == pontos * 2


def test_mistura_limite_disciplinas_e_entradas_preservadas():
    entrada = respostas()
    entrada["25"] = respostas("marcada", "B")["25"]
    entrada["26"] = respostas("branco")["26"]
    entrada["27"] = respostas("multipla")["27"]
    entrada["50"] = respostas("duvidosa")["50"]
    oficial = gabarito()
    antes = deepcopy((entrada, oficial))
    resultado = corrigir_respostas(entrada, oficial)
    assert (entrada, oficial) == antes
    assert resultado["resumo"] == {
        "acertos": 46, "erros": 1, "brancos": 1, "multiplas": 1, "duvidosas": 1,
        "pendentes": 2, "pontuacao": 46, "pontuacao_maxima": 50, "percentual_acertos": 92.0,
    }
    assert resultado["provisorio"] is True
    assert resultado["questoes_pendentes"] == ["27", "50"]
    portugues, matematica = (resultado["disciplinas"][d] for d in ("portugues", "matematica"))
    assert (portugues["pontuacao"], portugues["percentual_acertos"], portugues["erros"]) == (24, 96.0, 1)
    assert (matematica["pontuacao"], matematica["percentual_acertos"], matematica["pendentes"]) == (22, 88.0, 2)


@pytest.mark.parametrize("invalido", [None, [], {}, {str(i): "A" for i in range(1, 50)},
    {str(i): "A" for i in range(1, 52)}, {i: "A" for i in range(1, 51)}])
def test_estrutura_gabarito_invalida(invalido):
    with pytest.raises(ErroCorrecao):
        corrigir_respostas(respostas(), invalido)


@pytest.mark.parametrize("invalida", ["F", "a", " A", "", None, 1, [], {"resposta": "A"}])
def test_alternativa_oficial_invalida(invalida):
    oficial = gabarito()
    oficial["1"] = invalida
    with pytest.raises(ErroCorrecao):
        corrigir_respostas(respostas(), oficial)


@pytest.mark.parametrize("item", [
    None, {}, {"resposta": "A"},
    {"resposta": "A", "estado": "inexistente", "alternativas": ["A"]},
    {"resposta": "A", "estado": [], "alternativas": ["A"]},
    {"resposta": "F", "estado": "marcada", "alternativas": ["F"]},
    {"resposta": "A", "estado": "marcada", "alternativas": ["B"]},
    {"resposta": "A", "estado": "marcada", "alternativas": "A"},
    {"resposta": None, "estado": "branco", "alternativas": ["A"]},
    {"resposta": "A", "estado": "multipla", "alternativas": ["A", "B"]},
    {"resposta": None, "estado": "multipla", "alternativas": ["A"]},
    {"resposta": None, "estado": "duvidosa", "alternativas": []},
    {"resposta": None, "estado": "duvidosa", "alternativas": ["A", "A"]},
    {"resposta": None, "estado": "duvidosa", "alternativas": [[]]},
])
def test_resposta_inconsistente(item):
    entrada = respostas()
    entrada["1"] = item
    with pytest.raises(ErroCorrecao):
        corrigir_respostas(entrada, gabarito())


@pytest.mark.parametrize("entrada", [None, [], {}, {str(i): {} for i in range(1, 50)}])
def test_respostas_incompletas(entrada):
    with pytest.raises(ErroCorrecao):
        corrigir_respostas(entrada, gabarito())


def test_integracao_com_opencv():
    reconhecidas = reconhecer_imagem(cartao({
        (1, 0): "cheia", (25, 1): "cheia", (26, 0): "cheia",
        (27, 0): "cheia", (27, 1): "cheia", (50, 2): "parcial",
    }))
    resultado = corrigir_respostas(reconhecidas, gabarito())
    assert resultado["resumo"] == {
        "acertos": 2, "erros": 1, "brancos": 45, "multiplas": 1, "duvidosas": 1,
        "pendentes": 2, "pontuacao": 2, "pontuacao_maxima": 50, "percentual_acertos": 4.0,
    }
    assert resultado["provisorio"] is True
    assert resultado["questoes_pendentes"] == ["27", "50"]


def test_gabarito_obrigatorio():
    with pytest.raises(TypeError):
        corrigir_respostas(respostas())
