import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def arbol(tmp_path, monkeypatch):
    """Carpetas y archivos de prueba (datos ficticios) y configuración/índice aislados."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "datos"))
    raiz = tmp_path / "casa"
    archivos = {
        "Documentos/Facturas/Factura Enero 2026.pdf": 1200,
        "Documentos/Facturas/factura febrero.PDF": 800,
        "Documentos/Estado de cuenta marzo.xlsx": 500,
        "Documentos/Contraseña y Ñandú.txt": 10,
        "Imágenes/foto01.jpg": 3000,
        "Imágenes/foto02.jpg": 3100,
        "Imágenes/fotografia larga.png": 50,
        "Música/canción.mp3": 9000,
        "Proyectos/sri/anexo 2026.xml": 70,
        ".oculto/secreto.pdf": 5,
        "Excluida/no_aparece.pdf": 5,
    }
    for rel, tam in archivos.items():
        p = raiz / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * tam)
    (raiz / "Proyectos" / "vacia").mkdir()
    return raiz
