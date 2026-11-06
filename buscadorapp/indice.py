"""Índice de archivos (SQLite + FTS5 trigram) y búsqueda instantánea por nombre."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

CATEGORIAS: dict[str, tuple[str, list[str]]] = {
    "todo": ("Todo", []),
    "carpetas": ("Carpetas", []),
    "documentos": ("Documentos", ["pdf", "doc", "docx", "odt", "rtf", "txt", "md", "xls", "xlsx", "xlsm", "ods", "csv",
                                  "ppt", "pptx", "odp", "xml", "json", "html", "htm", "epub", "tex"]),
    "imagenes": ("Imágenes", ["jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "tif", "tiff", "heic", "ico", "xcf",
                              "psd", "raw", "cr2", "nef", "avif"]),
    "audio": ("Audio", ["mp3", "wav", "flac", "ogg", "m4a", "aac", "wma", "opus", "mid", "midi"]),
    "video": ("Video", ["mp4", "mkv", "avi", "mov", "wmv", "webm", "flv", "m4v", "3gp", "mpg", "mpeg", "ts"]),
    "comprimidos": ("Comprimidos", ["zip", "rar", "7z", "tar", "gz", "xz", "bz2", "tgz", "zst", "iso", "deb", "rpm",
                                    "uaf"]),
    "codigo": ("Código", ["py", "js", "ts", "java", "c", "cpp", "h", "hpp", "cs", "php", "rb", "go", "rs", "sh",
                          "sql", "css", "kt", "swift", "lua", "pl", "r", "yml", "yaml", "toml", "ini"]),
    "ejecutables": ("Programas", ["exe", "msi", "appimage", "run", "bin", "jar", "deb", "rpm", "desktop", "bat"]),
}

ORDENES = {"nombre": "a.clave", "carpeta": "c.ruta", "tamano": "a.tamano", "fecha": "a.mtime", "tipo": "a.ext"}


def normalizar(texto: str) -> str:
    """minúsculas y sin tildes: «Factura Nº Ñandú.PDF» → «factura no nandu.pdf» (para buscar sin importar eso)."""
    t = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def extension(nombre: str) -> str:
    base = nombre.lstrip(".")
    return base.rsplit(".", 1)[1].lower() if "." in base else ""


# ---------------------------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------------------------
def carpeta_config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "buscador-agil"


def carpeta_datos() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "buscador-agil"


def ruta_indice() -> Path:
    return carpeta_datos() / "indice.db"


def excluidas_por_defecto() -> list[str]:
    casa = Path.home()
    return [str(casa / ".cache"), str(casa / ".local" / "share" / "Trash"), "/proc", "/sys", "/dev", "/run",
            "/tmp", "/snap", "/var/lib/snapd"]


@dataclass
class Config:
    carpetas: list[str] = field(default_factory=lambda: [str(Path.home())])
    excluir: list[str] = field(default_factory=excluidas_por_defecto)
    ocultos: bool = False                 # incluir archivos y carpetas que empiezan con «.»
    minutos_actualizar: int = 10          # cada cuánto se actualiza solo el índice (0 = nunca)

    @classmethod
    def cargar(cls) -> "Config":
        try:
            datos = json.loads((carpeta_config() / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        base = cls()
        for k, v in datos.items():
            if hasattr(base, k):
                setattr(base, k, v)
        return base

    def guardar(self) -> None:
        carpeta_config().mkdir(parents=True, exist_ok=True)
        (carpeta_config() / "config.json").write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1),
                                                     encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# Indexar
# ---------------------------------------------------------------------------------------------
ESQUEMA = """
CREATE TABLE carpetas (id INTEGER PRIMARY KEY, ruta TEXT NOT NULL);
CREATE TABLE archivos (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, clave TEXT NOT NULL, ext TEXT NOT NULL,
                       carpeta INTEGER NOT NULL, tamano INTEGER NOT NULL, mtime INTEGER NOT NULL,
                       es_dir INTEGER NOT NULL);
CREATE TABLE info (clave TEXT PRIMARY KEY, valor TEXT);
"""

Progreso = Callable[[int, str], None]


class Cancelado(Exception):
    pass


def indexar(config: Config, destino: Path | None = None, progreso: Progreso | None = None,
            cancelar: Callable[[], bool] | None = None) -> int:
    """Recorre las carpetas y escribe un índice nuevo; reemplaza el anterior solo al terminar bien."""
    destino = Path(destino or ruta_indice())
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".nuevo")
    temporal.unlink(missing_ok=True)
    con = sqlite3.connect(temporal)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + ESQUEMA)
    excluir = {os.path.normpath(e) for e in config.excluir}
    total = 0
    id_carpeta = 0
    lote_c, lote_a = [], []
    vistas: set[tuple[int, int]] = set()   # (dispositivo, inodo) para no repetir carpetas montadas dos veces

    def vaciar():
        con.executemany("INSERT INTO carpetas VALUES (?,?)", lote_c)
        con.executemany("INSERT INTO archivos VALUES (?,?,?,?,?,?,?,?)", lote_a)
        lote_c.clear()
        lote_a.clear()

    try:
        pila = [os.path.normpath(c) for c in config.carpetas if os.path.isdir(c)]
        while pila:
            ruta = pila.pop()
            if ruta in excluir:
                continue
            try:
                st = os.stat(ruta)
                if (st.st_dev, st.st_ino) in vistas:
                    continue
                vistas.add((st.st_dev, st.st_ino))
                entradas = list(os.scandir(ruta))
            except OSError:
                continue
            id_carpeta += 1
            lote_c.append((id_carpeta, ruta))
            for e in entradas:
                nombre = e.name
                if not config.ocultos and nombre.startswith("."):
                    continue
                if excluir and os.path.normpath(e.path) in excluir:
                    continue
                try:
                    es_dir = e.is_dir(follow_symlinks=False)
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                total += 1
                lote_a.append((total, nombre, normalizar(nombre), "" if es_dir else extension(nombre), id_carpeta,
                               0 if es_dir else st.st_size, int(st.st_mtime), 1 if es_dir else 0))
                if es_dir:
                    pila.append(e.path)
            if len(lote_a) >= 20000:
                vaciar()
                if cancelar and cancelar():
                    raise Cancelado()
                if progreso:
                    progreso(total, ruta)
        vaciar()
        if progreso:
            progreso(total, "Preparando la búsqueda rápida…")
        con.executescript("""
            CREATE VIRTUAL TABLE nombres USING fts5(clave, content='archivos', content_rowid='id',
                                                    tokenize='trigram');
            INSERT INTO nombres(rowid, clave) SELECT id, clave FROM archivos;
            CREATE INDEX i_ext ON archivos(ext);
        """)
        con.execute("INSERT INTO info VALUES ('fecha', ?), ('total', ?)", (str(int(time.time())), str(total)))
        con.commit()
        con.close()
        os.replace(temporal, destino)
    except BaseException:
        con.close()
        temporal.unlink(missing_ok=True)
        raise
    return total


# ---------------------------------------------------------------------------------------------
# Buscar
# ---------------------------------------------------------------------------------------------
@dataclass
class Resultado:
    nombre: str
    carpeta: str
    tamano: int
    mtime: int
    es_dir: bool

    @property
    def ruta(self) -> str:
        return os.path.join(self.carpeta, self.nombre)


def _escapar_like(t: str) -> str:
    return t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def interpretar(texto: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Convierte lo que escribe el usuario en condiciones.

    - palabras separadas por espacio: deben aparecer todas («factura enero»)
    - "entre comillas": la frase exacta, con espacios
    - comodines * y ?: «*.pdf», «foto??.jpg» (deben coincidir con el nombre completo)
    - ext:pdf  o  ext:pdf,docx: por extensión
    - texto con «/»: busca también en la carpeta («documentos/sri»)
    Devuelve ([(tipo, patrón LIKE)], [extensiones])."""
    condiciones, extensiones = [], []
    for m in re.finditer(r'"([^"]*)"|(\S+)', texto):
        palabra = m.group(1) if m.group(1) is not None else m.group(2)
        if not palabra:
            continue
        if m.group(2) and palabra.lower().startswith("ext:"):
            extensiones += [x.strip(". ").lower() for x in palabra[4:].split(",") if x.strip(". ")]
            continue
        clave = normalizar(palabra)
        if "/" in clave:
            # «sri/2026»: una carpeta que contenga «sri» y, más adentro, algo con «2026»
            condiciones.append(("ruta", "%" + "%/%".join(_escapar_like(p) for p in clave.split("/")) + "%"))
        elif m.group(2) and ("*" in clave or "?" in clave):
            condiciones.append(("nombre", _escapar_like(clave).replace("*", "%").replace("?", "_")))
        else:
            condiciones.append(("nombre", f"%{_escapar_like(clave)}%"))
    return condiciones, extensiones


class Buscador:
    def __init__(self, ruta: Path | None = None):
        self.ruta = Path(ruta or ruta_indice())
        self._con: sqlite3.Connection | None = None
        self._version = None

    def _conexion(self) -> sqlite3.Connection | None:
        try:
            st = self.ruta.stat()
        except OSError:
            return None
        version = (st.st_ino, st.st_mtime_ns)
        if self._con is None or version != self._version:      # el índice se reemplazó: abrir el nuevo
            if self._con is not None:
                self._con.close()
            self._con = sqlite3.connect(f"{self.ruta.as_uri()}?mode=ro", uri=True, check_same_thread=False)
            self._version = version
        return self._con

    def info(self) -> tuple[int, int]:
        """(elementos indexados, fecha del índice en segundos)."""
        con = self._conexion()
        if con is None:
            return 0, 0
        datos = dict(con.execute("SELECT clave, valor FROM info"))
        return int(datos.get("total", 0)), int(datos.get("fecha", 0))

    def buscar(self, texto: str, categoria: str = "todo", orden: str = "nombre", descendente: bool = False,
               limite: int = 2000) -> tuple[list[Resultado], int]:
        con = self._conexion()
        if con is None:
            return [], 0
        condiciones, extensiones = interpretar(texto)
        donde, params = [], []
        usa_fts = any(t == "nombre" for t, _ in condiciones)
        for tipo, patron in condiciones:
            if tipo == "ruta":
                donde.append("(lower(c.ruta) || '/' || a.clave) LIKE ? ESCAPE '\\'")
            else:
                donde.append("n.clave LIKE ? ESCAPE '\\'")
            params.append(patron)
        if categoria == "carpetas":
            donde.append("a.es_dir = 1")
        elif categoria in CATEGORIAS and CATEGORIAS[categoria][1]:
            extensiones = extensiones + CATEGORIAS[categoria][1] if not extensiones else \
                [e for e in extensiones if e in CATEGORIAS[categoria][1]] or ["\0"]
        if extensiones:
            donde.append(f"a.ext IN ({','.join('?' * len(extensiones))})")
            params += extensiones
        origen = ("nombres n JOIN archivos a ON a.id = n.rowid" if usa_fts else "archivos a") + \
            " JOIN carpetas c ON c.id = a.carpeta"
        filtro = (" WHERE " + " AND ".join(donde)) if donde else ""
        columna = ORDENES.get(orden, "a.clave")
        sentido = "DESC" if descendente else "ASC"
        filas = con.execute(f"SELECT a.nombre, c.ruta, a.tamano, a.mtime, a.es_dir FROM {origen}{filtro} "
                            f"ORDER BY {columna} {sentido}, a.clave LIMIT ?", params + [limite]).fetchall()
        if len(filas) < limite:
            total = len(filas)
        else:
            total = con.execute(f"SELECT count(*) FROM {origen}{filtro}", params).fetchone()[0]
        return [Resultado(n, c, t, m, bool(d)) for n, c, t, m, d in filas], total

    def quitar(self, rutas: list[str]) -> int:
        """Saca del índice estos archivos o carpetas (y todo lo que haya dentro de las carpetas).
        Se usa al eliminar desde el programa o al notar que algo ya no existe, sin esperar a reindexar."""
        if not rutas or not self.ruta.exists():
            return 0
        con = sqlite3.connect(self.ruta, timeout=5)
        try:
            ids = []
            for ruta in rutas:
                ruta = os.path.normpath(ruta)
                carpeta, nombre = os.path.split(ruta)
                ids += [r[0] for r in con.execute(
                    "SELECT a.id FROM archivos a JOIN carpetas c ON c.id = a.carpeta WHERE c.ruta = ? AND a.nombre = ?",
                    (carpeta, nombre))]
                patron = _escapar_like(ruta) + "/%"
                ids += [r[0] for r in con.execute(
                    "SELECT a.id FROM archivos a JOIN carpetas c ON c.id = a.carpeta "
                    "WHERE c.ruta = ? OR c.ruta LIKE ? ESCAPE '\\'", (ruta, patron))]
            ids = sorted(set(ids))
            for i in range(0, len(ids), 500):
                trozo = ids[i:i + 500]
                marcas = ",".join("?" * len(trozo))
                # el índice de búsqueda rápida necesita el valor viejo para borrarlo
                con.execute(f"INSERT INTO nombres(nombres, rowid, clave) SELECT 'delete', id, clave FROM archivos "
                            f"WHERE id IN ({marcas})", trozo)
                con.execute(f"DELETE FROM archivos WHERE id IN ({marcas})", trozo)
            if ids:
                con.execute("UPDATE info SET valor = CAST(valor AS INTEGER) - ? WHERE clave = 'total'", (len(ids),))
            con.commit()
            return len(ids)
        finally:
            con.close()
