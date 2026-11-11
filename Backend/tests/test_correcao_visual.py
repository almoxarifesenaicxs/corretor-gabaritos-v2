import base64
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import correcao_visual
from app.services.reconhecimento import reconhecer_imagem, carregar_imagem, ErroLeitura
from app.services.captura import retificar_captura, decodificar_captura
from test_reconhecimento import cartao

OFICIAL = {str(i): 'A' for i in range(1, 51)}


def imagem_mista():
    return cartao({(1,0): 'cheia', (2,1): 'cheia', (4,0): 'cheia', (4,1): 'cheia', (5,0): 'parcial'})


def test_classificacoes_posicoes_e_imagem_original_preservada():
    imagem = imagem_mista()
    antes = imagem.copy()
    respostas = reconhecer_imagem(imagem)
    marcacoes = correcao_visual.classificar_questoes(respostas, OFICIAL)
    assert [marcacoes[str(i)]['estado'] for i in range(1,6)] == ['correta', 'incorreta', 'branco', 'pendente', 'pendente']
    visual = correcao_visual.preparar_visualizacao(imagem)
    assert len(visual['posicoes']) == 50
    posicao = visual['posicoes']['1']['A']
    assert abs(posicao['x']+posicao['largura']/2-100) < 1
    assert abs(posicao['y']+posicao['altura']/2-70) < 1
    bytes_png = base64.b64decode(visual['imagem'].split(',')[1])
    recuperada = cv2.imdecode(np.frombuffer(bytes_png, np.uint8), cv2.IMREAD_COLOR)
    np.testing.assert_array_equal(imagem, recuperada)
    np.testing.assert_array_equal(imagem, antes)


def test_posicoes_apos_retificacao_coincidem_com_imagem_enviada():
    fundo = np.full((1400,1600,3), 35, np.uint8)
    fundo[260:1137,490:1110] = cv2.resize(imagem_mista(), (620,877))
    capturada = cv2.imencode('.png', fundo)[1].tobytes()
    retificada = decodificar_captura(retificar_captura(capturada))
    assert retificada.shape == (1754,1240,3)
    respostas = reconhecer_imagem(retificada)
    assert respostas['1']['resposta'] == 'A'
    visual = correcao_visual.preparar_visualizacao(retificada)
    box = visual['posicoes']['1']['A']
    x,y = round(box['x']+box['largura']/2), round(box['y']+box['altura']/2)
    assert np.mean(retificada[y-2:y+3,x-2:x+3]) < 50
    assert visual['largura'] == retificada.shape[1]
    assert visual['altura'] == retificada.shape[0]


@pytest.mark.parametrize('nome', ['Gabarito em Branco.pdf', 'Gabarito Prova AIB.pdf'])
def test_geometria_das_tabelas_reais(nome):
    caminho = Path(__file__).parent/'fixtures'/'local'/nome
    if not caminho.exists(): pytest.skip('PDF local ausente')
    imagem = carregar_imagem(caminho)
    posicoes = correcao_visual.localizar_alternativas(imagem)
    assert len(posicoes) == 50
    assert posicoes['1']['A']['x'] < posicoes['26']['A']['x']
    assert posicoes['1']['A']['y'] < posicoes['25']['A']['y']
    for linha in posicoes.values():
        for caixa in linha.values():
            assert 0 <= caixa['x'] < caixa['x']+caixa['largura'] <= imagem.shape[1]
            assert 0 <= caixa['y'] < caixa['y']+caixa['altura'] <= imagem.shape[0]


def test_falha_de_geometria_nao_inventa_posicoes(monkeypatch):
    monkeypatch.setattr(correcao_visual, 'localizar_alternativas', lambda _: (_ for _ in ()).throw(ErroLeitura('Grade ausente')))
    visual = correcao_visual.preparar_visualizacao(imagem_mista())
    assert visual['imagem'] is None and visual['posicoes'] == {}


def test_endpoint_visual_e_revisao_manual():
    import json
    http = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    resposta = http.post('/api/correcoes/processar', files={'arquivo': ('cartao.png', cv2.imencode('.png', imagem_mista())[1].tobytes())},
                         data={'gabarito': json.dumps(OFICIAL), 'visual': 'true'})
    assert resposta.status_code == 200
    payload = resposta.json()
    assert payload['resultado']['resumo']['acertos'] == 1
    assert payload['marcacoes']['2']['estado'] == 'incorreta'
    payload['respostas']['2'] = {'resposta': 'A', 'estado': 'marcada', 'alternativas': ['A']}
    revisao = http.post('/api/correcoes/recalcular', json={'respostas': payload['respostas'], 'gabarito': OFICIAL})
    assert revisao.status_code == 200
    assert revisao.json()['resultado']['resumo']['acertos'] == 2
    assert revisao.json()['marcacoes']['2']['estado'] == 'correta'
    assert http.post('/api/correcoes/recalcular', json={'respostas': {}, 'gabarito': OFICIAL}).status_code == 422
