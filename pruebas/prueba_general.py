"""Pruebas generales de AeroFoam. Uso:  python pruebas/prueba_general.py  [--sin-interfaz]

Comprueba el catálogo de perfiles, la geometría de corte, el G-code, los fuselajes, el cálculo del
avión, la calibración, el guardado de proyectos y (si no se pasa --sin-interfaz) que la interfaz abre.
"""
import json
import math
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aerofoam.aero import calcular_avion                       # noqa: E402
from aerofoam.calibracion import gcode_calibracion             # noqa: E402
from aerofoam.fuselaje import piezas                           # noqa: E402
from aerofoam.gcode import generar                             # noqa: E402
from aerofoam.geometria import calcular                        # noqa: E402
from aerofoam.perfiles import interpolar, leer_dat, listar     # noqa: E402
from aerofoam.proyecto import Maquina, Proyecto, Varilla, proyecto_desde_dict   # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
fallos = []


def comprobar(condicion, mensaje):
    if not condicion:
        fallos.append(mensaje)


def cruces(P):
    """Número de cruces de una polilínea consigo misma."""
    def cr(u, v):
        return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]
    A, B, n = P[:-1], P[1:], 0
    for i in range(len(A)):
        a, b, Aj, Bj = A[i], B[i], A[i + 2:], B[i + 2:]
        if i == 0:
            Aj, Bj = Aj[:-1], Bj[:-1]
        n += np.sum((cr(b - a, Aj - a) * cr(b - a, Bj - a) < 0) & (cr(Bj - Aj, a - Aj) * cr(Bj - Aj, b - Aj) < 0))
    return n


def maquina():
    return Maquina(distancia_torres=800.0, recorrido_x=900.0, vel_max=300.0, eje3="A", eje4="Z")


def prueba_catalogo():
    datos = json.loads((RAIZ / "perfiles" / "catalogo.json").read_text(encoding="utf-8"))["perfiles"]
    lista = listar()
    comprobar(len(datos) >= 130, f"el catálogo tiene {len(datos)} perfiles")
    for k, d in datos.items():
        comprobar(k in lista, f"{k}: está en el catálogo pero falta el .dat")
        sup, inf = leer_dat(RAIZ / "perfiles" / f"{k}.dat")[1]
        x = np.linspace(0, 1, 1001)
        e = interpolar(sup, x) - interpolar(inf, x)
        comprobar(abs(e.max() * 100 - d["espesor"]) < 0.2, f"{k}: espesor distinto del catálogo")
        comprobar(e.min() > -1e-4, f"{k}: el extradós cruza el intradós")
    return len(datos)


def prueba_alas():
    m = maquina()
    for k in listar():
        for kerf, aleron in ((0.0, False), (1.2, True)):
            p = Proyecto()
            a = p.ala
            a.perfil_raiz = a.perfil_punta = k
            a.cuerda_punta, a.torsion_punta = 150.0, 2.0
            a.varillas = [Varilla("C", pos_raiz=60, pos_punta=45)]
            a.aleron.activo, a.aleron.cuerda_raiz, a.aleron.cuerda_punta = aleron, 55.0, 40.0
            p.corte.kerf_raiz = p.corte.kerf_punta = kerf
            try:
                r = calcular(p, m)
                generar(r, p, m)
            except Exception as e:  # noqa: BLE001
                fallos.append(f"{k} (kerf {kerf}): {e}")
                continue
            for cara in (r.raiz, r.punta):
                P = cara[3:-3][np.isin(np.array(r.tipos[3:-3]), ["corte", "aleron"])]
                P = P[np.r_[True, np.hypot(*np.diff(P, axis=0).T) > 1e-9]]
                comprobar(cruces(P) == 0, f"{k} (kerf {kerf}): el recorrido se cruza")


def prueba_gcode():
    m = maquina()
    p = Proyecto()
    p.ala.varillas = [Varilla("C")]
    p.corte.pausa_varillas = 0.5
    for modo in ("f_bruto", "cara_rapida", "g93"):
        p.corte.modo_velocidad = modo
        r = calcular(p, m)
        g, info = generar(r, p, m)
        comprobar(g.isascii(), f"{modo}: el G-code no es ASCII")
        for linea in g.splitlines():
            ok = linea.startswith(("(", "G1 ", "G4 ", "G21", "G90", "G93", "G94", "M2", "M3", "M5"))
            comprobar(ok, f"{modo}: línea inesperada '{linea}'")
        movs = [l for l in g.splitlines() if l.startswith("G1")]
        comprobar(all(re.search(r" X[-\d.]+ Y[-\d.]+ A[-\d.]+ Z[-\d.]+", l) for l in movs), f"{modo}: ejes mal")
        comprobar(np.all(np.diff(info["llegada"]) >= -1e-12), f"{modo}: tiempos no crecientes")
    # F tal cual
    p.corte.modo_velocidad, p.corte.vel_corte = "f_bruto", 50.0
    g, _ = generar(calcular(p, m), p, m)
    comprobar("F50.0" in g, "con F sin corregir y 50 no aparece F50")


def prueba_fuselajes():
    m = maquina()
    for metodo, pared in (("silueta", 0.0), ("tramos", 0.0), ("tramos", 6.0)):
        p = Proyecto()
        p.pieza, p.fuselaje.metodo, p.fuselaje.pared = "fuselaje", metodo, pared
        for et, res, _ in piezas(p, m):
            comprobar(min(res.xy[:, 1].min(), res.za[:, 1].min()) >= -1e-6, f"fuselaje {et}: torre bajo el cero")
            generar(res, p, m, "f", "fuselaje")


def prueba_avion():
    referencias = {"convencional": 329.6, "v": 319.4}      # puntos neutros de referencia (mm)
    for tipo, ref in referencias.items():
        p = Proyecto()
        p.avion.tipo_cola, p.avion.con_fuselaje, p.avion.peso, p.avion.cg = tipo, False, 400, 300
        p.ala.perfil_raiz = p.ala.perfil_punta = "NACA 2412"
        p.ala.cuerda_raiz, p.ala.cuerda_punta, p.ala.envergadura = 250, 180, 500
        p.estabilizador.cuerda_raiz, p.estabilizador.cuerda_punta = 130, 90
        p.estabilizador.envergadura, p.estabilizador.flecha = 260, 20
        p.avion.x_estab, p.avion.z_estab, p.avion.diedro_ala = 700, 10, 2
        r = calcular_avion(p)
        comprobar(abs(r.x_np - ref) / r.ala.cma < 0.03, f"punto neutro {tipo}: {r.x_np:.1f} (ref. {ref})")
    p = Proyecto()
    p.avion.tipo_cola = "sin_cola"
    r = calcular_avion(p)
    comprobar(math.isfinite(r.x_np) and r.lineas, "ala volante sin resultados")


def prueba_calibracion():
    m = maquina()
    g, _ = gcode_calibracion(m, Proyecto().corte, [30, 40, 50], literal=True)
    fs = {float(x) for x in re.findall(r"F([\d.]+)", g)}
    comprobar({30.0, 40.0, 50.0} <= fs, "la calibración no usa la F tal cual")


def prueba_proyecto():
    p = Proyecto()
    p.ala.varillas.append(Varilla("Extra"))
    p.ala.aleron.activo = True
    p.avion.componentes[0].masa = 77
    q = proyecto_desde_dict(json.loads(json.dumps(asdict(p))))
    comprobar(q == p, "el proyecto cambia al guardarlo y cargarlo")
    comprobar(proyecto_desde_dict({"ala": {}}).pieza == "ala", "no abre proyectos antiguos")


def prueba_interfaz():
    from aerofoam import gui
    app = gui.App()
    app.update()
    campo = next(c for c in app.form.campos if c["attr"] == "pieza")
    for nombre in gui.PIEZAS.values():
        campo["var"].set(nombre)
        app._confirmar_pendiente()
        app.update()
        texto = app.estado.get("1.0", "end")
        comprobar("Error" not in texto, f"interfaz, pieza '{nombre}': {texto.strip()[:80]}")
    app.destroy()


if __name__ == "__main__":
    pruebas = [("catálogo de perfiles", prueba_catalogo), ("alas con todos los perfiles", prueba_alas),
               ("G-code", prueba_gcode), ("fuselajes", prueba_fuselajes), ("avión", prueba_avion),
               ("calibración", prueba_calibracion), ("guardar y cargar", prueba_proyecto)]
    if "--sin-interfaz" not in sys.argv:
        pruebas.append(("interfaz", prueba_interfaz))
    for nombre, f in pruebas:
        t, antes = time.time(), len(fallos)
        f()
        print(f"{'OK   ' if len(fallos) == antes else 'FALLO'} {nombre} ({time.time() - t:.1f} s)")
    print()
    for f in fallos[:30]:
        print("  -", f)
    print("Todo correcto." if not fallos else f"{len(fallos)} fallos.")
    sys.exit(1 if fallos else 0)
