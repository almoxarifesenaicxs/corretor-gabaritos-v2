"""Integração real opcional: exige emulador local e projeto demo explícitos."""

import os
import socket
from urllib.parse import urlsplit

import pytest

from app.database.firestore import conectar_firestore, validar_emulador
from app.services.persistencia import Persistencia, RegistroExistente
from test_persistencia import resultado


def test_ciclo_completo_emulador():
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        pytest.skip("Firestore Emulator não configurado; nenhuma conexão real será aberta.")
    validar_emulador()  # Configuração insegura falha antes de abrir qualquer conexão.
    destino = urlsplit("//" + os.environ["FIRESTORE_EMULATOR_HOST"])
    try:
        with socket.create_connection((destino.hostname, destino.port), timeout=1):
            pass
    except OSError:
        pytest.fail("Firestore Emulator configurado, mas indisponível no endereço local.")

    with conectar_firestore() as cliente:
        repo = Persistencia(cliente)
        registros = []
        try:
            prova = repo.criar_prova("Integração isolada", "Documento temporário de teste")
            registros.append(("provas", prova["id"]))
            assert repo.consultar_prova(prova["id"]) == prova
            assert prova in repo.listar_provas()
            oficial = {str(i): "A" for i in range(1, 51)}
            gabarito = repo.cadastrar_gabarito(prova["id"], oficial)
            registros.append(("gabaritos", prova["id"]))
            assert repo.consultar_gabarito(prova["id"]) == gabarito
            with pytest.raises(RegistroExistente):
                repo.cadastrar_gabarito(prova["id"], oficial)
            correcao = repo.salvar_correcao(prova["id"], "Aluno de teste", resultado())
            registros.append(("correcoes", correcao["id"]))
            assert repo.consultar_correcao(correcao["id"]) == correcao
            assert repo.listar_correcoes(prova["id"]) == [correcao]
        finally:
            # Remove somente os documentos que este teste criou, nunca a base toda.
            for colecao, identificador in reversed(registros):
                cliente.collection(colecao).document(identificador).delete()
