"""Capacidades anônimas para acesso isolado; não identificam pessoas."""

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import re
import secrets
import time


PRAZO_SESSAO = 30 * 24 * 60 * 60
_TOKEN = re.compile(r"^([A-Za-z0-9_-]{32})\.([0-9]{10})\.([A-Za-z0-9_-]{43})$")
_COLECOES = frozenset({"alunos", "provas", "gabaritos", "correcoes", "operacoes", "nomes_alunos"})


def _assinar(chave: bytes, texto: str) -> str:
    return urlsafe_b64encode(hmac.new(chave, texto.encode("ascii"), sha256).digest()).rstrip(b"=").decode("ascii")


def criar_token(chave: bytes, *, agora: int | None = None) -> str:
    momento = int(time.time()) if agora is None else agora
    sessao = secrets.token_urlsafe(24)
    cabecalho = f"{sessao}.{momento + PRAZO_SESSAO}"
    return f"{cabecalho}.{_assinar(chave, cabecalho)}"


def identificar_token(chave: bytes, token: str, *, agora: int | None = None) -> str | None:
    if not isinstance(token, str) or len(token) > 100:
        return None
    partes = _TOKEN.fullmatch(token)
    if not partes:
        return None
    sessao, prazo, assinatura = partes.groups()
    momento = int(time.time()) if agora is None else agora
    if int(prazo) < momento or int(prazo) > momento + PRAZO_SESSAO:
        return None
    if not hmac.compare_digest(assinatura, _assinar(chave, f"{sessao}.{prazo}")):
        return None
    return sessao


def registrar_sessao(cliente, token: str) -> None:
    """Registra a expiração para permitir limpeza recursiva posterior."""
    sessao, prazo, _ = token.split(".")
    cliente.collection("sessoes_publicas").document(sessao).create({
        "expires_at": datetime.fromtimestamp(int(prazo), timezone.utc),
    })


@dataclass(frozen=True)
class FirestoreDaSessao:
    """Restringe todas as coleções de Persistencia à subárvore da sessão."""

    cliente: object
    sessao: str
    legacy_scan: bool = False

    @property
    def project(self):
        # Também separa caches legados que usam o projeto como chave.
        return f"{self.cliente.project}:sessao:{self.sessao}"

    def collection(self, nome):
        if nome not in _COLECOES:
            raise ValueError("Coleção não autorizada no espaço público.")
        return self.cliente.collection("sessoes_publicas").document(self.sessao).collection(nome)

    def transaction(self, **kwargs):
        return self.cliente.transaction(**kwargs)

    def batch(self):
        return self.cliente.batch()
