"""Construye el instalador .deb de Buscador Ágil (Zorin, Ubuntu, Linux Mint, Debian, Pop!_OS…).

Uso, desde la carpeta del proyecto:   .venv/bin/python empaquetar/construir_deb.py
Resultado:                             dist/buscador-agil_<versión>_amd64.deb

El programa va completo adentro (Python y Qt incluidos): en la otra máquina no hace falta instalar nada más.
Se instala en /opt/buscador-agil, con su ícono en el menú de aplicaciones y el comando «buscador-agil».
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NOMBRE = "buscador-agil"

# módulos de Qt que el buscador no usa: se dejan fuera para que el instalador pese menos
SIN_USAR = ["tkinter", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D",
            "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
            "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
            "PySide6.QtSerialPort", "PySide6.QtDesigner", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL",
            "PySide6.QtSvgWidgets", "PySide6.QtPrintSupport", "PySide6.QtQuickWidgets", "PySide6.QtGraphs"]

ESCRITORIO = """[Desktop Entry]
Type=Application
Version=1.0
Name=Buscador Ágil
GenericName=Buscador de archivos
Comment=Encuentra cualquier archivo al instante mientras escribe
Exec=/opt/buscador-agil/buscador-agil %U
Icon=buscador-agil
Terminal=false
Categories=Utility;FileTools;
Keywords=buscar;archivos;everything;search;find;
StartupWMClass=buscador-agil
"""

POSTINST = """#!/bin/sh
set -e
update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
exit 0
"""


def main() -> int:
    sys.path.insert(0, str(RAIZ))
    from buscadorapp import __version__

    dist, build = RAIZ / "dist", RAIZ / "build"
    shutil.rmtree(build, ignore_errors=True)
    shutil.rmtree(dist / NOMBRE, ignore_errors=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", NOMBRE, "--windowed",
            "--onedir", "--paths", str(RAIZ), "--distpath", str(dist), "--workpath", str(build),
            "--specpath", str(build)]
    for m in SIN_USAR:
        args += ["--exclude-module", m]
    args.append(str(RAIZ / "empaquetar" / "lanzador.py"))
    subprocess.run(args, check=True)

    paquete = build / "deb"
    shutil.rmtree(paquete, ignore_errors=True)
    shutil.copytree(dist / NOMBRE, paquete / "opt" / NOMBRE, symlinks=True)
    (paquete / "usr" / "bin").mkdir(parents=True)
    os.symlink(f"/opt/{NOMBRE}/{NOMBRE}", paquete / "usr" / "bin" / NOMBRE)
    apps = paquete / "usr" / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / f"{NOMBRE}.desktop").write_text(ESCRITORIO, encoding="utf-8")
    iconos = paquete / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    iconos.mkdir(parents=True)
    shutil.copy2(RAIZ / "empaquetar" / "icono.svg", iconos / f"{NOMBRE}.svg")

    tamano_kb = sum(p.stat().st_size for p in paquete.rglob("*") if p.is_file() and not p.is_symlink()) // 1024
    control = paquete / "DEBIAN"
    control.mkdir()
    (control / "control").write_text(f"""Package: {NOMBRE}
Version: {__version__}
Section: utils
Priority: optional
Architecture: amd64
Installed-Size: {tamano_kb}
Depends: libc6 (>= 2.35), libxcb-cursor0, libxkbcommon-x11-0, libegl1, libgl1, libfontconfig1, libdbus-1-3, xdg-utils, libglib2.0-bin
Maintainer: Leninsodu <198639107+Leninsodu@users.noreply.github.com>
Description: Buscador Ágil - encuentra cualquier archivo al instante
 Busca archivos y carpetas mientras escribe, como Everything en Windows:
 sin importar mayúsculas ni tildes, con comodines, filtros por tipo,
 abrir con, propiedades, papelera y un atajo de teclado global.
""", encoding="utf-8")
    (control / "postinst").write_text(POSTINST, encoding="utf-8")
    (control / "postrm").write_text(POSTINST, encoding="utf-8")
    for f in ("postinst", "postrm"):
        (control / f).chmod(0o755)
    for p in paquete.rglob("*"):
        if p.is_dir() and not p.is_symlink():
            p.chmod(0o755)
    destino = dist / f"{NOMBRE}_{__version__}_amd64.deb"
    destino.unlink(missing_ok=True)
    subprocess.run(["fakeroot", "dpkg-deb", "--build", "-Zxz", str(paquete), str(destino)], check=True)
    print(f"\nListo: {destino}  ({destino.stat().st_size / 1024 / 1024:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
