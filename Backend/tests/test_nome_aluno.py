from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import interface
from app.services import nome_aluno
from app.services.reconhecimento import carregar_imagem
from app.services.captura import retificar_captura


def cartao_nome(nome="MARIA DA SILVA"):
    imagem = np.full((1100, 850, 3), 255, np.uint8)
    cv2.line(imagem, (191, 308), (740, 308), (0, 0, 0), 2)
    cv2.line(imagem, (145, 368), (740, 368), (0, 0, 0), 2)
    if nome:
        cv2.putText(imagem, nome, (210, 300), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2)
    return imagem


@pytest.mark.parametrize("arquivo", ["Gabarito em Branco.pdf", "Gabarito Prova AIB.pdf"])
def test_regiao_real_identificada_e_nome_real_vazio(arquivo, monkeypatch):
    caminho = Path(__file__).parent / "fixtures" / "local" / arquivo
    if not caminho.is_file():
        pytest.skip("PDF de referência local ausente")
    imagem = carregar_imagem(caminho)
    recorte = nome_aluno.recortar_nome(imagem)
    assert recorte is not None
    assert recorte.shape[1] > imagem.shape[1] * .5
    motor = MagicMock()
    monkeypatch.setattr(nome_aluno, "_motor", motor)
    resposta = nome_aluno.ler_nome(imagem)
    assert resposta["nome"] is None
    assert resposta["estado"] == "nao_identificado"
    motor.assert_not_called()
    # Não retificar uma tabela lateral como se fosse a página inteira.
    dados = cv2.imencode('.png', imagem)[1].tobytes()
    assert retificar_captura(dados) == dados


@pytest.mark.parametrize("textos,scores,esperado", [
    (["MARIA DA SILVA"], [.99], "sugerido"),
    (["JOÃO DA SILVA"], [.99], "sugerido"),
    (["MARIA DA SILVA"], [.70], "baixa_confianca"),
    (["Candidato Curso"], [.99], "baixa_confianca"),
    (["MARIA 123 SILVA"], [.99], "baixa_confianca"),
    (["MARIA DA SILVA"], [float("nan")], "baixa_confianca"),
    ([], [], "nao_identificado"),
])
def test_confianca_e_falsos_positivos(monkeypatch, textos, scores, esperado):
    reconhecer = MagicMock(return_value=SimpleNamespace(txts=textos, scores=scores))
    monkeypatch.setattr(nome_aluno, "_motor", lambda: reconhecer)
    resposta = nome_aluno.ler_nome(cartao_nome())
    assert resposta["estado"] == esperado
    assert resposta["nome"] == (" ".join(textos) if esperado == "sugerido" else None)
    recorte = reconhecer.call_args.args[0]
    assert recorte.shape[0] < 80 and recorte.shape[1] < 850  # Somente o campo, não a página.


def test_motor_real_local_reconhece_nome_impresso_sintetico_sem_rede(monkeypatch):
    # Não é manuscrito nem amostra real: verifica compatibilidade e inferência local.
    import requests
    def bloquear(*args, **kwargs):
        pytest.fail("OCR não pode baixar modelo ou enviar imagem durante inferência.")
    monkeypatch.setattr(requests.sessions.Session, "request", bloquear)
    nome_aluno._motor.cache_clear()
    resposta = nome_aluno.ler_nome(cartao_nome())
    assert resposta["nome"] == "MARIA DA SILVA"
    assert resposta["estado"] == "sugerido"
    assert resposta["confianca"] >= .96


def test_falha_modelo_permite_entrada_manual(monkeypatch):
    monkeypatch.setattr(nome_aluno, "_motor", MagicMock(side_effect=RuntimeError("caminho privado")))
    resposta = nome_aluno.ler_nome(cartao_nome())
    assert resposta["estado"] == "indisponivel"
    assert resposta["nome"] is None
    assert "privado" not in str(resposta)


def test_layout_desconhecido_sem_nome(monkeypatch):
    motor = MagicMock()
    monkeypatch.setattr(nome_aluno, "_motor", motor)
    assert nome_aluno.ler_nome(np.full((800, 800, 3), 255, np.uint8))["nome"] is None
    motor.assert_not_called()


def test_rota_nome_mantem_imagem_temporaria_e_nao_salva(monkeypatch, tmp_path):
    cliente = TestClient(app)
    temporario = interface.TemporaryDirectory
    monkeypatch.setattr(interface, "TemporaryDirectory", lambda **kwargs: temporario(dir=tmp_path, **kwargs))
    sugestao = {"nome": "MARIA DA SILVA", "estado": "sugerido", "confianca": .99, "mensagem": "Confira"}
    leitor = MagicMock(return_value=sugestao)
    retificar = MagicMock(side_effect=lambda dados: dados)
    monkeypatch.setattr(interface, "ler_nome", leitor)
    monkeypatch.setattr(interface, "retificar_captura", retificar)
    conexao = MagicMock()
    monkeypatch.setattr(interface, "conectar_firestore", conexao)
    imagem = cartao_nome()
    resposta = cliente.post('/api/alunos/reconhecer-nome', files={'arquivo': ('captura.png', cv2.imencode('.png', imagem)[1].tobytes())}, data={'captura': 'true'})
    assert resposta.status_code == 200
    assert resposta.json() == sugestao
    retificar.assert_called_once()
    np.testing.assert_array_equal(leitor.call_args.args[0], imagem)
    conexao.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("nome,dados,status", [("invalido.txt", b"abc", 415),
    ("vazio.png", b"", 400), ("ruim.png", b"\x89PNG\r\n\x1a\nruim", 422)])
def test_rota_nome_rejeita_arquivo_invalido(nome, dados, status):
    resposta = TestClient(app).post('/api/alunos/reconhecer-nome', files={'arquivo': (nome, dados)})
    assert resposta.status_code == status
