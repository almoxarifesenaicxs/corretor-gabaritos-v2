"""Smoke test de build sem importar a API, abrir Firebase ou baixar modelos."""
from pathlib import Path
import sys


def verificar():
    esperado = (Path(__file__).resolve().parents[1] / ".python-version").read_text().strip()
    atual = ".".join(map(str, sys.version_info[:3]))
    if atual != esperado:
        raise RuntimeError(f"Python esperado: {esperado}; encontrado: {atual}.")
    import cv2
    import numpy as np
    import onnxruntime
    import pymupdf
    import fastapi
    from app.services.nome_aluno import _motor

    imagem = np.full((100, 800, 3), 255, dtype=np.uint8)
    cv2.putText(imagem, "Ana Silva", (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 2)
    png = cv2.imencode(".png", imagem)[1]
    assert cv2.imdecode(png, cv2.IMREAD_COLOR).shape == imagem.shape
    with pymupdf.open() as documento:
        documento.new_page(width=100, height=100)
        assert documento[0].get_pixmap().width == 100
    if "CPUExecutionProvider" not in onnxruntime.get_available_providers():
        raise RuntimeError("ONNX Runtime sem provedor CPU.")
    _motor()(imagem)  # Falha se modelos locais ausentes/corrompidos ou runtime incompatível.
    return {"python": atual, "fastapi": fastapi.__version__, "opencv": cv2.__version__,
            "numpy": np.__version__, "onnxruntime": onnxruntime.__version__, "ocr": "ok"}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    print(verificar())
