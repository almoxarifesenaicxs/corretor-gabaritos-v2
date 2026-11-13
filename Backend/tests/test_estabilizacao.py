"""Regressões de integridade e limites; nenhum acesso ao Firebase real."""

import asyncio
from copy import deepcopy
from io import BytesIO
from uuid import uuid4
from unittest.mock import MagicMock

import cv2
import numpy as np
import pymupdf
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from google.api_core.exceptions import PermissionDenied

from app.main import app
from app.routes.interface import obter_persistencia
from app.services import limites_imagem, reconhecimento, integridade
from app.services.persistencia import AlunosAmbiguos, ErroPersistencia, RegistroExistente
from app import seguranca
from test_persistencia import banco
from suporte_estabilizacao import entrada_segura


@pytest.fixture
def http(banco):
    repo, _ = banco
    def obter():
        try:
            yield repo
        except RegistroExistente:
            from fastapi import HTTPException
            raise HTTPException(409, "Operação em conflito")
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(422, "Dados incompatíveis")
    app.dependency_overrides[obter_persistencia] = obter
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345)) as client:
        yield client
    app.dependency_overrides.clear()


def salvar(repo, body):
    return repo.salvar_correcao(body["prova_id"], body["aluno"], body["resultado"],
        respostas=body["respostas"], comprovante=body["comprovante"], operacao_id=body["operacao_id"],
        novo_homonimo=body.get("novo_homonimo", False), aluno_id=body.get("aluno_id"),
        permitir_provisorio=body.get("permitir_provisorio", False), vincular_aluno=True)


@pytest.mark.parametrize("caso", ["999", "percentual", "situacao", "resposta", "comprovante", "gabarito", "estrutura"])
def test_rejeita_adulteracao_sem_qualquer_escrita(banco, http, caso):
    repo, dados = banco
    oficial = {str(i): "A" for i in range(1, 51)}
    prova = repo.criar_avaliacao("Prova oficial", oficial)
    body = entrada_segura(prova["id"])
    if caso == "999": body["resultado"]["resumo"]["pontuacao"] = 999
    if caso == "percentual": body["resultado"]["resumo"]["percentual_acertos"] = 30
    if caso == "situacao": body["resultado"]["provisorio"] = True
    if caso == "resposta":
        body["respostas"]["1"] = {"resposta": "B", "estado": "marcada", "alternativas": ["B"]}
        from app.services.correcao import corrigir_respostas
        body["resultado"] = corrigir_respostas(body["respostas"], oficial)
    if caso == "comprovante": body["comprovante"] = "0" * 64
    if caso == "gabarito":
        body = entrada_segura(prova["id"], oficial={str(i): "B" for i in range(1, 51)})
    if caso == "estrutura": body["respostas"]["1"]["resposta"] = "F"
    antes = deepcopy(dados)
    assert http.post("/api/correcoes/salvar", json=body).status_code == 422
    assert dados == antes


def test_legado_http_sem_respostas_nao_e_aceito(banco, http):
    body = entrada_segura("prova")
    del body["respostas"]
    assert http.post("/api/correcoes/salvar", json=body).status_code == 422
    assert banco[1] == {}


def test_reenvio_e_conflito_de_operacao(banco, http):
    repo, dados = banco
    prova = repo.criar_avaliacao("Oficial", {str(i): "A" for i in range(1, 51)})
    body = entrada_segura(prova["id"], novo_homonimo=True)
    primeira = http.post("/api/correcoes/salvar", json=body)
    assert primeira.status_code == 201
    antes = deepcopy(dados)
    # Mesmo após reiniciar a chave de comprovantes: operação já comprometida é recuperada.
    body["comprovante"] = "0" * 64
    segunda = http.post("/api/correcoes/salvar", json=body)
    assert segunda.status_code == 201
    assert segunda.json() == primeira.json()
    assert dados == antes
    body["aluno"] = "Outro Aluno"
    assert http.post("/api/correcoes/salvar", json=body).status_code == 409
    assert dados == antes


def test_origem_lote_integra_assinatura_idempotente_sem_imagem(banco):
    repo, dados = banco
    prova = repo.criar_avaliacao("Oficial", {str(i): "A" for i in range(1, 51)})
    body = entrada_segura(prova["id"])
    origem = {"lote_id": "a" * 32, "indice": 0, "imagem_sha256": "b" * 64}
    argumentos = dict(respostas=body["respostas"], comprovante=body["comprovante"],
                      operacao_id=body["operacao_id"], origem_lote=origem)
    primeiro = repo.salvar_correcao(body["prova_id"], body["aluno"], body["resultado"], **argumentos)
    antes = deepcopy(dados)
    segundo = repo.salvar_correcao(body["prova_id"], body["aluno"], body["resultado"], **argumentos)
    assert segundo == primeiro
    assert dados == antes
    assert primeiro["origem_lote"] == origem
    assert "imagem" not in primeiro
    with pytest.raises(RegistroExistente):
        repo.salvar_correcao(body["prova_id"], body["aluno"], body["resultado"],
                            **{**argumentos, "origem_lote": {**origem, "indice": 1}})


def test_avaliacao_idempotente_e_inseparavel_do_gabarito(banco, http):
    body = {"titulo": "Oficial", "alternativas": {str(i): "A" for i in range(1, 51)},
            "confirmado": True, "operacao_id": uuid4().hex}
    primeira = http.post("/api/avaliacoes", json=body)
    assert primeira.status_code == 201
    antes = deepcopy(banco[1])
    assert http.post("/api/avaliacoes", json=body).json() == primeira.json()
    assert banco[1] == antes
    body["alternativas"]["1"] = "B"
    assert http.post("/api/avaliacoes", json=body).status_code == 409
    assert banco[1] == antes


def test_reutiliza_id_antigo_sem_migrar_e_preserva_pendencias(banco):
    repo, dados = banco
    prova = repo.criar_avaliacao("Oficial", {str(i): "A" for i in range(1, 51)})
    antigo = {"id": "id-antigo", "nome": "Ana Silva"}
    dados["alunos", "id-antigo"] = deepcopy(antigo)
    body = entrada_segura(prova["id"])
    body["respostas"]["1"] = {"resposta": None, "estado": "branco", "alternativas": []}
    body["respostas"]["2"] = {"resposta": None, "estado": "multipla", "alternativas": ["A", "C"]}
    body["respostas"]["26"] = {"resposta": None, "estado": "duvidosa", "alternativas": ["B"]}
    body = entrada_segura(prova["id"], respostas=body["respostas"], permitir_provisorio=True)
    registro = salvar(repo, body)
    assert registro["aluno_id"] == "id-antigo"
    assert registro["situacao"] == "provisoria"
    assert registro["resultado"]["resumo"]["pontuacao"] == 47
    assert registro["resultado"]["questoes_pendentes"] == ["2", "26"]
    assert dados["alunos", "id-antigo"] == antigo
    assert registro["respostas"] == body["respostas"]


def test_corrida_de_homonimo_rele_nome_e_exige_escolha(banco):
    repo, dados = banco
    prova = repo.criar_avaliacao("Oficial", {str(i): "A" for i in range(1, 51)})
    salvar(repo, entrada_segura(prova["id"]))
    fabricar = repo.cliente.transaction.side_effect
    criado = []
    def fabrica(**kwargs):
        tx = fabricar(**kwargs)
        commit = tx.commit
        def concorrente():
            if not criado:
                criado.append(True)
                salvar(repo, entrada_segura(prova["id"], novo_homonimo=True))
            commit()
        tx.commit = concorrente
        return tx
    repo.cliente.transaction.side_effect = fabrica
    body = entrada_segura(prova["id"])
    with pytest.raises(AlunosAmbiguos): salvar(repo, body)
    assert len(repo.listar_alunos()) == 2
    assert len(repo.listar_correcoes(prova["id"])) == 2
    assert ("operacoes", "correcao-" + body["operacao_id"]) not in dados


def test_transacao_falha_sem_aluno_correcao_ou_operacao_parciais(banco):
    repo, dados = banco
    prova = repo.criar_avaliacao("Oficial", {str(i): "A" for i in range(1, 51)})
    antes = deepcopy(dados)
    fabricar = repo.cliente.transaction.side_effect
    def fabrica(**kwargs):
        tx = fabricar(**kwargs)
        tx.commit = MagicMock(side_effect=PermissionDenied("privado"))
        return tx
    repo.cliente.transaction.side_effect = fabrica
    with pytest.raises(ErroPersistencia): salvar(repo, entrada_segura(prova["id"]))
    assert dados == antes


def test_corrida_da_mesma_operacao_retorna_um_unico_registro(banco):
    repo, dados = banco
    prova = repo.criar_avaliacao("Oficial", {str(i): "A" for i in range(1, 51)})
    body = entrada_segura(prova["id"])
    fabricar = repo.cliente.transaction.side_effect
    concluida = []
    def fabrica(**kwargs):
        tx = fabricar(**kwargs)
        commit = tx.commit
        def concorrente():
            if not concluida:
                concluida.append(True)
                concluida.append(salvar(repo, body))
            commit()
        tx.commit = concorrente
        return tx
    repo.cliente.transaction.side_effect = fabrica
    assert salvar(repo, body) == concluida[1]
    assert len(repo.listar_correcoes(prova["id"])) == 1
    assert len(repo.listar_alunos()) == 1


def test_revisao_manual_emite_comprovante_e_salva_nota_recalculada(banco, http):
    repo, _ = banco
    oficial = {str(i): "A" for i in range(1, 51)}
    prova = repo.criar_avaliacao("Oficial", oficial)
    body = entrada_segura(prova["id"])
    original = body["comprovante"]
    body["respostas"]["1"] = {"resposta": "B", "estado": "marcada", "alternativas": ["B"]}
    revisao = http.post("/api/correcoes/recalcular", json={"respostas": body["respostas"], "gabarito": oficial})
    assert revisao.status_code == 200
    body.update(resultado=revisao.json()["resultado"], comprovante=revisao.json()["comprovante"])
    assert body["comprovante"] != original
    salvo = http.post("/api/correcoes/salvar", json=body)
    assert salvo.status_code == 201
    assert salvo.json()["resultado"]["resumo"]["pontuacao"] == 49


@pytest.mark.parametrize("path", [".qa/cartao.png", ".qa/package.json", "tests/browser.test.cjs",
                                  "js/script.js", ".env", "requirements.txt", "css/privado.css"])
def test_arquivos_internos_bloqueados(http, path):
    assert http.get("/interface/" + path).status_code == 404


@pytest.mark.parametrize("peer,host,headers", [
    ("192.168.1.20", "127.0.0.1", {}), ("127.0.0.1", "externo.example", {}),
    ("127.0.0.1", "localhost", {"Origin": "https://externo.example"}),
    ("127.0.0.1", "localhost", {"X-Forwarded-For": "127.0.0.1"}),
])
def test_bloqueio_local_global_antes_de_qualquer_servico(monkeypatch, peer, host, headers):
    from app.routes import interface
    abrir = MagicMock()
    monkeypatch.setattr(interface, "conectar_firestore", abrir)
    http = TestClient(app, base_url="http://" + host, client=(peer, 50000))
    assert http.get("/api/avaliacoes", headers=headers).status_code == 403
    assert http.post("/api/capturas/analisar", content=b"abc", headers=headers).status_code == 403
    assert http.get("/interface/", headers=headers).status_code == 403
    abrir.assert_not_called()


def test_orcamento_http_antes_do_parser_sem_content_length(monkeypatch):
    monkeypatch.setattr(seguranca, "LIMITE_CORPO_JSON", 8)
    chamadas = []
    async def destino(*args): chamadas.append(1)
    middleware = seguranca.ProtecaoLocal(destino)
    eventos = iter([{"type": "http.request", "body": b"12345", "more_body": True},
                    {"type": "http.request", "body": b"6789", "more_body": False}])
    enviados = []
    async def receber(): return next(eventos)
    async def enviar(evento): enviados.append(evento)
    scope = {"type": "http", "client": ("127.0.0.1", 50), "scheme": "http", "method": "POST",
             "path": "/api/avaliacoes", "headers": [(b"host", b"localhost")]}
    asyncio.run(middleware(scope, receber, enviar))
    assert enviados[0]["status"] == 413
    assert chamadas == []


def test_orcamentos_de_json_e_envelope_multipart(http, monkeypatch):
    monkeypatch.setattr(seguranca, "LIMITE_CORPO_JSON", 20)
    monkeypatch.setattr(seguranca, "LIMITE_CORPO_UPLOAD", 80)
    assert http.post("/api/avaliacoes", content=b"x" * 21).status_code == 413
    assert http.post("/api/capturas/analisar", files={"arquivo": ("a.png", b"x")}).status_code == 413


@pytest.mark.parametrize("formato", ["PNG", "JPEG"])
def test_limite_de_cabecalho_antes_do_opencv(monkeypatch, tmp_path, formato):
    monkeypatch.setattr(limites_imagem, "MAX_PIXELS", 10)
    stream = BytesIO()
    Image.new("RGB", (4, 4)).save(stream, format=formato)
    caminho = tmp_path / ("a.png" if formato == "PNG" else "a.jpg")
    caminho.write_bytes(stream.getvalue())
    decoder = MagicMock()
    monkeypatch.setattr(reconhecimento.cv2, "imdecode", decoder)
    with pytest.raises(reconhecimento.ErroLeitura): reconhecimento.carregar_imagem(caminho)
    from app.services.captura import decodificar_captura
    with pytest.raises(reconhecimento.ErroLeitura): decodificar_captura(stream.getvalue())
    decoder.assert_not_called()


def test_pdf_grande_rejeitado_antes_de_renderizar(monkeypatch, tmp_path):
    caminho = tmp_path / "grande.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=4000, height=4000)
        doc.save(caminho)
    render = MagicMock()
    monkeypatch.setattr(pymupdf.Page, "get_pixmap", render)
    with pytest.raises(reconhecimento.ErroLeitura): reconhecimento.carregar_imagem(caminho)
    render.assert_not_called()


@pytest.mark.parametrize("dimensoes", [(6001, 1), (4000, 4000), (0, 50), (float("inf"), 50)])
def test_dimensoes_fora_do_orcamento(dimensoes):
    with pytest.raises(ValueError): limites_imagem.validar_dimensoes(*dimensoes)


def test_limite_de_processamentos_e_liberacao(http, monkeypatch):
    bloqueio = MagicMock()
    bloqueio.acquire.return_value = False
    monkeypatch.setattr(seguranca, "_PROCESSAMENTOS", bloqueio)
    assert http.post("/api/capturas/analisar", files={"arquivo": ("a.png", b"x")}).status_code == 503
    bloqueio.release.assert_not_called()
    bloqueio.acquire.return_value = True
    assert http.post("/api/capturas/analisar", files={"arquivo": ("a.png", b"x")}).status_code == 415
    bloqueio.release.assert_called_once()


def test_limite_de_recepcoes_nao_le_corpo(http, monkeypatch):
    bloqueio = MagicMock()
    bloqueio.acquire.return_value = False
    monkeypatch.setattr(seguranca, "_RECEPCOES", bloqueio)
    assert http.post("/api/avaliacoes", content=b"{}").status_code == 503
    bloqueio.release.assert_not_called()


def test_prazo_de_recepcao_nao_deixa_vaga_presa(http, monkeypatch):
    monkeypatch.setattr(seguranca, "PRAZO_CORPO", 0)
    bloqueio = MagicMock()
    bloqueio.acquire.return_value = True
    monkeypatch.setattr(seguranca, "_RECEPCOES", bloqueio)
    assert http.post("/api/avaliacoes", content=b"{}").status_code == 408
    bloqueio.release.assert_called_once()


def test_comprovante_expira_apos_reinicio_sem_salvar(banco, monkeypatch):
    repo, dados = banco
    prova = repo.criar_avaliacao("Oficial", {str(i): "A" for i in range(1, 51)})
    body = entrada_segura(prova["id"])
    antes = deepcopy(dados)
    monkeypatch.setattr(integridade, "_CHAVE", b"outra-chave-local")
    with pytest.raises(ValueError): salvar(repo, body)
    assert dados == antes
