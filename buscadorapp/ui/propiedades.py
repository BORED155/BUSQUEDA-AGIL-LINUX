"""Ventana de propiedades de un archivo o carpeta."""

from __future__ import annotations

import datetime as dt
import grp
import os
import pwd
import stat
import threading
from pathlib import Path

from PySide6.QtCore import QMimeDatabase, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QImageReader
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout)

from .. import aplicaciones, sistema
from .modelo import tamano_legible


class _Señal(QObject):
    listo = Signal(int, int, int, bool)   # bytes, archivos, carpetas, terminado


def _fecha(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%d/%m/%Y %H:%M:%S") if t else "—"


def permisos_legibles(modo: int) -> str:
    def trio(r, w, x):
        partes = [n for bit, n in ((r, "leer"), (w, "escribir"), (x, "ejecutar")) if modo & bit]
        return ", ".join(partes) or "ninguno"

    return (f"Dueño: {trio(stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR)}  ·  "
            f"Grupo: {trio(stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP)}  ·  "
            f"Otros: {trio(stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH)}   ({stat.filemode(modo)})")


def tamano_carpeta(ruta: str, avisar, cancelar) -> None:
    total = archivos = carpetas = 0
    pila = [ruta]
    n = 0
    while pila:
        if cancelar():
            return
        actual = pila.pop()
        try:
            entradas = list(os.scandir(actual))
        except OSError:
            continue
        for e in entradas:
            try:
                if e.is_dir(follow_symlinks=False):
                    carpetas += 1
                    pila.append(e.path)
                else:
                    archivos += 1
                    total += e.stat(follow_symlinks=False).st_size
            except OSError:
                pass
        n += 1
        if n % 200 == 0:
            avisar(total, archivos, carpetas, False)
    avisar(total, archivos, carpetas, True)


class DialogoPropiedades(QDialog):
    def __init__(self, ruta: str, parent=None):
        super().__init__(parent)
        self.ruta = ruta
        self._cancelar = False
        p = Path(ruta)
        self.setWindowTitle(f"Propiedades — {p.name}")
        self.setMinimumWidth(560)
        try:
            st = os.lstat(ruta)
        except OSError as e:
            st = None
            error = str(e)
        es_dir = bool(st and stat.S_ISDIR(st.st_mode))
        es_enlace = bool(st and stat.S_ISLNK(st.st_mode))

        # encabezado: ícono grande + nombre
        mime = QMimeDatabase().mimeTypeForFile(ruta)
        icono = QIcon.fromTheme("folder" if es_dir else mime.iconName(),
                                QIcon.fromTheme(mime.genericIconName(), QIcon.fromTheme("text-x-generic")))
        img = QLabel()
        img.setPixmap(icono.pixmap(64, 64))
        nombre = QLabel(f"<span style='font-size:16px'><b>{p.name}</b></span><br>"
                        f"<span style='color:#546e7a'>{'Carpeta' if es_dir else mime.comment() or 'Archivo'}</span>")
        nombre.setTextInteractionFlags(Qt.TextSelectableByMouse)
        nombre.setWordWrap(True)
        cabeza = QHBoxLayout()
        cabeza.addWidget(img)
        cabeza.addWidget(nombre, 1)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(7)

        def fila(titulo, texto):
            l = QLabel(texto)
            l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            l.setWordWrap(True)
            l.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            form.addRow(f"<b>{titulo}:</b>", l)
            return l

        fila("Ubicación", str(p.parent))
        if st is None:
            fila("Estado", f"No se puede leer: {error}")
        else:
            if es_enlace:
                fila("Apunta a", os.readlink(ruta))
            if es_dir:
                self.lbl_tamano = fila("Contenido", "Calculando…")
                s = _Señal(self)
                s.listo.connect(self._contenido)
                threading.Thread(target=tamano_carpeta, args=(ruta, s.listo.emit, lambda: self._cancelar),
                                 daemon=True).start()
            else:
                fila("Tamaño", f"{tamano_legible(st.st_size)}  ({st.st_size:,} bytes)".replace(",", "."))
                fila("Tipo", f"{mime.comment()}  ({mime.name()})")
                lector = QImageReader(ruta)
                if mime.name().startswith("image/") and lector.size().isValid():
                    t = lector.size()
                    fila("Dimensiones", f"{t.width()} × {t.height()} píxeles")
            fila("Modificado", _fecha(st.st_mtime))
            fila("Último acceso", _fecha(st.st_atime))
            fila("Cambio de atributos", _fecha(st.st_ctime))
            try:
                dueno = pwd.getpwuid(st.st_uid).pw_name
            except KeyError:
                dueno = str(st.st_uid)
            try:
                grupo = grp.getgrgid(st.st_gid).gr_name
            except KeyError:
                grupo = str(st.st_gid)
            fila("Dueño", f"{dueno}  (grupo {grupo})")
            fila("Permisos", permisos_legibles(st.st_mode))
            fila("Se puede", ", ".join(x for x, ok in (("leer", os.access(ruta, os.R_OK)),
                                                      ("modificar", os.access(ruta, os.W_OK)))
                                       if ok) or "solo verlo en la lista")

        botones = QHBoxLayout()
        for texto, funcion in (("Abrir", lambda: aplicaciones.abrir_predeterminada(ruta)),
                               ("📂 Abrir carpeta contenedora", self._carpeta),
                               ("Copiar ruta", lambda: QGuiApplication.clipboard().setText(ruta))):
            b = QPushButton(texto)
            b.clicked.connect(funcion)
            botones.addWidget(b)
        botones.addStretch(1)
        cerrar = QPushButton("Cerrar")
        cerrar.setDefault(True)
        cerrar.clicked.connect(self.accept)
        botones.addWidget(cerrar)

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addLayout(cabeza)
        lay.addLayout(form)
        lay.addLayout(botones)

    def _carpeta(self) -> None:
        if not sistema.mostrar_en_carpeta(Path(self.ruta)):
            aplicaciones.abrir_predeterminada(str(Path(self.ruta).parent))

    def _contenido(self, total: int, archivos: int, carpetas: int, terminado: bool) -> None:
        texto = (f"{tamano_legible(total)}  ·  {archivos:,} archivo(s) y {carpetas:,} carpeta(s)"
                 .replace(",", "."))
        self.lbl_tamano.setText(texto + ("" if terminado else "  (calculando…)"))

    def done(self, r) -> None:
        self._cancelar = True
        super().done(r)
