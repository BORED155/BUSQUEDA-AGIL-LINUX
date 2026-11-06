"""Controles con estilo moderno."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox


class Interruptor(QCheckBox):
    """Casilla con forma de interruptor (píldora redondeada con un círculo que se desliza)."""

    ANCHO, ALTO = 38, 20

    def __init__(self, texto: str = "", parent=None):
        super().__init__(texto, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=140)
        self._anim.valueChanged.connect(self._mover)
        self.toggled.connect(self._animar)

    def setChecked(self, si: bool) -> None:
        super().setChecked(si)
        self._pos = 1.0 if si else 0.0
        self.update()

    def _mover(self, v) -> None:
        self._pos = float(v)
        self.update()

    def _animar(self, activo: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if activo else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:
        texto = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(self.ANCHO + 8 + texto + 4, max(self.ALTO + 4, self.fontMetrics().height() + 4))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - self.ALTO) / 2
        a, b = QColor("#b0bec5"), QColor("#2e7d32")
        fondo = QColor(int(a.red() + (b.red() - a.red()) * self._pos), int(a.green() + (b.green() - a.green()) * self._pos),
                       int(a.blue() + (b.blue() - a.blue()) * self._pos))
        p.setPen(Qt.NoPen)
        p.setBrush(fondo if self.isEnabled() else QColor("#e0e0e0"))
        p.drawRoundedRect(QRectF(0, y, self.ANCHO, self.ALTO), self.ALTO / 2, self.ALTO / 2)
        m = 3
        d = self.ALTO - 2 * m
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(m + (self.ANCHO - d - 2 * m) * self._pos, y + m, d, d))
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(QRectF(self.ANCHO + 8, 0, self.width() - self.ANCHO - 8, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()
