from copy import deepcopy
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from google.api_core.exceptions import AlreadyExists, PermissionDenied
import pytest

from app.main import app
from app.routes.interface import obter_persistencia
from app.services.persistencia import AlunosAmbiguos, ErroPersistencia
from test_persistencia import banco, resultado


def salvar(repo, prova, nome='Ana Silva', **kwargs):
    return repo.salvar_correcao(prova['id'], nome, resultado(), vincular_aluno=True, **kwargs)


def test_cadastro_apenas_no_salvamento_e_reutilizacao_normalizada(banco):
    repo, dados = banco
    prova = repo.criar_prova('Avaliação')
    assert repo.correspondencias_aluno('Ana Silva')['exatos'] == []
    assert repo.listar_alunos() == []
    primeira = salvar(repo, prova)
    segunda = salvar(repo, prova, '  ANA   SILVA ')
    assert primeira['aluno_id'] == segunda['aluno_id']
    assert len(repo.listar_alunos()) == 1
    historico = repo.historico_aluno(primeira['aluno_id'])
    assert {c['id'] for c in historico['correcoes']} == {primeira['id'],segunda['id']}
    assert primeira['resultado'] == resultado()


def test_concorrencia_reconsulta_id_criado_por_outro_salvamento(banco):
    repo, dados = banco
    prova = repo.criar_prova('Avaliação')
    criar_lote = repo.cliente.batch.side_effect
    chamadas = []
    def lote_concorrente():
        lote = criar_lote()
        commit = lote.commit.side_effect
        def concluir():
            chamadas.append(1)
            if len(chamadas) == 1:
                aluno = repo._dados_aluno('Ana Silva')
                dados['alunos',aluno['id']] = aluno
                raise AlreadyExists('Outro processo criou o mesmo aluno')
            commit()
        lote.commit.side_effect = concluir
        return lote
    repo.cliente.batch.side_effect = lote_concorrente
    correcao = salvar(repo, prova)
    assert len(chamadas) == 2
    assert len(repo.listar_alunos()) == 1
    assert correcao['aluno_id'] == repo.listar_alunos()[0]['id']
    assert len(repo.listar_correcoes(prova['id'])) == 1


def test_falha_no_lote_nao_deixa_aluno_ou_correcao_parcial(banco):
    repo, dados = banco
    prova = repo.criar_prova('Avaliação')
    antes = deepcopy(dados)
    lote = MagicMock()
    lote.commit.side_effect = PermissionDenied('Falha simulada')
    repo.cliente.batch.side_effect = lambda: lote
    with pytest.raises(ErroPersistencia): salvar(repo, prova)
    assert dados == antes


def test_semelhante_nao_e_reutilizado(banco):
    repo, _ = banco
    prova = repo.criar_prova('Avaliação')
    anna = repo.cadastrar_aluno('Anna Silva')
    correcao = salvar(repo, prova, 'Ana Silva')
    assert correcao['aluno_id'] != anna['id']
    assert repo.historico_aluno(anna['id'])['correcoes'] == []


def test_homonimo_explicitamente_confirmado_e_escolha_ambigua(banco):
    repo, dados = banco
    prova = repo.criar_prova('Avaliação')
    primeira = salvar(repo, prova)
    segunda = salvar(repo, prova, novo_homonimo=True)
    assert primeira['aluno_id'] != segunda['aluno_id']
    antes = deepcopy(dados)
    with pytest.raises(AlunosAmbiguos): salvar(repo, prova)
    assert dados == antes
    escolhida = salvar(repo, prova, aluno_id=segunda['aluno_id'])
    assert escolhida['aluno_id'] == segunda['aluno_id']
    assert len(repo.historico_aluno(primeira['aluno_id'])['correcoes']) == 1
    assert len(repo.historico_aluno(segunda['aluno_id'])['correcoes']) == 2


def test_confirmacao_http_e_ambiguidade_sem_gravacao(banco):
    repo, dados = banco
    prova = repo.criar_prova('Avaliação')
    app.dependency_overrides[obter_persistencia] = lambda: repo
    try:
        http = TestClient(app)
        body = {'prova_id':prova['id'],'aluno':'Ana Silva','resultado':resultado(),'confirmado':False}
        assert http.post('/api/correcoes/salvar',json=body).status_code == 422
        assert repo.listar_alunos() == []
        body['confirmado'] = True
        assert http.post('/api/correcoes/salvar',json=body).status_code == 201
        body['novo_homonimo'] = True
        segundo = http.post('/api/correcoes/salvar',json=body).json()
        body['novo_homonimo'] = False
        antes = deepcopy(dados)
        ambiguo = http.post('/api/correcoes/salvar',json=body)
        assert ambiguo.status_code == 409
        assert ambiguo.json()['detail']['codigo'] == 'aluno_ambiguo'
        assert len(ambiguo.json()['detail']['alunos']) == 2
        assert dados == antes
        body['aluno_id'] = segundo['aluno_id']
        assert http.post('/api/correcoes/salvar',json=body).json()['aluno_id'] == segundo['aluno_id']
    finally: app.dependency_overrides.clear()
