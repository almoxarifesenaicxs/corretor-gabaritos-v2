from unittest.mock import MagicMock

import cv2
from fastapi.testclient import TestClient
from google.api_core.exceptions import PermissionDenied
import pytest

from app.main import app
from app.routes import interface
from app.services.persistencia import Persistencia, ErroPersistencia, RegistroExistente
from app.services.reconhecimento import ErroLeitura
from test_correcao import gabarito, respostas
from test_reconhecimento import cartao
from app.services.correcao import corrigir_respostas
from test_captura import folha
from test_persistencia import banco
from suporte_estabilizacao import entrada_segura
from uuid import uuid4

client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


@pytest.fixture
def repo():
    mock = MagicMock()
    def obter():
        # Usa a mesma tradução de erros da dependência real, com cliente simulado.
        try:
            yield mock
        except RegistroExistente:
            raise interface.HTTPException(409, "Registro existente")
        except ValueError:
            raise interface.HTTPException(422, "Dados inválidos")
        except ErroPersistencia:
            raise interface.HTTPException(503, "Banco indisponível")
    app.dependency_overrides[interface.obter_persistencia] = obter
    yield mock
    app.dependency_overrides.clear()


def test_interface_e_assets_preservam_api():
    assert client.get("/").json() == {"mensagem": "API do Corretor de Gabaritos funcionando!"}
    html = client.get("/interface/")
    assert html.status_code == 200
    assert 'data-tab="avaliacoes"' in html.text and 'data-tab="correcao"' in html.text
    assert 'id="evaluation-name"' not in html.text
    for caminho in ["css/style.css", "js/app.mjs", "js/camera.mjs", "js/api.mjs",
                    "js/paginas.mjs", "js/fluxo-captura.mjs", "js/revisao.mjs",
                    "pages/avaliacoes.html", "pages/correcao.html", "pages/alunos.html",
                    "components/captura.html"]:
        assert client.get("/interface/" + caminho).status_code == 200
    for pagina, elemento in [("avaliacoes", "evaluation-name"),
                             ("correcao", "student-name"), ("alunos", "student-search")]:
        fragmento = client.get(f"/interface/pages/{pagina}.html").text
        assert f'id="{elemento}"' in fragmento
        assert '<nav' not in fragmento and 'id="sidebar"' not in fragmento


def test_fluxo_avaliacao_requer_confirmacao(repo):
    entrada = {"titulo": "Avaliação", "alternativas": gabarito(), "confirmado": False, "operacao_id": uuid4().hex}
    assert client.post("/api/avaliacoes", json=entrada).status_code == 422
    repo.criar_avaliacao.assert_not_called()
    entrada["confirmado"] = True
    repo.criar_avaliacao.return_value = {"id": "prova-1", "titulo": "Avaliação"}
    resposta = client.post("/api/avaliacoes", json=entrada)
    assert resposta.status_code == 201
    repo.criar_avaliacao.assert_called_once_with("Avaliação", gabarito(), operacao_id=entrada["operacao_id"])
    repo.listar_provas.return_value = [resposta.json()]
    assert client.get("/api/avaliacoes").json() == [resposta.json()]
    repo.consultar_gabarito.return_value = {"alternativas": gabarito()}
    assert client.get("/api/avaliacoes/prova-1/gabarito").json()["alternativas"] == gabarito()
    repo.consultar_gabarito.return_value = None
    assert client.get("/api/avaliacoes/ausente/gabarito").status_code == 404


def test_reconhecimento_gabarito_e_captura_nao_gravam(repo):
    imagem = cartao({(1, 0): "cheia"})
    dados = cv2.imencode(".png", imagem)[1].tobytes()
    resposta = client.post("/api/gabaritos/reconhecer", files={"arquivo": ("cartao.png", dados)})
    assert resposta.status_code == 200
    assert len(resposta.json()) == 50
    assert resposta.json()["1"]["resposta"] == "A"
    assert resposta.json()["2"]["estado"] == "branco"
    resposta = client.post("/api/gabaritos/reconhecer", files={"arquivo": ("captura.png", dados)}, data={"captura": "true"})
    assert resposta.status_code == 200
    repo.assert_not_called()
    assert repo.method_calls == []


def test_salvar_somente_apos_confirmacao(repo):
    resultado = corrigir_respostas(respostas(), gabarito())
    entrada = entrada_segura("prova-1", aluno="Aluno", confirmado=False)
    assert client.post("/api/correcoes/salvar", json=entrada).status_code == 422
    repo.salvar_correcao.assert_not_called()
    entrada["confirmado"] = True
    repo.salvar_correcao.return_value = {"id": "correcao-1", **entrada}
    assert client.post("/api/correcoes/salvar", json=entrada).status_code == 201
    repo.salvar_correcao.assert_called_once_with("prova-1", "Aluno", resultado, permitir_provisorio=False,
                                               vincular_aluno=True, novo_homonimo=False, respostas=entrada["respostas"],
                                               comprovante=entrada["comprovante"], operacao_id=entrada["operacao_id"])


def test_salvar_provisorio_exige_aceite_no_servico_real(repo, banco):
    real, dados = banco
    prova = real.criar_avaliacao("Provisoria", gabarito())
    repo.salvar_correcao.side_effect = real.salvar_correcao
    entrada_respostas = respostas()
    entrada_respostas["1"] = {"resposta": None, "estado": "duvidosa", "alternativas": ["A"]}
    entrada = entrada_segura(prova["id"], respostas=entrada_respostas)
    antes = dict(dados)
    assert client.post("/api/correcoes/salvar", json=entrada).status_code == 422
    assert dados == antes
    entrada["permitir_provisorio"] = True
    resposta = client.post("/api/correcoes/salvar", json=entrada)
    assert resposta.status_code == 201
    assert resposta.json()["resultado"] == entrada["resultado"]
    assert resposta.json()["situacao"] == "provisoria"


def test_cadastro_invalido_http_usa_validacao_motor(repo):
    cliente = MagicMock()
    repo.criar_avaliacao.side_effect = Persistencia(cliente).criar_avaliacao
    resposta = client.post("/api/avaliacoes", json={"titulo": "Teste", "alternativas": {}, "confirmado": True, "operacao_id": uuid4().hex})
    assert resposta.status_code == 422
    cliente.batch.assert_not_called()


def test_cadastro_atomico_valida_antes_e_nao_sobrescreve():
    cliente = MagicMock()
    repo = Persistencia(cliente)
    with pytest.raises(ValueError):
        repo.criar_avaliacao("Teste", {})
    cliente.batch.assert_not_called()
    prova = repo.criar_avaliacao("Teste", gabarito())
    assert cliente.batch.return_value.create.call_count == 2
    cliente.batch.return_value.commit.assert_called_once()
    docs = cliente.batch.return_value.create.call_args_list
    assert docs[0].args[1]["id"] == docs[1].args[1]["prova_id"] == prova["id"]
    assert docs[1].args[1]["alternativas"] == gabarito()
    cliente.batch.return_value.commit.side_effect = PermissionDenied("segredo")
    with pytest.raises(ErroPersistencia):
        repo.criar_avaliacao("Teste", gabarito())


def test_sem_emulador_responde_503_sem_conexao(monkeypatch):
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    conexao = MagicMock()
    monkeypatch.setattr(interface, "conectar_firestore", conexao)
    resposta = client.get("/api/avaliacoes")
    assert resposta.status_code == 503
    conexao.assert_not_called()


@pytest.mark.parametrize("erro,status", [(RegistroExistente("privado"), 409),
                                        (ErroPersistencia("privado"), 503), (ValueError("privado"), 422)])
def test_erros_persistencia(repo, erro, status):
    repo.criar_avaliacao.side_effect = erro
    resposta = client.post("/api/avaliacoes", json={"titulo": "Teste", "alternativas": gabarito(), "confirmado": True, "operacao_id": uuid4().hex})
    assert resposta.status_code == status
    assert "privado" not in resposta.text


@pytest.mark.parametrize("rota", ["/api/gabaritos/reconhecer", "/api/capturas/analisar"])
def test_uploads_invalidos(rota):
    assert client.post(rota, files={"arquivo": ("cartao.exe", b"abc")}).status_code == 415
    assert client.post(rota, files={"arquivo": ("cartao.png", b"")}).status_code == 400
    assert client.post(rota, files={"arquivo": ("cartao.png", b"\x89PNG\r\n\x1a\nruim")}).status_code == 422


def test_analise_frame_baseada_em_imagem():
    for imagem, esperado in [(folha(), "vermelho"), (folha([[160,60],[640,60],[640,740],[160,740]]), "verde")]:
        resposta = client.post("/api/capturas/analisar", files={"arquivo": ("frame.png", cv2.imencode(".png", imagem)[1].tobytes())})
        assert resposta.status_code == 200
        assert resposta.json()["estado"] == esperado


def test_temporarios_limpos_em_falhas(monkeypatch, tmp_path):
    criar = interface.TemporaryDirectory
    monkeypatch.setattr(interface, "TemporaryDirectory", lambda **kwargs: criar(dir=tmp_path, **kwargs))
    monkeypatch.setattr(interface, "reconhecer_arquivo", MagicMock(side_effect=ErroLeitura("privado")))
    resposta = client.post("/api/gabaritos/reconhecer", files={"arquivo": ("cartao.png", cv2.imencode(".png", cartao())[1].tobytes())})
    assert resposta.status_code == 422
    assert "privado" not in resposta.text
    assert list(tmp_path.iterdir()) == []
