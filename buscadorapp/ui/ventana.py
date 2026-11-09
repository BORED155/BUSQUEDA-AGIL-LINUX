"""Ventana principal del Buscador Ágil."""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QMimeData, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QSpinBox, QTableView, QToolButton, QVBoxLayout, QWidget)

from .. import __version__, aplicaciones, sistema
from ..indice import CATEGORIAS, Buscador, Cancelado, Config, indexar
from .abrir_con import llenar_menu
from .modelo import ModeloResultados
from .widgets import Interruptor

ESTILO = """
QLineEdit#busqueda { font-size: 17px; padding: 9px 14px; border: 2px solid #1565c0; border-radius: 12px;
                     background: palette(base); }
QPushButton#categoria { border: 1px solid #cfd8dc; border-radius: 14px; padding: 5px 14px; background: #eceff1;
                        color: #37474f; }
QPushButton#categoria:hover { background: #e3f2fd; }
QPushButton#categoria:checked { background: #1565c0; color: white; border-color: #1565c0; font-weight: bold; }
QToolButton#herramienta { border: 1px solid #cfd8dc; border-radius: 10px; padding: 5px 12px; background: palette(base); }
QToolButton#herramienta:hover { border-color: #1565c0; }
QTableView { border: 1px solid #cfd8dc; border-radius: 12px; background: palette(base); gridline-color: transparent;
             selection-background-color: #1565c0; selection-color: white; outline: 0; }
QTableView::item { padding: 2px 6px; }
QHeaderView::section { background: palette(base); border: none; border-bottom: 1px solid #cfd8dc; padding: 6px;
                       font-weight: bold; color: #37474f; }
QLabel#estado { color: #546e7a; padding: 2px 4px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #b0bec5; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:horizontal { background: #b0bec5; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:hover { background: #78909c; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QPushButton#principal { background: #2e7d32; color: white; border-radius: 6px; padding: 6px 14px; }
"""

VERIFICAR = 100     # filas que se comprueban en disco en cada búsqueda: las visibles, no las 2000

AYUDA = ("Escriba parte del nombre. Ejemplos:\n"
         "  factura enero      → que tenga las dos palabras\n"
         '  "estado de cuenta" → la frase exacta\n'
         "  *.pdf   foto??.jpg → comodines\n"
         "  ext:xlsx,csv       → por extensión\n"
         "  sri/2026           → también busca en el nombre de la carpeta")


class _Señales(QObject):
    progreso = Signal(int, str)
    listo = Signal(int, float)
    error = Signal(str)


def miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def hace(segundos: float) -> str:
    if segundos < 60:
        return "hace un momento"
    if segundos < 3600:
        return f"hace {int(segundos // 60)} min"
    if segundos < 86400:
        return f"hace {int(segundos // 3600)} h"
    return f"hace {int(segundos // 86400)} días"


class VentanaBuscador(QMainWindow):
    def __init__(self, config: Config | None = None, ruta_indice: Path | None = None):
        super().__init__()
        self.config = config or Config.cargar()
        self.ruta_indice = ruta_indice
        self.buscador = Buscador(ruta_indice)
        self.categoria = "todo"
        self.orden, self.descendente = "nombre", False
        self.indexando = False
        self._cancelar = False
        self.setWindowTitle("Buscador Ágil")
        self.resize(1100, 680)
        self.setStyleSheet(ESTILO)

        # --- barra de búsqueda ---
        self.busqueda = QLineEdit()
        self.busqueda.setObjectName("busqueda")
        self.busqueda.setPlaceholderText("Buscar archivos y carpetas…   (ej.: factura enero, *.pdf, ext:xlsx)")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.setToolTip(AYUDA)
        self.busqueda.textChanged.connect(lambda _t: self._temporizador.start())
        self.busqueda.returnPressed.connect(self.abrir_primero)
        self._temporizador = QTimer(self, singleShot=True, interval=40)
        self._temporizador.timeout.connect(self.buscar)

        self.b_actualizar = QToolButton()
        self.b_actualizar.setObjectName("herramienta")
        self.b_actualizar.setText("⟳ Actualizar índice")
        self.b_actualizar.setToolTip("Vuelve a leer las carpetas para encontrar los archivos nuevos")
        self.b_actualizar.clicked.connect(self.actualizar_indice)
        self.b_config = QToolButton()
        self.b_config.setObjectName("herramienta")
        self.b_config.setText("⚙ Dónde buscar…")
        self.b_config.clicked.connect(self.configurar)
        arriba = QHBoxLayout()
        arriba.addWidget(self.busqueda, 1)
        arriba.addWidget(self.b_actualizar)
        arriba.addWidget(self.b_config)

        # --- categorías (botones redondeados) ---
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        cats = QHBoxLayout()
        cats.setSpacing(6)
        for clave, (texto, _ext) in CATEGORIAS.items():
            b = QPushButton(texto)
            b.setObjectName("categoria")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(clave == "todo")
            b.clicked.connect(lambda _c, k=clave: self._cambiar_categoria(k))
            self.grupo.addButton(b)
            cats.addWidget(b)
        cats.addStretch(1)

        # --- resultados ---
        self.modelo = ModeloResultados(self)
        self.modelo.orden_pedido.connect(self._ordenar)
        self.tabla = QTableView()
        self.tabla.setModel(self.modelo)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tabla.setShowGrid(False)
        self.tabla.setAlternatingRowColors(False)
        self.tabla.setWordWrap(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(26)
        self.tabla.setSortingEnabled(True)
        self.tabla.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
        cab = self.tabla.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.Interactive)
        cab.setSectionResizeMode(1, QHeaderView.Stretch)
        # ancho fijo: con ResizeToContents Qt mide cientos de filas en cada búsqueda (cerca de 1 s al abrir)
        medida = self.tabla.fontMetrics().horizontalAdvance
        cab.resizeSection(0, 380)
        cab.resizeSection(2, medida("999.9 MB") + 28)
        cab.resizeSection(3, medida("00/00/0000 00:00") + 28)
        self.tabla.setDragEnabled(True)
        self.tabla.setDragDropMode(QAbstractItemView.DragOnly)
        self.tabla.doubleClicked.connect(lambda i: self.abrir([i.row()]))
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._menu)

        self.lbl_estado = QLabel()
        self.lbl_estado.setObjectName("estado")
        self.barra = QProgressBar()
        self.barra.setMaximumWidth(200)
        self.barra.setRange(0, 0)
        self.barra.hide()
        abajo = QHBoxLayout()
        abajo.addWidget(self.lbl_estado, 1)
        abajo.addWidget(self.barra)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(14, 12, 14, 8)
        lay.setSpacing(10)
        lay.addLayout(arriba)
        lay.addLayout(cats)
        lay.addWidget(self.tabla, 1)
        lay.addLayout(abajo)
        self.setCentralWidget(central)

        # --- teclado ---
        for tecla, funcion in ((QKeySequence.Find, self.enfocar_busqueda), ("Ctrl+L", self.enfocar_busqueda),
                               ("F5", self.actualizar_indice), (QKeySequence.Delete, self.a_la_papelera),
                               ("Shift+Delete", self.eliminar_definitivo), ("Alt+Return", self.propiedades),
                               ("Ctrl+Shift+C", self.copiar_ruta), (QKeySequence.Copy, self.copiar_archivos),
                               ("Ctrl+Return", self.mostrar_en_carpeta), ("Escape", self._escape)):
            QShortcut(QKeySequence(tecla), self, activated=funcion)
        self.tabla.activated.connect(lambda i: self.abrir([i.row()]))
        self.busqueda.installEventFilter(self)

        # --- actualización automática del índice ---
        self._auto = QTimer(self)
        self._auto.timeout.connect(lambda: self.actualizar_indice(silencioso=True))
        self._programar_auto()

        total, fecha = self.buscador.info()
        if not total or (self.config.minutos_actualizar and time.time() - fecha > self.config.minutos_actualizar * 60):
            QTimer.singleShot(200, lambda: self.actualizar_indice(silencioso=bool(total)))
        self.buscar()
        self.enfocar_busqueda()

    # --- búsqueda -------------------------------------------------------------------------------
    def buscar(self) -> None:
        if not hasattr(self, "lbl_estado"):     # todavía se está armando la ventana
            return
        inicio = time.perf_counter()
        filas, total = self.buscador.buscar(self.busqueda.text(), self.categoria, self.orden, self.descendente)
        # lo que se borró por fuera (Archivos, terminal…) no se muestra y se saca del índice al momento
        faltan = [r for r in filas[:VERIFICAR] if not os.path.lexists(r.ruta)]
        if faltan:
            self.buscador.quitar([r.ruta for r in faltan])
            idos = {id(r) for r in faltan}
            filas = [r for r in filas if id(r) not in idos]
            total -= len(faltan)
        ms = (time.perf_counter() - inicio) * 1000
        self.modelo.poner(filas)
        self._estado(total, len(filas), ms)

    def _estado(self, total: int, mostrados: int, ms: float = 0) -> None:
        indexados, fecha = self.buscador.info()
        if not indexados:
            texto = "Creando el índice por primera vez… en unos segundos podrá buscar."
        else:
            texto = f"<b>{miles(total)}</b> resultado(s)"
            if mostrados < total:
                texto += f" (se muestran los primeros {miles(mostrados)}; escriba más para afinar)"
            texto += f"  ·  {miles(indexados)} elementos en el índice, actualizado {hace(time.time() - fecha)}"
            if ms:
                texto += f"  ·  {ms:.0f} ms"
        self.lbl_estado.setText(texto)

    def _cambiar_categoria(self, clave: str) -> None:
        self.categoria = clave
        self.buscar()

    def _ordenar(self, columna: str, descendente: bool) -> None:
        self.orden, self.descendente = columna, descendente
        self.buscar()

    def enfocar_busqueda(self) -> None:
        self.busqueda.setFocus()
        self.busqueda.selectAll()

    def _escape(self) -> None:
        if self.busqueda.text():
            self.busqueda.clear()
            self.enfocar_busqueda()
        else:
            self.showMinimized()

    def eventFilter(self, obj, evento) -> bool:
        # flecha abajo desde la búsqueda: pasa a los resultados
        if obj is self.busqueda and evento.type() == evento.Type.KeyPress and evento.key() == Qt.Key_Down:
            if self.modelo.rowCount():
                self.tabla.setFocus()
                self.tabla.selectRow(0)
                return True
        return super().eventFilter(obj, evento)

    # --- índice ---------------------------------------------------------------------------------
    def _programar_auto(self) -> None:
        self._auto.stop()
        if self.config.minutos_actualizar:
            self._auto.start(self.config.minutos_actualizar * 60 * 1000)

    def actualizar_indice(self, silencioso: bool = False) -> None:
        if self.indexando:
            return
        self.indexando = True
        self._cancelar = False
        self.b_actualizar.setEnabled(False)
        self.barra.show()
        s = _Señales(self)
        s.progreso.connect(lambda n, ruta: self.statusBar().showMessage(
            f"Leyendo carpetas… {miles(n)} elementos — {ruta}"))
        s.listo.connect(self._indice_listo)
        s.error.connect(self._indice_error)
        config, destino = self.config, self.ruta_indice

        def trabajo():
            inicio = time.time()
            try:
                n = indexar(config, destino, progreso=s.progreso.emit, cancelar=lambda: self._cancelar)
                s.listo.emit(n, time.time() - inicio)
            except Cancelado:
                s.error.emit("")
            except Exception as e:  # noqa: BLE001 - se informa al usuario
                s.error.emit(str(e))

        threading.Thread(target=trabajo, daemon=True).start()

    def _indice_listo(self, n: int, segundos: float) -> None:
        self.indexando = False
        self.b_actualizar.setEnabled(True)
        self.barra.hide()
        self.statusBar().showMessage(f"Índice actualizado: {miles(n)} elementos en {segundos:.1f} s.",
                                     6000)
        self.buscar()

    def _indice_error(self, mensaje: str) -> None:
        self.indexando = False
        self.b_actualizar.setEnabled(True)
        self.barra.hide()
        self.statusBar().clearMessage()
        if mensaje:
            QMessageBox.warning(self, "No se pudo actualizar el índice", mensaje)

    # --- acciones sobre los resultados ------------------------------------------------------------
    def filas_elegidas(self) -> list[int]:
        return sorted({i.row() for i in self.tabla.selectionModel().selectedRows()})

    def abrir_primero(self) -> None:
        if self.modelo.rowCount():
            self.abrir([0])

    def abrir(self, filas: list[int] | None = None) -> None:
        for f in (filas if filas is not None else self.filas_elegidas())[:10]:
            ruta = self.modelo.filas[f].ruta
            if not Path(ruta).exists():
                self.statusBar().showMessage(f"Ya no existe: {ruta} (pulse «Actualizar índice»)", 8000)
                continue
            # con la aplicación predeterminada del sistema (la misma que usa Archivos con doble clic)
            if not aplicaciones.abrir_predeterminada(ruta):
                QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))

    def mostrar_en_carpeta(self) -> None:
        filas = self.filas_elegidas()
        if not filas:
            return
        r = self.modelo.filas[filas[0]]
        if not sistema.mostrar_en_carpeta(Path(r.ruta)):
            aplicaciones.abrir_predeterminada(r.carpeta)

    def copiar_ruta(self) -> None:
        rutas = [self.modelo.filas[f].ruta for f in self.filas_elegidas()]
        if rutas:
            QGuiApplication.clipboard().setText("\n".join(rutas))
            self.statusBar().showMessage("Ruta copiada.", 4000)

    def copiar_archivos(self) -> None:
        """Copia los archivos para pegarlos en Archivos (Ctrl+V), el escritorio, un correo…"""
        if self.busqueda.hasFocus():
            self.busqueda.copy()
            return
        rutas = [self.modelo.filas[f].ruta for f in self.filas_elegidas()]
        if not rutas:
            return
        datos = QMimeData()
        datos.setUrls([QUrl.fromLocalFile(r) for r in rutas])
        datos.setData("x-special/gnome-copied-files",
                      ("copy\n" + "\n".join(QUrl.fromLocalFile(r).toString() for r in rutas)).encode())
        datos.setText("\n".join(rutas))
        QGuiApplication.clipboard().setMimeData(datos)
        self.statusBar().showMessage(f"{len(rutas)} elemento(s) copiados: péguelos con Ctrl+V donde quiera.", 6000)

    def a_la_papelera(self) -> None:
        self.eliminar(permanente=False)

    def eliminar_definitivo(self) -> None:
        self.eliminar(permanente=True)

    def eliminar(self, permanente: bool = False) -> None:
        if self.busqueda.hasFocus():
            return
        filas = self.filas_elegidas()
        if not filas:
            return
        nombres = [self.modelo.filas[f].nombre for f in filas]
        cuales = f"«{nombres[0]}»" if len(nombres) == 1 else f"{len(nombres)} elementos"
        if permanente:
            texto = f"¿Eliminar {cuales} PARA SIEMPRE?\n\nNo pasa por la papelera: no se puede recuperar."
            titulo, boton = "Eliminar definitivamente", "Eliminar para siempre"
        else:
            texto, titulo, boton = f"¿Mover {cuales} a la papelera?", "Mover a la papelera", "Mover a la papelera"
        caja = QMessageBox(QMessageBox.Warning if permanente else QMessageBox.Question, titulo, texto, parent=self)
        b_si = caja.addButton(boton, QMessageBox.ActionRole)
        b_si.setStyleSheet("background: #f4a6a6; color: black; padding: 5px 14px;")
        b_no = caja.addButton("Cancelar", QMessageBox.ActionRole)
        caja.setDefaultButton(b_no)
        caja.setEscapeButton(b_no)
        caja.exec()
        if caja.clickedButton() is not b_si:
            return
        borrados = []
        for f in filas:
            r = self.modelo.filas[f]
            try:
                if permanente:
                    if r.es_dir and not os.path.islink(r.ruta):
                        shutil.rmtree(r.ruta)
                    else:
                        os.unlink(r.ruta)
                else:
                    sistema.a_la_papelera(Path(r.ruta))
                borrados.append(r.ruta)
            except OSError as e:
                QMessageBox.warning(self, "No se pudo", f"{r.nombre}: {e}")
                break
        # al instante: fuera de la lista y fuera del índice (sin esperar a «Actualizar índice»)
        self.buscador.quitar(borrados)
        fila = filas[0]
        self.buscar()
        if self.modelo.rowCount():
            self.tabla.selectRow(min(fila, self.modelo.rowCount() - 1))   # para seguir borrando con Supr
            self.tabla.setFocus()
        self.statusBar().showMessage(
            f"{len(borrados)} elemento(s) " + ("eliminados definitivamente." if permanente else
                                               "movidos a la papelera (se pueden recuperar desde ahí)."), 6000)

    def propiedades(self) -> None:
        from .propiedades import DialogoPropiedades

        filas = self.filas_elegidas()
        if not filas:
            return
        r = self.modelo.filas[filas[0]]
        if not os.path.lexists(r.ruta):
            self.buscar()
            return
        DialogoPropiedades(r.ruta, self).exec()
        self.buscar()     # por si se borró o cambió algo mientras estaba abierta

    def _menu(self, pos) -> None:
        if not self.filas_elegidas():
            return
        rutas = [self.modelo.filas[f].ruta for f in self.filas_elegidas()]
        m = QMenu(self)

        def accion(texto, icono, funcion, atajo=None):
            a = m.addAction(QIcon.fromTheme(icono), texto, funcion)
            if atajo:
                a.setShortcut(QKeySequence(atajo))          # se muestra a la derecha, alineado
                a.setShortcutVisibleInContextMenu(True)
            return a

        accion("Abrir", "document-open", self.abrir, "Return")
        con = m.addMenu(QIcon.fromTheme("system-run"), "Abrir con")
        con.aboutToShow.connect(lambda: con.isEmpty() and llenar_menu(con, rutas, self))
        accion("Abrir carpeta contenedora", "folder-open", self.mostrar_en_carpeta, "Ctrl+Return")
        m.addSeparator()
        accion("Copiar", "edit-copy", self.copiar_archivos, "Ctrl+C")
        accion("Copiar ruta", "edit-paste", self.copiar_ruta, "Ctrl+Shift+C")
        m.addSeparator()
        accion("Mover a la papelera", "user-trash", self.a_la_papelera, "Delete")
        accion("Eliminar definitivamente", "edit-delete", self.eliminar_definitivo, "Shift+Delete")
        m.addSeparator()
        accion("Propiedades", "document-properties", self.propiedades, "Alt+Return")
        m.exec(self.tabla.viewport().mapToGlobal(pos))

    # --- configuración ----------------------------------------------------------------------------
    def configurar(self) -> None:
        dlg = DialogoConfig(self.config, self)
        if dlg.exec() != QDialog.Accepted:
            return
        cambio_carpetas = dlg.aplicar()
        self.config.guardar()
        self._programar_auto()
        if cambio_carpetas:
            self.actualizar_indice()

    def mostrar(self) -> None:
        """Traer la ventana al frente (al abrir el programa otra vez o con el atajo de teclado)."""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.enfocar_busqueda()

    def changeEvent(self, e) -> None:
        # al volver a la ventana (p. ej. después de borrar algo en Archivos) se refresca la lista
        if e.type() == e.Type.ActivationChange and self.isActiveWindow() and hasattr(self, "lbl_estado"):
            filas = self.filas_elegidas()
            self.buscar()
            if filas and self.modelo.rowCount():
                self.tabla.selectRow(min(filas[0], self.modelo.rowCount() - 1))
        super().changeEvent(e)

    def closeEvent(self, e) -> None:
        self._cancelar = True
        super().closeEvent(e)


class DialogoConfig(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Dónde buscar")
        self.resize(620, 560)
        self.carpetas = QListWidget()
        self.carpetas.addItems(config.carpetas)
        b_agregar = QPushButton("Agregar carpeta…")
        b_agregar.clicked.connect(self._agregar)
        b_quitar = QPushButton("Quitar")
        b_quitar.clicked.connect(lambda: [self.carpetas.takeItem(self.carpetas.row(i))
                                          for i in self.carpetas.selectedItems()])
        fila = QHBoxLayout()
        fila.addWidget(b_agregar)
        discos = [d for d in sistema.discos_montados() if d not in config.carpetas]
        if discos:
            b_disco = QToolButton()
            b_disco.setText("Agregar otro disco  ▾")
            b_disco.setPopupMode(QToolButton.InstantPopup)
            menu = QMenu(b_disco)
            for d in discos:
                menu.addAction(d, lambda d=d: self._agregar_ruta(d))
            b_disco.setMenu(menu)
            fila.addWidget(b_disco)
        fila.addWidget(b_quitar)
        fila.addStretch(1)
        self.excluir = QListWidget()
        self.excluir.addItems(config.excluir)
        b_ex = QPushButton("Agregar carpeta a excluir…")
        b_ex.clicked.connect(self._agregar_excluida)
        b_ex_q = QPushButton("Quitar")
        b_ex_q.clicked.connect(lambda: [self.excluir.takeItem(self.excluir.row(i)) for i in self.excluir.selectedItems()])
        fila_ex = QHBoxLayout()
        fila_ex.addWidget(b_ex)
        fila_ex.addWidget(b_ex_q)
        fila_ex.addStretch(1)
        self.ocultos = Interruptor("Incluir archivos y carpetas ocultos (los que empiezan con «.»)")
        self.ocultos.setChecked(config.ocultos)
        self.minutos = QSpinBox()
        self.minutos.setRange(0, 1440)
        self.minutos.setSuffix(" min")
        self.minutos.setSpecialValueText("nunca")
        self.minutos.setValue(config.minutos_actualizar)
        fila_min = QHBoxLayout()
        fila_min.addWidget(QLabel("Actualizar el índice solo cada:"))
        fila_min.addWidget(self.minutos)
        fila_min.addStretch(1)

        self.lbl_atajo = QLabel()
        self.b_atajo = QPushButton()
        self.b_atajo.clicked.connect(self._atajo)
        fila_atajo = QHBoxLayout()
        fila_atajo.addWidget(self.lbl_atajo, 1)
        fila_atajo.addWidget(self.b_atajo)
        self._mostrar_atajo()

        botones = QDialogButtonBox()
        ok = botones.addButton("Guardar", QDialogButtonBox.AcceptRole)
        ok.setObjectName("principal")
        botones.addButton("Cancelar", QDialogButtonBox.RejectRole)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Carpetas donde buscar</b> (con todo lo que tienen adentro):"))
        lay.addWidget(self.carpetas, 1)
        lay.addLayout(fila)
        lay.addWidget(QLabel("<b>Carpetas que no se revisan</b>:"))
        lay.addWidget(self.excluir, 1)
        lay.addLayout(fila_ex)
        lay.addWidget(self.ocultos)
        lay.addLayout(fila_min)
        lay.addWidget(QLabel("<b>Atajo de teclado</b> para abrir el buscador desde cualquier lugar:"))
        lay.addLayout(fila_atajo)
        lay.addWidget(botones)

    def _agregar_ruta(self, ruta: str) -> None:
        if ruta and not self.carpetas.findItems(ruta, Qt.MatchExactly):
            self.carpetas.addItem(ruta)

    def _agregar(self) -> None:
        self._agregar_ruta(QFileDialog.getExistingDirectory(self, "Carpeta donde buscar", str(Path.home())))

    def _agregar_excluida(self) -> None:
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta que no se revisa", str(Path.home()))
        if ruta and not self.excluir.findItems(ruta, Qt.MatchExactly):
            self.excluir.addItem(ruta)

    def _mostrar_atajo(self) -> None:
        actual = sistema.atajo_actual()
        if actual:
            legible = actual
            for viejo, nuevo in (("<Primary>", "Ctrl+"), ("<Control>", "Ctrl+"), ("<Alt>", "Alt+"),
                                 ("<Super>", "Super+"), ("<Shift>", "Mayús+")):
                legible = legible.replace(viejo, nuevo)
            cabeza, _, tecla = legible.rpartition("+")
            self.lbl_atajo.setText(f"Activo: <b>{cabeza + '+' if cabeza else ''}{tecla.upper()}</b>")
            self.b_atajo.setText("Quitar el atajo")
        else:
            self.lbl_atajo.setText("Sin atajo. Se puede crear <b>Ctrl+Alt+B</b>.")
            self.b_atajo.setText("Crear atajo Ctrl+Alt+B")

    def _atajo(self) -> None:
        try:
            if sistema.atajo_actual():
                sistema.quitar_atajo()
            else:
                sistema.poner_atajo(comando_programa())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Atajo de teclado", f"No se pudo: {e}")
        self._mostrar_atajo()

    def aplicar(self) -> bool:
        carpetas = [self.carpetas.item(i).text() for i in range(self.carpetas.count())]
        excluir = [self.excluir.item(i).text() for i in range(self.excluir.count())]
        cambio = (carpetas != self.config.carpetas or excluir != self.config.excluir
                  or self.ocultos.isChecked() != self.config.ocultos)
        self.config.carpetas, self.config.excluir = carpetas, excluir
        self.config.ocultos = self.ocultos.isChecked()
        self.config.minutos_actualizar = self.minutos.value()
        return cambio


def comando_programa() -> str:
    """Cómo volver a abrir este programa (para el atajo de teclado)."""
    ejecutable = Path(sys.argv[0]).resolve()
    if ejecutable.name == "buscadorapp" or getattr(sys, "frozen", False):
        return str(ejecutable)
    return f"{sys.executable} -m buscadorapp"


def acerca() -> str:
    return f"Buscador Ágil {__version__}"
