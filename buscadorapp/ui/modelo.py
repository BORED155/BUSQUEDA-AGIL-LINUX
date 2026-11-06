"""Modelo de la tabla de resultados."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QIcon
from PySide6.QtCore import QMimeDatabase

from ..indice import Resultado

COLUMNAS = [("Nombre", "nombre"), ("Carpeta", "carpeta"), ("Tamaño", "tamano"), ("Modificado", "fecha")]


def tamano_legible(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unidad in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024:
            return f"{n:,.1f} {unidad}".replace(",", " ")
    return f"{n:,.1f} PB"


class ModeloResultados(QAbstractTableModel):
    orden_pedido = Signal(str, bool)   # (columna, descendente): la búsqueda se ordena en la base de datos

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filas: list[Resultado] = []
        self._mimes = QMimeDatabase()
        self._iconos: dict[str, QIcon] = {}

    def poner(self, filas: list[Resultado]) -> None:
        self.beginResetModel()
        self.filas = filas
        self.endResetModel()

    def quitar(self, fila: int) -> None:
        self.beginRemoveRows(QModelIndex(), fila, fila)
        del self.filas[fila]
        self.endRemoveRows()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.filas)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNAS)

    def headerData(self, seccion, orientacion, rol=Qt.DisplayRole):
        if orientacion == Qt.Horizontal and rol == Qt.DisplayRole:
            return COLUMNAS[seccion][0]
        return None

    def _icono(self, r: Resultado) -> QIcon:
        clave = "/carpeta" if r.es_dir else r.nombre.rsplit(".", 1)[-1].lower() if "." in r.nombre else ""
        icono = self._iconos.get(clave)
        if icono is None:
            if r.es_dir:
                icono = QIcon.fromTheme("folder")
            else:
                mime = self._mimes.mimeTypeForFile(r.nombre, QMimeDatabase.MatchExtension)
                icono = QIcon.fromTheme(mime.iconName(), QIcon.fromTheme(mime.genericIconName(),
                                                                         QIcon.fromTheme("text-x-generic")))
            self._iconos[clave] = icono
        return icono

    def data(self, indice, rol=Qt.DisplayRole):
        if not indice.isValid():
            return None
        r = self.filas[indice.row()]
        col = indice.column()
        if rol == Qt.DisplayRole:
            if col == 0:
                return r.nombre
            if col == 1:
                return r.carpeta
            if col == 2:
                return "" if r.es_dir else tamano_legible(r.tamano)
            return dt.datetime.fromtimestamp(r.mtime).strftime("%d/%m/%Y %H:%M") if r.mtime else ""
        if rol == Qt.DecorationRole and col == 0:
            return self._icono(r)
        if rol == Qt.ToolTipRole:
            return r.ruta
        if rol == Qt.TextAlignmentRole and col == 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def flags(self, indice):
        return super().flags(indice) | Qt.ItemIsDragEnabled

    def sort(self, columna: int, orden=Qt.AscendingOrder) -> None:
        self.orden_pedido.emit(COLUMNAS[columna][1], orden == Qt.DescendingOrder)

    # arrastrar resultados a otras aplicaciones (Archivos, correo, el escritorio…)
    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indices):
        filas = sorted({i.row() for i in indices})
        datos = QMimeData()
        datos.setUrls([QUrl.fromLocalFile(self.filas[f].ruta) for f in filas])
        return datos
