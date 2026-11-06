"""Arranque. Si el buscador ya está abierto, solo se trae al frente (útil con el atajo de teclado)."""

from __future__ import annotations

import getpass
import sys

from PySide6.QtCore import QEvent, QLibraryInfo, QObject, Qt, QTranslator
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu

ESTILO_MENUS = """
QMenu { background: palette(base); border: 1px solid #cfd8dc; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 7px 22px 7px 10px; border-radius: 7px; margin: 1px 0; }
QMenu::item:selected { background: #e3f2fd; color: #0d47a1; }
QMenu::item:disabled { color: #9e9e9e; }
QMenu::icon { padding-left: 8px; }
QMenu::separator { height: 1px; background: #e6eaed; margin: 5px 10px; }
"""


class MenusRedondeados(QObject):
    """Para que se vean las esquinas redondeadas, el fondo de la ventana del menú debe ser transparente."""

    def eventFilter(self, obj, evento) -> bool:
        if evento.type() == QEvent.Polish and isinstance(obj, QMenu) and not obj.property("_redondeado"):
            obj.setProperty("_redondeado", True)
            obj.setAttribute(Qt.WA_TranslucentBackground)
            obj.setWindowFlags(obj.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        return False

NOMBRE_SERVIDOR = f"buscador-agil-{getpass.getuser()}"


def _ya_abierto(texto: str) -> bool:
    s = QLocalSocket()
    s.connectToServer(NOMBRE_SERVIDOR)
    if not s.waitForConnected(300):
        return False
    s.write(("mostrar\n" + texto).encode("utf-8"))
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def ejecutar(argumentos: list[str]) -> int:
    app = QApplication([sys.argv[0]] + argumentos)
    app.setOrganizationName("buscador-agil")
    app.setApplicationName("Buscador Ágil")
    app.setDesktopFileName("buscador-agil")
    texto = " ".join(a for a in argumentos if not a.startswith("-"))
    if _ya_abierto(texto):
        return 0
    traductor = QTranslator(app)
    if traductor.load("qtbase_es", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(traductor)
    app.setStyleSheet(ESTILO_MENUS)
    app._menus = MenusRedondeados(app)
    app.installEventFilter(app._menus)
    from .ventana import VentanaBuscador

    ventana = VentanaBuscador()
    QLocalServer.removeServer(NOMBRE_SERVIDOR)
    servidor = QLocalServer(app)
    servidor.listen(NOMBRE_SERVIDOR)

    def conexion():
        s = servidor.nextPendingConnection()
        if s is None:
            return

        def leer():
            datos = bytes(s.readAll()).decode("utf-8", "replace").split("\n", 1)
            ventana.mostrar()
            if len(datos) > 1 and datos[1]:
                ventana.busqueda.setText(datos[1])

        s.readyRead.connect(leer)

    servidor.newConnection.connect(conexion)
    ventana.show()
    if texto:
        ventana.busqueda.setText(texto)
    return app.exec()
