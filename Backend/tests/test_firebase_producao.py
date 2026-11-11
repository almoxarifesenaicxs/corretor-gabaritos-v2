"""Configuração Firebase sem credenciais ou conexões externas."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from google.cloud.firestore_v1 import AsyncClient
from app import autenticacao


@pytest.mark.parametrize("projeto_existente", ["projeto-teste", "outro-projeto"])
def test_app_auth_nao_reutiliza_outro_projeto(monkeypatch, projeto_existente):
    app = SimpleNamespace(project_id=projeto_existente)
    monkeypatch.setattr(autenticacao.firebase_admin, "get_app", lambda nome: app)
    autenticacao._app_auth.cache_clear()
    try:
        if projeto_existente == "projeto-teste":
            assert autenticacao._app_auth("projeto-teste") is app
        else:
            with pytest.raises(ValueError, match="outro projeto"):
                autenticacao._app_auth("projeto-teste")
    finally:
        autenticacao._app_auth.cache_clear()


def test_falha_configuracao_nao_e_token_invalido(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "projeto-teste")
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    monkeypatch.setattr(autenticacao, "_app_auth", Mock(side_effect=ValueError("detalhe-privado")))
    verificar = Mock()
    monkeypatch.setattr(autenticacao.auth, "verify_id_token", verificar)
    with pytest.raises(HTTPException) as erro:
        autenticacao.verificar_token("token-simulado")
    assert erro.value.status_code == 503
    assert "detalhe-privado" not in erro.value.detail
    verificar.assert_not_called()


def test_cliente_assincrono_real_bloqueado(monkeypatch):
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "projeto-teste")
    with pytest.raises(ValueError, match="demo"):
        AsyncClient(project="projeto-teste")


def test_adc_e_verificacao_real_bloqueados():
    import google.auth
    with pytest.raises(RuntimeError, match="bloqueado"):
        google.auth.default()
    with pytest.raises(RuntimeError, match="bloqueado"):
        autenticacao.auth.verify_id_token("token-simulado")
