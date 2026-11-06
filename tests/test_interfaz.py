import time

import pytest
from PySide6.QtWidgets import QApplication

from buscadorapp.indice import Config, indexar
from buscadorapp.ui import ventana as modulo
from buscadorapp.ui.ventana import VentanaBuscador


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_buscar_abrir_copiar_y_papelera(app, arbol, tmp_path, monkeypatch):
    config = Config(carpetas=[str(arbol)], excluir=[], minutos_actualizar=0)
    db = tmp_path / "i.db"
    indexar(config, db)
    w = VentanaBuscador(config, db)
    w.busqueda.setText("factura")
    w.buscar()
    assert [r.nombre for r in w.modelo.filas] == ["Factura Enero 2026.pdf", "factura febrero.PDF", "Facturas"]
    assert "3</b> resultado" in w.lbl_estado.text()
    # categorías
    w._cambiar_categoria("carpetas")
    assert [r.nombre for r in w.modelo.filas] == ["Facturas"]
    w._cambiar_categoria("todo")
    # copiar para pegar en Archivos
    w.tabla.selectRow(1)
    w.tabla.setFocus()
    w.copiar_archivos()
    datos = QApplication.clipboard().mimeData()
    assert datos.urls()[0].toLocalFile().endswith("factura febrero.PDF")
    # arrastrar
    md = w.modelo.mimeData([w.modelo.index(0, 0)])
    assert md.urls()[0].toLocalFile().endswith("Factura Enero 2026.pdf")
    # papelera (sin tocar la papelera real)
    borrados = []
    monkeypatch.setattr(modulo.sistema, "a_la_papelera", lambda ruta: borrados.append(ruta.name))
    monkeypatch.setattr(modulo.QMessageBox, "exec", lambda self: self.buttons()[0].click() or 0)
    w.a_la_papelera()
    assert borrados == ["factura febrero.PDF"] and len(w.modelo.filas) == 2
    # ordenar por tamaño desde la cabecera
    w.busqueda.setText("foto")
    from PySide6.QtCore import Qt
    w.modelo.sort(2, Qt.DescendingOrder)
    assert [r.nombre for r in w.modelo.filas][0] == "foto02.jpg"
    w.close()


def test_indexa_en_segundo_plano(app, arbol, tmp_path):
    config = Config(carpetas=[str(arbol)], excluir=[], minutos_actualizar=0)
    w = VentanaBuscador(config, tmp_path / "nuevo.db")       # sin índice: se crea solo
    fin = time.time() + 10
    while time.time() < fin and (w.indexando or not w.buscador.info()[0]):
        app.processEvents()
        time.sleep(0.02)
    assert w.buscador.info()[0] == 18   # 10 archivos + 8 carpetas (sin ocultos)
    w.busqueda.setText("anexo")
    w.buscar()
    assert [r.nombre for r in w.modelo.filas] == ["anexo 2026.xml"]
    w.close()


def test_atajo_de_teclado(monkeypatch):
    from buscadorapp import sistema
    estado = {"lista": "@as []"}

    def gs(*args):
        if args[:2] == ("get", sistema.ESQUEMA_ATAJOS):
            return estado["lista"]
        if args[:2] == ("set", sistema.ESQUEMA_ATAJOS):
            estado["lista"] = args[3]
            return ""
        if args[0] == "set":
            estado[args[2]] = args[3]
        if args[0] == "get":
            return f"'{estado.get(args[2], '')}'"
        return ""

    monkeypatch.setattr(sistema, "_gs", gs)
    assert sistema.atajo_actual() == ""
    estado["lista"] = "['/otro/atajo/']"
    sistema.poner_atajo("buscadorapp")
    assert "/otro/atajo/" in estado["lista"] and sistema.RUTA_ATAJO in estado["lista"]   # no borra los demás
    assert sistema.atajo_actual() == "<Primary><Alt>b" and estado["command"] == "buscadorapp"
    sistema.quitar_atajo()
    assert sistema.RUTA_ATAJO not in estado["lista"] and "/otro/atajo/" in estado["lista"]


def test_borrar_se_actualiza_al_instante(app, arbol, tmp_path, monkeypatch):
    config = Config(carpetas=[str(arbol)], excluir=[], minutos_actualizar=0)
    db = tmp_path / "i.db"
    indexar(config, db)
    w = VentanaBuscador(config, db)
    monkeypatch.setattr(modulo.QMessageBox, "exec", lambda self: self.buttons()[0].click() or 0)
    w.busqueda.setText("foto")
    w.buscar()
    assert len(w.modelo.filas) == 3
    # eliminar definitivamente desde el programa: sale de la lista y del índice en el mismo momento
    w.tabla.selectRow(0)
    w.tabla.setFocus()
    w.eliminar_definitivo()
    assert not (arbol / "Imágenes" / "foto01.jpg").exists()
    assert [r.nombre for r in w.modelo.filas] == ["foto02.jpg", "fotografia larga.png"]
    assert w.tabla.selectionModel().selectedRows()[0].row() == 0     # queda elegido el siguiente
    # borrado por fuera (en Archivos o la terminal): al buscar ya no aparece
    (arbol / "Imágenes" / "foto02.jpg").unlink()
    w.buscar()
    assert [r.nombre for r in w.modelo.filas] == ["fotografia larga.png"]
    assert "1</b> resultado" in w.lbl_estado.text()
    w.close()


def test_propiedades(app, arbol):
    from buscadorapp.ui.propiedades import DialogoPropiedades, permisos_legibles
    d = DialogoPropiedades(str(arbol / "Documentos" / "Facturas" / "Factura Enero 2026.pdf"))
    textos = " ".join(l.text() for l in d.findChildren(modulo.QLabel))
    assert "1.2 KB" in textos and "1.200 bytes" in textos and "Facturas" in textos and "PDF" in textos
    d.close()
    d = DialogoPropiedades(str(arbol / "Documentos"))
    fin = time.time() + 5
    while time.time() < fin and "calculando" in d.lbl_tamano.text().lower():
        app.processEvents()
    assert "4 archivo(s) y 1 carpeta(s)" in d.lbl_tamano.text()
    d.close()
    assert permisos_legibles(0o100644).startswith("Dueño: leer, escribir  ·  Grupo: leer")


def test_aplicaciones_y_abrir_con(app, tmp_path, monkeypatch):
    from buscadorapp import aplicaciones
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "visor.desktop").write_text("[Desktop Entry]\nType=Application\nName=Visor\nName[es]=Visor PDF\n"
                                        "Exec=visor %f\nMimeType=application/pdf;\n")
    (apps / "visor-copia.desktop").write_text("[Desktop Entry]\nType=Application\nName=Visor PDF\nExec=v %f\n"
                                              "NoDisplay=true\nMimeType=application/pdf;\n")
    (apps / "editor.desktop").write_text("[Desktop Entry]\nType=Application\nName=Editor\nExec=ed %f\n"
                                         "MimeType=text/plain;\n")
    (apps / "roto.desktop").write_text("no es un desktop")
    monkeypatch.setenv("LANG", "es_EC.UTF-8")
    monkeypatch.setattr(aplicaciones, "carpetas_aplicaciones", lambda: [apps])
    aplicaciones._cache = None
    assert [a.nombre for a in aplicaciones.para_tipo(["application/pdf"])] == ["Visor PDF"]   # sin repetidos
    lanzadas = []
    monkeypatch.setattr(aplicaciones, "abrir_con", lambda a, rutas: lanzadas.append((a.id, rutas)))
    monkeypatch.setattr(aplicaciones, "predeterminada", lambda t: "visor.desktop")
    from buscadorapp.ui.abrir_con import DialogoAbrirCon, llenar_menu
    from PySide6.QtWidgets import QMenu
    archivo = tmp_path / "x.pdf"
    archivo.write_bytes(b"%PDF-1.4")
    m = QMenu()
    llenar_menu(m, [str(archivo)], None)
    textos = [a.text() for a in m.actions()]
    assert textos[0] == "Visor PDF   (predeterminada)" and textos[-1] == "Otra aplicación…"
    m.actions()[0].trigger()
    assert lanzadas == [("visor.desktop", [str(archivo)])]
    d = DialogoAbrirCon([str(archivo)])
    d.filtro.setText("edit")
    assert d.elegida().nombre == "Editor"
    d.accept()
    assert lanzadas[-1][0] == "editor.desktop"
    aplicaciones._cache = None
