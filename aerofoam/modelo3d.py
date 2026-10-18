"""Modelo 3D de lo que sale del corte, para verlo antes de cortar.

Cada parte es un par de contornos (uno en cada extremo) con el mismo número de puntos:
la superficie es la que deja el hilo al unir el punto i de un extremo con el i del otro.
Coordenadas de dibujo: (a lo largo, ancho, alto).
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class Parte:
    a: np.ndarray            # contorno (N, 3) de un extremo
    b: np.ndarray            # contorno (N, 3) del otro
    color: str
    tapas: bool = True       # cerrar los extremos
    alfa: float = 1.0


def _cerrar(P):
    return np.vstack([P, P[:1]])


def partes_ala(p, res):
    """Panel del ala que sale del corte (contorno del hilo, sin entrada ni salida)."""
    c, a = p.corte, p.ala
    d, L = c.dist_torre_bloque, a.envergadura
    s_r, s_t = (d, d + L) if a.raiz_lado == "XY" else (d + L, d)
    R, T = res.raiz[3:-3], res.punta[3:-3]
    def en3d(P, s):
        return np.column_stack([np.full(len(P), s), P[:, 0], P[:, 1]])
    return [Parte(en3d(R, s_r), en3d(T, s_t), "#7fa8dc")]


def partes_fuselaje(piezas, elegida):
    """Fuselaje entero montado con todos sus tramos (el elegido resaltado), o la silueta extruida."""
    partes = []
    for k, (_, res, _) in enumerate(piezas):
        ex = res.extra
        if "silueta" in ex:
            S, e = ex["silueta"], ex["espesor"] / 2
            if ex["vista"] == "lateral":   # (x, alto) -> grosor en el ancho
                a = np.column_stack([S[:, 0], np.full(len(S), -e), S[:, 1]])
                b = np.column_stack([S[:, 0], np.full(len(S), e), S[:, 1]])
            else:                          # (x, ancho) -> grosor en el alto
                a = np.column_stack([S[:, 0], S[:, 1], np.full(len(S), -e)])
                b = np.column_stack([S[:, 0], S[:, 1], np.full(len(S), e)])
            partes.append(Parte(a, b, "#ffb347"))
            continue
        x1, x2 = ex["x1"], ex["x2"]
        color = "#ffb347" if k == elegida else "#a9c4e8"
        def en3d(P, x):
            return np.column_stack([np.full(len(P), x), P[:, 0], P[:, 1]])
        hueco = ex["hueco"]
        partes.append(Parte(en3d(ex["a"], x1), en3d(ex["b"], x2), color, tapas=hueco is None))
        if hueco is not None:
            partes.append(Parte(en3d(hueco[0], x1), en3d(hueco[1], x2), "#6b6b6b", tapas=False))
            # aros de los extremos (pared) para que se vea el grosor
            for P, H, x in ((ex["a"], hueco[0], x1), (ex["b"], hueco[1], x2)):
                partes.append(Parte(en3d(P, x), en3d(H, x), color, tapas=False))
    return partes


def caja(partes):
    todos = np.vstack([np.vstack([q.a, q.b]) for q in partes])
    return todos.min(axis=0), todos.max(axis=0)


def a_stl(partes, ruta):
    """Guarda las partes como STL (ASCII) para verlas en cualquier visor 3D."""
    lineas = ["solid aerofoam"]

    def tri(p, q, r):
        n = np.cross(q - p, r - p)
        n = n / (np.linalg.norm(n) or 1)
        lineas.append(f"facet normal {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n outer loop")
        for v in (p, q, r):
            lineas.append(f"  vertex {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")
        lineas.append(" endloop\nendfacet")

    for q in partes:
        A, B = _cerrar(q.a), _cerrar(q.b)
        for i in range(len(A) - 1):
            tri(A[i], B[i], B[i + 1])
            tri(A[i], B[i + 1], A[i + 1])
        if q.tapas:
            for P, invertir in ((q.a, True), (q.b, False)):
                c = P.mean(axis=0)
                for i in range(len(P)):
                    u, v = P[i], P[(i + 1) % len(P)]
                    tri(c, v, u) if invertir else tri(c, u, v)
    lineas.append("endsolid aerofoam")
    with open(ruta, "w", encoding="ascii") as fh:
        fh.write("\n".join(lineas) + "\n")
