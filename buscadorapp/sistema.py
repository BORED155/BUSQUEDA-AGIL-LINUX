"""Acciones con el escritorio: abrir, mostrar en carpeta, papelera, atajo de teclado global."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

RUTA_ATAJO = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/buscador-agil/"
ESQUEMA_ATAJOS = "org.gnome.settings-daemon.plugins.media-keys"
ESQUEMA_ATAJO = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"


def entorno_sistema() -> dict[str, str]:
    """Entorno para lanzar programas del sistema. En el .deb, LD_LIBRARY_PATH apunta a las librerías del paquete y
    con ellas gsettings no carga dconf (guarda en otro lado, sin avisar) y gio falla al arrancar."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
    return env


def mostrar_en_carpeta(ruta: Path) -> bool:
    """Abre el administrador de archivos con el elemento seleccionado. Devuelve False si no se pudo."""
    if shutil.which("gdbus"):
        try:
            r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
                                "--object-path", "/org/freedesktop/FileManager1",
                                "--method", "org.freedesktop.FileManager1.ShowItems", f"['{Path(ruta).as_uri()}']",
                                ""], capture_output=True, timeout=10, env=entorno_sistema())
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return False


def a_la_papelera(ruta: Path) -> None:
    r = subprocess.run(["gio", "trash", str(ruta)], capture_output=True, text=True, timeout=60, env=entorno_sistema())
    if r.returncode != 0:
        raise OSError((r.stderr or "No se pudo mover a la papelera").strip())


# --- atajo de teclado global (GNOME, Zorin, Ubuntu, Budgie…) ---------------------------------
def _gs(*args: str) -> str:
    r = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=10, env=entorno_sistema())
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "gsettings falló").strip())
    return r.stdout.strip()


def atajo_actual() -> str:
    """El atajo configurado para Buscador Ágil (p. ej. «<Primary><Alt>b») o «»."""
    try:
        lista = _gs("get", ESQUEMA_ATAJOS, "custom-keybindings")
        if RUTA_ATAJO not in lista:
            return ""
        return _gs("get", f"{ESQUEMA_ATAJO}:{RUTA_ATAJO}", "binding").strip("'")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return ""


def poner_atajo(comando: str, combinacion: str = "<Primary><Alt>b") -> None:
    """Agrega (sin tocar los demás) un atajo de teclado que abre el buscador."""
    texto = _gs("get", ESQUEMA_ATAJOS, "custom-keybindings")
    texto = texto.replace("@as ", "")
    try:
        lista = list(ast.literal_eval(texto)) if texto.strip() not in ("", "[]") else []
    except (ValueError, SyntaxError):
        lista = []
    if RUTA_ATAJO not in lista:
        lista.append(RUTA_ATAJO)
        _gs("set", ESQUEMA_ATAJOS, "custom-keybindings", str(lista))
    _gs("set", f"{ESQUEMA_ATAJO}:{RUTA_ATAJO}", "name", "Buscador Ágil")
    _gs("set", f"{ESQUEMA_ATAJO}:{RUTA_ATAJO}", "command", comando)
    _gs("set", f"{ESQUEMA_ATAJO}:{RUTA_ATAJO}", "binding", combinacion)


def quitar_atajo() -> None:
    texto = _gs("get", ESQUEMA_ATAJOS, "custom-keybindings").replace("@as ", "")
    try:
        lista = list(ast.literal_eval(texto)) if texto.strip() not in ("", "[]") else []
    except (ValueError, SyntaxError):
        lista = []
    if RUTA_ATAJO in lista:
        lista.remove(RUTA_ATAJO)
        _gs("set", ESQUEMA_ATAJOS, "custom-keybindings", str(lista))
    for clave in ("name", "command", "binding"):
        try:
            _gs("reset", f"{ESQUEMA_ATAJO}:{RUTA_ATAJO}", clave)
        except RuntimeError:
            pass


def discos_montados() -> list[str]:
    """Otros discos montados (p. ej. la partición de Windows en /mnt/windows, memorias USB en /media)."""
    rutas = []
    try:
        for linea in Path("/proc/mounts").read_text().splitlines():
            partes = linea.split()
            if len(partes) > 2:
                destino = partes[1].replace("\\040", " ")
                if destino.startswith(("/mnt/", "/media/", "/run/media/")):
                    rutas.append(destino)
    except OSError:
        pass
    return sorted(set(rutas))
