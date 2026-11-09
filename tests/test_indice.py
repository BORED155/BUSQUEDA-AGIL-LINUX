import pytest

from buscadorapp.indice import Buscador, Config, indexar, interpretar, normalizar


def _crear(arbol, tmp_path, **kw):
    c = Config(carpetas=[str(arbol)], excluir=[str(arbol / "Excluida")], **kw)
    db = tmp_path / "i.db"
    n = indexar(c, db)
    return Buscador(db), n


def nombres(b, texto, cat="todo", **kw):
    return [r.nombre for r in b.buscar(texto, cat, **kw)[0]]


def test_normalizar():
    assert normalizar("Canción ÑANDÚ.PDF") == "cancion nandu.pdf"


def test_busquedas(arbol, tmp_path):
    b, n = _crear(arbol, tmp_path)
    assert n == 16   # 9 archivos + 7 carpetas (sin ocultos ni la excluida)
    assert nombres(b, "factura") == ["Factura Enero 2026.pdf", "factura febrero.PDF", "Facturas"]
    assert nombres(b, "factura enero") == ["Factura Enero 2026.pdf"]          # todas las palabras
    assert nombres(b, "cancion") == ["canción.mp3"]                          # sin tildes
    assert nombres(b, "NANDU") == ["Contraseña y Ñandú.txt"]
    assert nombres(b, '"estado de cuenta"') == ["Estado de cuenta marzo.xlsx"]
    assert nombres(b, "*.pdf") == ["Factura Enero 2026.pdf", "factura febrero.PDF"]
    assert nombres(b, "foto??.jpg") == ["foto01.jpg", "foto02.jpg"]
    assert nombres(b, "ext:xlsx,mp3") == ["canción.mp3", "Estado de cuenta marzo.xlsx"]
    assert nombres(b, "sri/2026") == ["anexo 2026.xml"]                       # busca en la carpeta
    assert nombres(b, "fo", "imagenes") == ["foto01.jpg", "foto02.jpg", "fotografia larga.png"]
    assert nombres(b, "", "carpetas") == ["Documentos", "Facturas", "Imágenes", "Música", "Proyectos", "sri", "vacia"]
    assert nombres(b, "50%") == []                                           # % no es comodín
    assert nombres(b, "secreto") == [] and nombres(b, "no_aparece") == []    # ocultos y excluidas


def test_orden_y_limite(arbol, tmp_path):
    b, _ = _crear(arbol, tmp_path)
    assert nombres(b, "foto", orden="tamano", descendente=True) == ["foto02.jpg", "foto01.jpg", "fotografia larga.png"]
    filas, total = b.buscar("", limite=3)
    assert len(filas) == 3 and total == 16


def test_ocultos_y_reindexar(arbol, tmp_path):
    b, _ = _crear(arbol, tmp_path)
    (arbol / "nuevo informe.docx").write_bytes(b"x")
    assert nombres(b, "informe") == []
    indexar(Config(carpetas=[str(arbol)], ocultos=True), tmp_path / "i.db")   # reemplaza el índice
    assert nombres(b, "informe") == ["nuevo informe.docx"]                    # se abre el índice nuevo solo
    assert nombres(b, "secreto") == ["secreto.pdf"]


def test_interpretar():
    cond, ext = interpretar('ext:PDF,.docx "a b" x*')
    assert ext == ["pdf", "docx"] and cond == [("nombre", "%a b%"), ("nombre", "x%")]


def test_sin_indice(tmp_path):
    assert Buscador(tmp_path / "no.db").buscar("x") == ([], 0)


def test_quitar_del_indice(arbol, tmp_path):
    b, n = _crear(arbol, tmp_path)
    assert b.quitar([str(arbol / "Imágenes" / "foto01.jpg")]) == 1
    assert nombres(b, "foto") == ["foto02.jpg", "fotografia larga.png"]
    assert nombres(b, "fotografia") == ["fotografia larga.png"]       # la búsqueda rápida sigue bien
    # una carpeta se lleva todo lo que tiene adentro
    assert b.quitar([str(arbol / "Documentos")]) == 6   # Documentos, Facturas, 2 facturas, estado, contraseña
    assert nombres(b, "factura") == [] and nombres(b, "estado") == []
    assert b.info()[0] == n - 7


def _indice_con(tmp_path, nombres):
    base = tmp_path / "datos"
    base.mkdir()
    for n in nombres:
        (base / n).write_text("x")
    destino = tmp_path / "i.db"
    indexar(Config(carpetas=[str(base)], excluir=[]), destino)
    return Buscador(destino)


def _nombres(b, texto):
    return sorted(r.nombre for r in b.buscar(texto)[0])


def test_busqueda_usa_trigramas_y_respeta_guion_bajo_literal(tmp_path):
    b = _indice_con(tmp_path, ["mi_archivo.txt", "mixarchivo.txt", "a_b.txt", "axb.txt", "100%listo.txt", "100xlisto.txt",
                               "foto12.jpg", "foto123.jpg"])
    assert _nombres(b, "mi_archivo") == ["mi_archivo.txt"]
    assert _nombres(b, "a_b") == ["a_b.txt"]
    assert _nombres(b, "100%listo") == ["100%listo.txt"]
    assert _nombres(b, "foto??.jpg") == ["foto12.jpg"]
    assert _nombres(b, "archivo mi_") == ["mi_archivo.txt"]
    assert _nombres(b, "ax") == ["axb.txt"]
    plan = " ".join(r[3] for r in b._conexion().execute(
        "EXPLAIN QUERY PLAN SELECT rowid FROM nombres n WHERE n.clave LIKE ?", ("%archivo%",)))
    assert "VIRTUAL TABLE INDEX 0:L" in plan


def test_normalizar_ascii_y_con_tildes():
    assert normalizar("Factura.PDF") == "factura.pdf"
    assert normalizar("Canción Ñandú") == "cancion nandu"
