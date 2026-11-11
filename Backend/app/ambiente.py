"""Configuração explícita, validada antes de aceitar tráfego de produção."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import os
import re


@dataclass(frozen=True)
class Ambiente:
    modo: str
    hosts: tuple[str, ...] = ()
    origens: tuple[str, ...] = ()
    chave_integridade: bytes | None = None


def carregar_ambiente(origens):
    modo = os.environ.get("APP_AMBIENTE", "local").strip().lower()
    if modo not in {"local", "homologacao", "producao"}:
        raise ValueError("APP_AMBIENTE deve ser local, homologacao ou producao.")
    if modo == "local":
        return Ambiente(modo)
    if modo == "homologacao":
        hosts = tuple(host.strip().lower() for host in os.environ.get("ALLOWED_HOSTS", "").split(","))
        if any(len(host) > 253 or any(not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in host.split(".")) for host in hosts):
            raise ValueError("Homologação exige ALLOWED_HOSTS com hosts exatos, sem portas ou curingas.")
        if os.environ.get("SERVIR_FRONTEND", "false").strip().lower() != "false":
            raise ValueError("Homologação exige SERVIR_FRONTEND=false.")
        if os.environ.get("FORWARDED_ALLOW_IPS", "").strip() == "*":
            raise ValueError("Confiança irrestrita em proxies não é permitida.")
        # Não carregar credenciais ou serviços Firebase neste modo.
        return Ambiente(modo, hosts)

    projeto = os.environ.get("FIREBASE_PROJECT_ID", "")
    if not projeto or projeto != projeto.strip() or projeto.startswith("demo-"):
        raise ValueError("Produção exige FIREBASE_PROJECT_ID real e explícito.")
    if os.environ.get("FIRESTORE_MODO") != "real":
        raise ValueError("Produção exige FIRESTORE_MODO=real.")
    if os.environ.get("FIRESTORE_EMULATOR_HOST") or os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"):
        raise ValueError("Emuladores não são permitidos em produção.")
    uids = [uid.strip() for uid in os.environ.get("ADMIN_UIDS", "").split(",")]
    if not uids or any(not uid or "*" in uid or len(uid) > 128 for uid in uids):
        raise ValueError("Produção exige ADMIN_UIDS explícitos, sem curingas ou itens vazios.")
    if not origens or any(urlsplit(origem).scheme != "https" for origem in origens):
        raise ValueError("Produção exige CORS_ORIGINS explícitas em HTTPS.")
    hosts = tuple(host.strip().lower() for host in os.environ.get("ALLOWED_HOSTS", "").split(","))
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
           or ".." in host for host in hosts):
        raise ValueError("Produção exige ALLOWED_HOSTS com nomes exatos, sem portas ou curingas.")
    segredo = os.environ.get("INTEGRIDADE_CHAVE", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", segredo) or len(set(segredo.lower())) < 8:
        raise ValueError("Produção exige INTEGRIDADE_CHAVE aleatória de 32 bytes em hexadecimal.")
    if os.environ.get("SERVIR_FRONTEND", "false").strip().lower() != "false":
        raise ValueError("Produção exige SERVIR_FRONTEND=false; a interface deve ser hospedada separadamente.")
    caminho = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not caminho or not Path(caminho).is_file():
        raise ValueError("Produção exige arquivo privado de credenciais disponível no backend.")
    # A configuração de processo documentada ignora encaminhamento. Não permitir
    # a variável que normalmente habilita confiança irrestrita no Uvicorn.
    if os.environ.get("FORWARDED_ALLOW_IPS", "").strip() == "*":
        raise ValueError("Confiança irrestrita em proxies não é permitida.")
    from app.autenticacao import _app_auth
    try:
        _app_auth(projeto).credential.get_credential()
    except Exception:
        raise ValueError("Credenciais de autenticação indisponíveis ou inválidas.") from None
    return Ambiente(modo, hosts, tuple(origens), bytes.fromhex(segredo))
