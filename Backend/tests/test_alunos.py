from copy import deepcopy
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from fastapi.encoders import jsonable_encoder
import pytest

from app.main import app
from app.routes.interface import obter_persistencia
from app.routes import interface
from app.services.persistencia import RegistroExistente
from test_persistencia import banco, resultado
from suporte_estabilizacao import entrada_segura


def test_alunos_cadastro_ordenacao_busca_e_duplicatas(banco):
    repo, dados = banco
    zelia = repo.cadastrar_aluno("Zélia Santos")
    ana = repo.cadastrar_aluno("  Ana   Silva ")
    alvaro = repo.cadastrar_aluno("Álvaro Souza")
    assert [a['nome'] for a in repo.listar_alunos()] == ['Álvaro Souza', 'Ana Silva', 'Zélia Santos']
    assert repo.listar_alunos('zelia') == [zelia]
    assert repo.listar_alunos('sil') == [ana]
    assert repo.consultar_aluno(alvaro['id']) == alvaro
    with pytest.raises(RegistroExistente):
        repo.cadastrar_aluno('ana SILVA')
    assert len(dados) == 3
    correspondencias = repo.correspondencias_aluno('Ana Silva')
    assert correspondencias['exato']['id'] == ana['id']
    repo.cadastrar_aluno('Anna Silva')
    correspondencias = repo.correspondencias_aluno('Ana Silva')
    assert [a['nome'] for a in correspondencias['semelhantes']] == ['Anna Silva']
    assert correspondencias['exato']['id'] == ana['id']


@pytest.mark.parametrize('nome', ['', ' ', '12345', 'A'*201, None])
def test_nome_invalido(banco, nome):
    with pytest.raises(ValueError):
        banco[0].cadastrar_aluno(nome)


def test_associacao_historico_e_legados_sem_migracao(banco):
    repo, dados = banco
    prova = repo.criar_prova('Avaliação 1')
    aluno = repo.cadastrar_aluno('Ana Silva')
    outra = repo.cadastrar_aluno('Anna Silva')
    vinculada = repo.salvar_correcao(prova['id'], 'ANA SILVA', resultado(), aluno_id=aluno['id'])
    antiga = repo.salvar_correcao(prova['id'], 'Ana Silva', resultado(True), permitir_provisorio=True)
    repo.salvar_correcao(prova['id'], outra['nome'], resultado(), aluno_id=outra['id'])
    antes = deepcopy(dados)
    historico = repo.historico_aluno(aluno['id'])
    assert [c['id'] for c in historico['correcoes']] == [vinculada['id']]
    assert [c['id'] for c in historico['legadas_por_nome']] == [antiga['id']]
    assert historico['correcoes'][0]['avaliacao'] == 'Avaliação 1'
    assert 'aluno_id' not in repo.consultar_correcao(antiga['id'])
    assert dados == antes
    with pytest.raises(ValueError, match='não corresponde'):
        repo.salvar_correcao(prova['id'], 'Outro Nome', resultado(), aluno_id=aluno['id'])
    with pytest.raises(ValueError, match='inexistente'):
        repo.salvar_correcao(prova['id'], aluno['nome'], resultado(), aluno_id='ausente')


def test_rotas_alunos_com_banco_simulado(banco):
    repo, _ = banco
    app.dependency_overrides[obter_persistencia] = lambda: repo
    try:
        http = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
        prova = repo.criar_avaliacao('Teste', {str(i): 'A' for i in range(1,51)})
        entrada = entrada_segura(prova['id'], confirmado=False)
        assert http.post('/api/correcoes/salvar',json=entrada).status_code == 422
        assert repo.listar_alunos() == []
        entrada['confirmado'] = True
        created = http.post('/api/correcoes/salvar', json=entrada)
        assert created.status_code == 201
        aluno = repo.consultar_aluno(created.json()['aluno_id'])
        assert http.post('/api/alunos', json={'nome':'Ana Silva','confirmado':True}).status_code == 405
        assert http.get('/api/alunos?busca=ana').json() == [jsonable_encoder(aluno)]
        assert http.get('/api/alunos/correspondencias?nome=Ana%20Silva').json()['exato'] == jsonable_encoder(aluno)
        assert len(http.get(f'/api/alunos/{aluno["id"]}/correcoes').json()['correcoes']) == 1
        assert http.get('/api/alunos/ausente/correcoes').status_code == 404
        prova = repo.criar_avaliacao('Teste', {str(i): 'A' for i in range(1,51)})
        saved = http.post('/api/correcoes/salvar', json=entrada_segura(prova['id'], aluno=aluno['nome'], aluno_id=aluno['id']))
        assert saved.status_code == 201
        assert saved.json()['aluno_id'] == aluno['id']
    finally:
        app.dependency_overrides.clear()


def test_rota_alunos_preserva_bloqueio_real_remoto(monkeypatch):
    monkeypatch.setenv('FIRESTORE_MODO','real')
    monkeypatch.setenv('FIREBASE_PROJECT_ID','projeto-apenas-simulado')
    monkeypatch.delenv('FIRESTORE_EMULATOR_HOST',raising=False)
    abrir = MagicMock()
    monkeypatch.setattr(interface,'conectar_firestore',abrir)
    http = TestClient(app,base_url='http://127.0.0.1:8000',client=('192.168.1.99',12345))
    assert http.get('/api/alunos').status_code == 403
    assert http.post('/api/correcoes/salvar',json={'prova_id':'prova','aluno':'Ana Silva','resultado':resultado(),'confirmado':True}).status_code == 403
    abrir.assert_not_called()
