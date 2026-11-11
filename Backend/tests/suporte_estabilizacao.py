from uuid import uuid4

from app.services.integridade import assinar_respostas
from app.services.correcao import corrigir_respostas


def entrada_segura(prova_id, *, respostas=None, oficial=None, **campos):
    oficial = oficial or {str(i): "A" for i in range(1, 51)}
    if respostas is None:
        respostas = {str(i): {"resposta": "A", "estado": "marcada", "alternativas": ["A"]}
                     for i in range(1, 51)}
    return {"prova_id": prova_id, "aluno": "Ana Silva", "respostas": respostas,
            "resultado": corrigir_respostas(respostas, oficial), "confirmado": True,
            "comprovante": assinar_respostas(respostas, oficial), "operacao_id": uuid4().hex, **campos}
