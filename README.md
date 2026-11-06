# Buscador Ágil

Encuentra cualquier archivo o carpeta de Linux **al instante mientras escribe**, como *Everything* en Windows.

- Guarda los nombres de sus archivos en un índice (SQLite con búsqueda por trigramas) que se actualiza solo.
- Búsqueda sin importar mayúsculas ni tildes: `cancion` encuentra «Canción.mp3».
- Varias palabras (`factura enero`), frase exacta (`"estado de cuenta"`), comodines (`*.pdf`, `foto??.jpg`),
  por extensión (`ext:xlsx,csv`) y por carpeta (`sri/2026`).
- Filtros: Carpetas, Documentos, Imágenes, Audio, Video, Comprimidos, Código, Programas.
- Doble clic o Enter abre; clic derecho: abrir carpeta contenedora, copiar para pegar, copiar ruta, papelera.
  Se puede arrastrar un resultado a otra ventana.
- Atajo de teclado global opcional (Ctrl+Alt+B) para abrirlo desde cualquier lugar.

## Instalar

Descargue el `.deb` de la página **Releases** y ábralo con doble clic (o `sudo apt install ./buscador-agil_*.deb`).

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/buscadorapp
.venv/bin/python -m pytest -q
.venv/bin/python empaquetar/construir_deb.py     # instalador .deb en dist/
```
