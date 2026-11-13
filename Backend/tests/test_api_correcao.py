import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import correcoes
from app.services.correcao import corrigir_respostas
from app.services.reconhecimento import ErroLeitura, reconhecer_imagem
from test_reconhecimento import cartao
from test_fotos_cartoes import _grade_sintetica

client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
URL = "/api/correcoes/processar"
OFICIAL = {str(i): "A" for i in range(1, 51)}  # Fictício e explícito.


@pytest.fixture(autouse=True)
def verificar_limpeza(monkeypatch, tmp_path):
    criar_diretorio = correcoes.TemporaryDirectory
    monkeypatch.setattr(correcoes, "TemporaryDirectory",
                        lambda **kwargs: criar_diretorio(dir=tmp_path, **kwargs))
    yield
    assert list(tmp_path.iterdir()) == []


def enviar(conteudo, nome="cartao.png", gabarito=None):
    return client.post(URL, files={"arquivo": (nome, conteudo, "application/octet-stream")},
                       data={"gabarito": json.dumps(OFICIAL) if gabarito is None else gabarito})


@pytest.fixture
def imagem():
    return cartao({(1, 0): "cheia", (25, 1): "cheia", (26, 0): "cheia",
                   (27, 0): "cheia", (27, 1): "cheia", (50, 2): "parcial"})


@pytest.mark.parametrize("extensao", [".png", ".jpg", ".jpeg", ".PNG"])
def test_upload_imagem(imagem, extensao):
    conteudo = cv2.imencode(extensao.lower(), imagem)[1].tobytes()
    response = enviar(conteudo, "cartão" + extensao)
    assert response.status_code == 200
    # Compara o contrato completo, incluindo disciplinas e pendências.
    esperada = corrigir_respostas(reconhecer_imagem(imagem), OFICIAL)
    assert response.json() == esperada
    assert response.json()["provisorio"] is True
    assert response.json()["questoes_pendentes"] == ["27", "50"]


def test_upload_pdf(imagem):
    with pymupdf.open() as documento:
        pagina = documento.new_page(width=850, height=1100)
        pagina.insert_image(pagina.rect, stream=cv2.imencode(".png", imagem)[1].tobytes())
        conteudo = documento.tobytes()
    response = enviar(conteudo, "cartao.pdf")
    assert response.status_code == 200
    assert response.json() == corrigir_respostas(reconhecer_imagem(imagem), OFICIAL)


@pytest.mark.parametrize("campo", ["arquivo", "gabarito"])
def test_campo_ausente(campo):
    kwargs = {"files": {"arquivo": ("cartao.png", b"abc")}, "data": {"gabarito": json.dumps(OFICIAL)}}
    kwargs.pop("files" if campo == "arquivo" else "data")
    response = client.post(URL, **kwargs)
    assert response.status_code == 422


@pytest.mark.parametrize("conteudo,nome,status", [
    (b"", "cartao.png", 400),
    (b"abc", "cartao.txt", 415),
    (b"abc", "cartao.pdf", 415),
    (b"%PDF-corrompido", "cartao.pdf", 422),
    (b"\x89PNG\r\n\x1a\ncorrompido", "cartao.png", 422),
    (b"\xff\xd8\xffcorrompido", "cartao.jpg", 422),
])
def test_arquivo_invalido(conteudo, nome, status):
    response = enviar(conteudo, nome)
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)


def test_grade_nao_identificada():
    branco = np.full((500, 500, 3), 255, np.uint8)
    response = enviar(cv2.imencode(".png", branco)[1].tobytes())
    assert response.status_code == 422
    assert "grade" in response.json()["detail"]


def test_diagnostico_da_captura_registra_so_metadados(caplog):
    branco = np.full((500, 600, 3), 255, np.uint8)
    conteudo = cv2.imencode(".jpg", branco)[1].tobytes()
    with caplog.at_level("INFO", logger="app.routes.correcoes"):
        response = client.post(URL,
            files={"arquivo": ("aluno-privado.jpg", conteudo, "image/jpeg")},
            data={"gabarito": json.dumps(OFICIAL), "captura": "true"})
    assert response.status_code == 422
    assert "entrada_px=600x500" in caplog.text
    assert "processado_px=600x500" in caplog.text
    assert "etapa=grade_circular" in caplog.text
    assert "aluno-privado" not in caplog.text


def test_http_captura_assistida_reconhece_margens_grandes_sem_salvar():
    pagina = cv2.resize(_grade_sintetica(), (500, 707), interpolation=cv2.INTER_AREA)
    foto = np.full((2600, 2200, 3), 55, np.uint8)
    foto[450:1157, 250:750] = pagina
    dados = cv2.imencode(".jpg", foto, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
    cantos = [[250 / 2200, 450 / 2600], [749 / 2200, 450 / 2600],
              [749 / 2200, 1156 / 2600], [250 / 2200, 1156 / 2600]]
    response = client.post(URL, files={"arquivo": ("captura.jpg", dados, "image/jpeg")},
        data={"gabarito": json.dumps(OFICIAL), "captura": "true", "visual": "true",
              "cantos": json.dumps(cantos)})
    assert response.status_code == 200
    body = response.json()
    assert len(body["respostas"]) == 50
    assert [body["respostas"][str(n)]["resposta"] for n in range(1, 51)] == list("ABCDE" * 10)
    assert len(body["visualizacao"]["posicoes"]) == 50
    assert client.post(URL, files={"arquivo": ("captura.jpg", dados, "image/jpeg")},
        data={"gabarito": json.dumps(OFICIAL), "cantos": json.dumps(cantos)}).status_code == 422


@pytest.mark.parametrize("mensagem,codigo", [
    ("Tabela incompleta: esperadas seis colunas", "tabela_contagem_linhas_colunas"),
    ("Tabela com linha vertical interrompida.", "tabela_continuidade_vertical"),
    ("Tabela com linha horizontal interrompida.", "tabela_continuidade_horizontal"),
    ("Tabela com espaçamento irregular.", "tabela_espacamento"),
    ("Esperadas duas tabelas lado a lado.", "tabelas_posicionamento"),
    ("caminho privado ou nome de aluno", "nao_classificada"),
])
def test_codigo_de_rejeicao_nao_expoe_mensagem(mensagem, codigo):
    assert correcoes._etapa_rejeicao(ErroLeitura(mensagem)) == codigo


def test_pdf_protegido():
    with pymupdf.open() as documento:
        documento.new_page()
        conteudo = documento.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                     owner_pw="dono", user_pw="senha")
    response = enviar(conteudo, "cartao.pdf")
    assert response.status_code == 422


@pytest.mark.parametrize("gabarito", ["{", "null", "[]", "{}",
    json.dumps({str(i): "A" for i in range(1, 50)}),
    json.dumps({str(i): "F" for i in range(1, 51)}),
    json.dumps({str(i): "A" for i in range(1, 52)}),
    json.dumps(OFICIAL)[:-1] + ', "1": "B"}',
])
def test_gabarito_invalido_antes_do_reconhecimento(monkeypatch, gabarito):
    def nao_executar(_):
        pytest.fail("Reconhecimento não deve executar com gabarito inválido.")
    monkeypatch.setattr(correcoes, "reconhecer_arquivo", nao_executar)
    response = enviar(b"\x89PNG\r\n\x1a\n", gabarito=gabarito)
    assert response.status_code == 422
    assert "Gabarito inválido" in response.json()["detail"]


def test_upload_acima_do_limite():
    response = enviar(b"x" * (correcoes.LIMITE_UPLOAD + 1))
    assert response.status_code == 413


@pytest.mark.parametrize("falha", [None, ErroLeitura("caminho privado"), RuntimeError("C:/privado/segredo.pdf")])
def test_limpeza_temporarios_e_erros_sem_detalhes(monkeypatch, falha):
    caminhos = []

    def reconhecer(caminho):
        caminhos.append(Path(caminho))
        assert caminho.exists()
        assert caminho.name == "cartao.png"
        if falha:
            raise falha
        return {str(i): {"resposta": None, "estado": "branco", "alternativas": []}
                for i in range(1, 51)}

    monkeypatch.setattr(correcoes, "reconhecer_arquivo", reconhecer)
    response = enviar(b"\x89PNG\r\n\x1a\n", "../../privado.png")
    assert response.status_code == (200 if falha is None else 422 if isinstance(falha, ErroLeitura) else 500)
    assert len(caminhos) == 1
    assert not caminhos[0].exists()
    assert not caminhos[0].parent.exists()
    assert "privado" not in response.text
    assert "Traceback" not in response.text


def test_limite_sem_confiar_no_tamanho_declarado(monkeypatch):
    from io import BytesIO
    from starlette.datastructures import UploadFile

    monkeypatch.setattr(correcoes, "LIMITE_UPLOAD", 8)
    arquivo = UploadFile(BytesIO(b"x" * 9), filename="cartao.png", size=None)
    try:
        with pytest.raises(correcoes.HTTPException) as erro:
            correcoes.processar(arquivo, json.dumps(OFICIAL))
        assert erro.value.status_code == 413
    finally:
        arquivo.file.close()
