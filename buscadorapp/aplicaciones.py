"""Aplicaciones instaladas (archivos .desktop): cuáles abren un tipo de archivo, la predeterminada y «Abrir con»."""

from __future__ import annotations

import configparser
import locale
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Aplicacion:
    id: str                  # p. ej. «org.gnome.Evince.desktop»
    nombre: str
    icono: str
    ruta: Path               # el archivo .desktop
    mimes: list[str] = field(default_factory=list)


def carpetas_aplicaciones() -> list[Path]:
    """Por prioridad: las del usuario primero (pueden reemplazar a las del sistema)."""
    casa = Path.home()
    datos = Path(os.environ.get("XDG_DATA_HOME") or casa / ".local" / "share")
    rutas = [datos / "applications", datos / "flatpak" / "exports" / "share" / "applications"]
    for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"):
        if d:
            rutas.append(Path(d) / "applications")
    rutas += [Path("/var/lib/flatpak/exports/share/applications"), Path("/var/lib/snapd/desktop/applications")]
    unicas = []
    for r in rutas:
        if r not in unicas:
            unicas.append(r)
    return unicas


def _idiomas() -> list[str]:
    lang = (os.environ.get("LANGUAGE") or os.environ.get("LANG") or locale.getlocale()[0] or "").split(":")[0]
    lang = lang.split(".")[0]
    return [x for x in (lang, lang.split("_")[0]) if x]


def leer_desktop(ruta: Path, id_: str) -> Aplicacion | None:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        cp.read_string(ruta.read_text(encoding="utf-8", errors="replace"))
    except (OSError, configparser.Error):
        return None
    if not cp.has_section("Desktop Entry"):
        return None
    e = cp["Desktop Entry"]
    if e.get("Type", "Application") != "Application" or e.get("Hidden", "").lower() == "true":
        return None
    if not e.get("Exec"):
        return None
    nombre = next((e.get(f"Name[{i}]") for i in _idiomas() if e.get(f"Name[{i}]")), None) or e.get("Name", id_)
    mimes = [m.strip() for m in e.get("MimeType", "").split(";") if m.strip()]
    app = Aplicacion(id_, nombre.strip(), e.get("Icon", "").strip(), ruta, mimes)
    app.oculta = e.get("NoDisplay", "").lower() == "true"     # type: ignore[attr-defined]
    return app


_cache: list[Aplicacion] | None = None


def todas(recargar: bool = False) -> list[Aplicacion]:
    """Todas las aplicaciones instaladas (una por id, gana la carpeta de mayor prioridad)."""
    global _cache
    if _cache is not None and not recargar:
        return _cache
    vistas: dict[str, Aplicacion | None] = {}
    for base in carpetas_aplicaciones():
        if not base.is_dir():
            continue
        for ruta in sorted(base.rglob("*.desktop")):
            id_ = str(ruta.relative_to(base)).replace("/", "-")
            if id_ in vistas:
                continue
            vistas[id_] = leer_desktop(ruta, id_)
    _cache = sorted((a for a in vistas.values() if a is not None), key=lambda a: a.nombre.lower())
    return _cache


def para_tipo(tipos: list[str]) -> list[Aplicacion]:
    """Aplicaciones que dicen poder abrir alguno de estos tipos (el tipo exacto primero, luego los «padres»)."""
    resultado, nombres = [], {}
    for t in tipos:
        for a in todas():
            if t not in a.mimes or a in resultado:
                continue
            previa = nombres.get(a.nombre.lower())
            if previa is not None:
                # la misma aplicación instalada dos veces (o un ayudante oculto): queda la visible
                if getattr(previa, "oculta", False) and not getattr(a, "oculta", False):
                    resultado[resultado.index(previa)] = a
                    nombres[a.nombre.lower()] = a
                continue
            nombres[a.nombre.lower()] = a
            resultado.append(a)
    return resultado


def predeterminada(tipo: str) -> str:
    """id del .desktop que el sistema usa para este tipo (o «»)."""
    if not shutil.which("xdg-mime"):
        return ""
    try:
        r = subprocess.run(["xdg-mime", "query", "default", tipo], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def poner_predeterminada(app: Aplicacion, tipo: str) -> None:
    r = subprocess.run(["xdg-mime", "default", app.id, tipo], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "No se pudo cambiar la aplicación predeterminada").strip())


def abrir_con(app: Aplicacion, rutas: list[str]) -> None:
    """Abre los archivos con esa aplicación (gio entiende los %f %u… del .desktop)."""
    subprocess.Popen(["gio", "launch", str(app.ruta), *rutas], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def abrir_predeterminada(ruta: str) -> bool:
    """Abre con la aplicación predeterminada del sistema (la misma que usa Archivos al hacer doble clic)."""
    for cmd in (["gio", "open", ruta], ["xdg-open", ruta]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
    return False
