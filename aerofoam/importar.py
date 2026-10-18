"""Importación de formas: contornos desde DXF y mallas desde STL."""
import struct
from pathlib import Path

import numpy as np

from .geometria import ErrorGeometria


# ---------------------------------------------------------------- DXF
def contorno_dxf(ruta, escala=1.0):
    """Contorno cerrado más grande del DXF (polilíneas, líneas, arcos, círculos, splines...).
    Une los trozos cuyos extremos coinciden. Devuelve un array Nx2 en mm."""
    try:
        import ezdxf
        from ezdxf import path as ezpath
    except ImportError:
        raise ErrorGeometria("Falta la librería ezdxf para leer DXF (pip install ezdxf).")
    try:
        doc = ezdxf.readfile(str(ruta))
    except (IOError, ezdxf.DXFStructureError) as e:
        raise ErrorGeometria(f"No se pudo leer el DXF: {e}")
    trozos = []
    for e in doc.modelspace():
        try:
            camino = ezpath.make_path(e)
        except (TypeError, ValueError, AttributeError):
            continue  # textos, cotas, etc.
        for sub in camino.sub_paths():
            pts = np.array([(v.x, v.y) for v in sub.flattening(distance=0.05)], float)
            if len(pts) >= 2:
                trozos.append(pts)
    if not trozos:
        raise ErrorGeometria("El DXF no tiene líneas ni curvas.")
    lazos = _unir(trozos, tol=0.05 * max(1.0, _tamano(trozos)) / 100)
    if not lazos:
        raise ErrorGeometria("No encuentro ningún contorno cerrado en el DXF.")
    lazo = max(lazos, key=lambda P: abs(_area(P)))
    return lazo * escala


def _tamano(trozos):
    todos = np.vstack(trozos)
    return float(np.ptp(todos, axis=0).max())


def _area(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _unir(trozos, tol):
    """Encadena trozos abiertos en lazos cerrados (extremos que coinciden dentro de tol)."""
    lazos, abiertos = [], []
    for t in trozos:
        if np.hypot(*(t[0] - t[-1])) <= tol and len(t) > 3:
            lazos.append(t[:-1])
        else:
            abiertos.append(t)
    # índice de extremos por celdas de tamaño tol (se miran las celdas vecinas)
    celdas = {}

    def clave(p):
        return int(np.floor(p[0] / tol)), int(np.floor(p[1] / tol))

    for i, t in enumerate(abiertos):
        for lado, p in ((0, t[0]), (1, t[-1])):
            celdas.setdefault(clave(p), []).append((i, lado))

    def buscar(p, usados):
        cx, cy = clave(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i, lado in celdas.get((cx + dx, cy + dy), ()):
                    if i not in usados:
                        q = abiertos[i][0] if lado == 0 else abiertos[i][-1]
                        if np.hypot(*(p - q)) <= tol:
                            return i, lado
        return None

    usados = set()
    for inicio in range(len(abiertos)):
        if inicio in usados:
            continue
        usados.add(inicio)
        cad = [abiertos[inicio]]
        while True:
            fin = cad[-1][-1]
            if np.hypot(*(fin - cad[0][0])) <= tol and sum(len(c) for c in cad) > 3:
                break
            sig = buscar(fin, usados)
            if sig is None:
                break
            i, lado = sig
            usados.add(i)
            t = abiertos[i] if lado == 0 else abiertos[i][::-1]
            cad.append(t[1:])
        P = np.vstack(cad)
        if np.hypot(*(P[0] - P[-1])) <= tol and len(P) > 3:
            lazos.append(P[:-1])
    return lazos


# ---------------------------------------------------------------- STL
EJES = {"X": 0, "Y": 1, "Z": 2}


def cargar_stl(ruta, eje_largo="X", eje_arriba="Z", escala=1.0):
    """Triángulos (T, 3, 3) con el eje largo del fuselaje en x (empezando en 0, el morro en el
    lado de x más pequeña), el lateral en y (centrado) y la altura en z."""
    datos = Path(ruta).read_bytes()
    tri = None
    if len(datos) >= 84:
        n = struct.unpack("<I", datos[80:84])[0]
        if 84 + n * 50 == len(datos):  # binario
            reg = np.frombuffer(datos, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                                count=n, offset=84)
            tri = reg["v"].astype(float)
    if tri is None:  # ASCII
        texto = datos.decode("latin-1")
        v = [list(map(float, l.split()[1:4])) for l in texto.splitlines() if l.strip().startswith("vertex")]
        if len(v) < 3:
            raise ErrorGeometria("El fichero no parece un STL válido.")
        tri = np.array(v, float)[: len(v) // 3 * 3].reshape(-1, 3, 3)
    il, ia = EJES[eje_largo], EJES[eje_arriba]
    if il == ia:
        raise ErrorGeometria("El eje largo y el eje de arriba del STL deben ser distintos.")
    ilat = 3 - il - ia
    tri = tri[:, :, [il, ilat, ia]] * escala
    tri[:, :, 0] -= tri[:, :, 0].min()
    tri[:, :, 1] -= (tri[:, :, 1].min() + tri[:, :, 1].max()) / 2
    return tri


def seccion_stl(tri, x):
    """Lazo cerrado (y, z) más grande del corte de la malla por el plano x."""
    d = tri[:, :, 0] - x
    d = np.where(d == 0, 1e-9, d)       # ningún vértice justo en el plano
    cruza = (d.min(axis=1) < 0) & (d.max(axis=1) > 0)
    t, dd = tri[cruza], d[cruza]
    puntos, marcas = [], []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        with np.errstate(divide="ignore", invalid="ignore"):  # aristas que no cortan: se descartan
            f = dd[:, i] / (dd[:, i] - dd[:, j])
        puntos.append(t[:, i, 1:] + f[:, None] * (t[:, j, 1:] - t[:, i, 1:]))
        marcas.append((dd[:, i] < 0) != (dd[:, j] < 0))
    puntos, marcas = np.stack(puntos, 1), np.stack(marcas, 1)      # (T, 3, 2), (T, 3)
    orden = np.argsort(~marcas, axis=1, kind="stable")[:, :2]      # las dos aristas cortadas
    segs = list(np.take_along_axis(puntos, orden[:, :, None], axis=1))
    if not segs:
        raise ErrorGeometria(f"El STL no tiene sección en x = {x:.1f} mm.")
    lazos = _unir(segs, tol=1e-4 * max(1.0, float(np.ptp(tri[:, :, 1:]))))
    if not lazos:
        raise ErrorGeometria(f"La sección del STL en x = {x:.1f} mm no está cerrada (¿malla con agujeros?).")
    return max(lazos, key=lambda P: abs(_area(P)))


def muestrear_angulos(P, n, centro=None):
    """n puntos del contorno P a ángulos iguales alrededor del centro, empezando por la izquierda
    (ángulo 180°) y en sentido antihorario. Para formas sin entrantes, como las cuadernas."""
    if centro is None:
        centro = (P.min(axis=0) + P.max(axis=0)) / 2
    Q = np.vstack([P, P[:1]]) - centro
    a, b = Q[:-1], Q[1:]
    out = np.empty((n, 2))
    for k, ang in enumerate(np.pi + 2 * np.pi * np.arange(n) / n):
        u = np.array([np.cos(ang), np.sin(ang)])
        e = b - a
        den = u[0] * e[:, 1] - u[1] * e[:, 0]
        ok = np.abs(den) > 1e-12
        t = np.where(ok, (a[:, 0] * e[:, 1] - a[:, 1] * e[:, 0]) / np.where(ok, den, 1), -1)
        s = np.where(ok, (a[:, 0] * u[1] - a[:, 1] * u[0]) / np.where(ok, den, 1), -1)
        valido = ok & (t > 0) & (s >= 0) & (s <= 1)
        r = t[valido].max() if valido.any() else 0.0
        out[k] = centro + r * u
    return out


def silueta_stl(tri, vista, n=160):
    """Silueta lateral ('lateral': x-z) o en planta ('planta': x-y) a partir de cortes."""
    L = tri[:, :, 0].max()
    xs = np.linspace(L * 0.002, L * 0.998, n)
    col = 2 if vista == "lateral" else 1
    arriba, abajo, xv = [], [], []
    for x in xs:
        try:
            s = seccion_stl(tri, x)
        except ErrorGeometria:
            continue
        xv.append(x)
        abajo.append(s[:, col - 1].min())
        arriba.append(s[:, col - 1].max())
    if len(xv) < 5:
        raise ErrorGeometria("No se ha podido sacar la silueta del STL.")
    xv, ab, ar = map(np.array, (xv, abajo, arriba))
    morro = np.array([[0.0, (ab[0] + ar[0]) / 2]])
    return np.vstack([morro, np.column_stack([xv, ab]), np.column_stack([xv, ar])[::-1]])
