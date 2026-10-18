# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: genera instalador/dist/AeroFoam (carpeta con AeroFoam.exe y todo lo necesario).
# Se usa desde herramientas/crear_instalador.bat
import os

raiz = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(raiz, "main.py")],
    pathex=[raiz],
    datas=[
        (os.path.join(raiz, "perfiles", "*.dat"), "perfiles"),
        (os.path.join(raiz, "perfiles", "catalogo.json"), "perfiles"),
        (os.path.join(raiz, "aerofoam", "aerofoam.ico"), "."),
    ],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "jupyter", "notebook", "pytest",
              "PyInstaller", "pip", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AeroFoam",
    icon=os.path.join(SPECPATH, "aerofoam.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AeroFoam")
