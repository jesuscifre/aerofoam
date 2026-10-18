"""Dónde están los ficheros del programa y del usuario.

- Desde la carpeta de desarrollo (AeroFoam.bat / python main.py) todo está en esa carpeta,
  como siempre.
- Instalado (exe de PyInstaller), el programa es de solo lectura:
    configuración de máquina y recientes -> %APPDATA%\\AeroFoam
    proyectos y perfiles propios         -> Documentos\\AeroFoam
    catálogo de perfiles                 -> dentro del programa
"""
import os
import shutil
import sys
from pathlib import Path

INSTALADO = getattr(sys, "frozen", False)
CARPETA = Path(__file__).resolve().parent.parent   # carpeta de desarrollo


def _documentos():
    """Carpeta Documentos real (puede estar movida, p. ej. a OneDrive)."""
    try:
        import ctypes
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except (AttributeError, OSError):
        pass
    return Path.home() / "Documents"


if INSTALADO:
    RECURSOS = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    DATOS = Path(os.environ.get("APPDATA", Path.home())) / "AeroFoam"
    DOCUMENTOS = _documentos() / "AeroFoam"
    DIR_MIS_PERFILES = DOCUMENTOS / "perfiles"
else:
    RECURSOS = DATOS = DOCUMENTOS = CARPETA
    DIR_MIS_PERFILES = CARPETA / "perfiles"

DIR_CATALOGO = RECURSOS / "perfiles"
DIR_PROYECTOS = DOCUMENTOS / "proyectos"
MAQUINA_JSON = DATOS / "maquina.json"
RECIENTES_JSON = DATOS / "recientes.json"
MATERIALES_JSON = DATOS / "materiales.json"


NOMBRE_ANTERIOR = "Cortahilo"   # nombre de las primeras versiones: sus datos se copian la primera vez


def _migrar():
    """La primera vez, copia los datos de las carpetas del nombre anterior del programa."""
    for nueva, antigua in ((DATOS, DATOS.parent / NOMBRE_ANTERIOR),
                           (DOCUMENTOS, DOCUMENTOS.parent / NOMBRE_ANTERIOR)):
        if antigua.is_dir() and not nueva.exists():
            try:
                shutil.copytree(antigua, nueva)
            except OSError:
                pass


def preparar():
    """Crea las carpetas del usuario la primera vez."""
    if INSTALADO:
        _migrar()
    for d in (DATOS, DIR_PROYECTOS, DIR_MIS_PERFILES):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    if INSTALADO:
        leeme = DIR_MIS_PERFILES / "LEEME.txt"
        if not leeme.exists():
            try:
                leeme.write_text("Copia aquí tus perfiles .dat: aparecen en AeroFoam en la "
                                 "categoría 'Mis perfiles'.\n", encoding="utf-8")
            except OSError:
                pass
