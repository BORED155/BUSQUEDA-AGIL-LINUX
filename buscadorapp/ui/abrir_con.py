"""Menú y ventana «Abrir con…»."""

from __future__ import annotations

from PySide6.QtCore import QMimeDatabase, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QVBoxLayout)

from .. import aplicaciones


def tipo_de(ruta: str):
    return QMimeDatabase().mimeTypeForFile(ruta)


def _icono(app) -> QIcon:
    if app.icono.startswith("/"):
        return QIcon(app.icono)
    return QIcon.fromTheme(app.icono, QIcon.fromTheme("application-x-executable"))


def llenar_menu(menu: QMenu, rutas: list[str], ventana) -> None:
    """Agrega al submenú: la predeterminada, las recomendadas y «Otra aplicación…»."""
    mime = tipo_de(rutas[0])
    tipos = [mime.name()] + list(mime.aliases()) + list(mime.allAncestors())
    defecto = aplicaciones.predeterminada(mime.name())
    recomendadas = aplicaciones.para_tipo(tipos)
    recomendadas.sort(key=lambda a: a.id != defecto)
    for app in recomendadas[:15]:
        texto = app.nombre + ("   (predeterminada)" if app.id == defecto else "")
        accion = menu.addAction(_icono(app), texto, lambda a=app: aplicaciones.abrir_con(a, rutas))
        if app.id == defecto:
            f = accion.font()
            f.setBold(True)
            accion.setFont(f)
    if recomendadas:
        menu.addSeparator()
    menu.addAction("Otra aplicación…", lambda: DialogoAbrirCon(rutas, ventana).exec())


class DialogoAbrirCon(QDialog):
    def __init__(self, rutas: list[str], parent=None):
        super().__init__(parent)
        self.rutas = rutas
        self.mime = tipo_de(rutas[0])
        self.setWindowTitle("Abrir con…")
        self.resize(460, 560)
        nombre = rutas[0].rsplit("/", 1)[-1] if len(rutas) == 1 else f"{len(rutas)} archivos"
        titulo = QLabel(f"Elija la aplicación para abrir <b>{nombre}</b>")
        titulo.setWordWrap(True)
        self.filtro = QLineEdit()
        self.filtro.setPlaceholderText("Escriba para buscar una aplicación…")
        self.filtro.setClearButtonEnabled(True)
        self.filtro.textChanged.connect(self._filtrar)
        self.lista = QListWidget()
        self.lista.setIconSize(self.lista.iconSize() * 1.5)
        self.lista.itemDoubleClicked.connect(lambda _i: self.accept())
        tipos = [self.mime.name()] + list(self.mime.aliases()) + list(self.mime.allAncestors())
        recomendadas = {a.id for a in aplicaciones.para_tipo(tipos)}
        visibles = [a for a in aplicaciones.todas() if not getattr(a, "oculta", False) or a.id in recomendadas]
        visibles.sort(key=lambda a: (a.id not in recomendadas, a.nombre.lower()))
        vistos, unicas = set(), []
        for a in visibles:                     # la misma aplicación instalada dos veces aparece una sola vez
            if a.nombre.lower() not in vistos:
                vistos.add(a.nombre.lower())
                unicas.append(a)
        visibles = unicas
        for app in visibles:
            item = QListWidgetItem(_icono(app), app.nombre + ("   ✓ recomendada" if app.id in recomendadas else ""))
            item.setData(Qt.UserRole, app)
            item.setToolTip(app.id)
            if app.id in recomendadas:
                f = QFont(item.font())
                f.setBold(True)
                item.setFont(f)
            self.lista.addItem(item)
        if self.lista.count():
            self.lista.setCurrentRow(0)
        descripcion = self.mime.comment() or self.mime.name()
        self.siempre = QCheckBox(f"Usar siempre esta aplicación para «{descripcion}»")
        botones = QDialogButtonBox()
        self.b_abrir = botones.addButton("Abrir", QDialogButtonBox.AcceptRole)
        botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(titulo)
        lay.addWidget(self.filtro)
        lay.addWidget(self.lista, 1)
        lay.addWidget(self.siempre)
        lay.addWidget(botones)
        self.filtro.setFocus()

    def _filtrar(self, texto: str) -> None:
        t = texto.lower().strip()
        primero = None
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            app = item.data(Qt.UserRole)
            oculto = bool(t) and t not in app.nombre.lower() and t not in app.id.lower()
            item.setHidden(oculto)
            if not oculto and primero is None:
                primero = item
        if primero is not None:
            self.lista.setCurrentItem(primero)

    def elegida(self):
        item = self.lista.currentItem()
        return item.data(Qt.UserRole) if item is not None and not item.isHidden() else None

    def accept(self) -> None:
        app = self.elegida()
        if app is None:
            return
        if self.siempre.isChecked():
            try:
                aplicaciones.poner_predeterminada(app, self.mime.name())
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "Aplicación predeterminada", str(e))
        aplicaciones.abrir_con(app, self.rutas)
        super().accept()
