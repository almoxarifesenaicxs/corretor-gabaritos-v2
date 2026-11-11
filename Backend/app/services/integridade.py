"""Comprovante local de respostas processadas ou revisadas, sem guardar imagens."""

import hashlib
import hmac
import json
import secrets

_CHAVE = secrets.token_bytes(32)


def resumo_canonico(dados):
    return hashlib.sha256(json.dumps(dados, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def assinar_respostas(respostas, gabarito):
    return hmac.new(_CHAVE, resumo_canonico([respostas, gabarito]).encode(), hashlib.sha256).hexdigest()


def conferir_respostas(comprovante, respostas, gabarito):
    if not isinstance(comprovante, str) or not comprovante.isascii() or not hmac.compare_digest(
            comprovante, assinar_respostas(respostas, gabarito)):
        raise ValueError("Respostas alteradas ou comprovante expirado. Reconheça ou revise novamente.")
