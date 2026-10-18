"""Red de vórtices (Vortex Lattice Method) lineal para el ala y la cola.

Cada superficie se divide en paneles con un vórtice en herradura (segmento ligado en el 25% del
panel y dos estelas rectas hacia atrás); en el 75% de cada panel el flujo no puede atravesar la
superficie. Resolviendo eso salen la sustentación y el momento de todo el avión a la vez, con la
estela del ala sobre la cola, el diedro, la flecha y la cola en V tal cual.
Coordenadas: x hacia atrás, y a la derecha, z arriba (mm).
"""
import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Panel:
    """Una mitad de superficie (o la deriva)."""
    x_ba: float          # borde de ataque de la raíz
    y0: float
    z0: float
    cuerda_raiz: float
    cuerda_punta: float
    largo: float         # a lo largo del panel
    flecha: float        # desplazamiento del BA de la punta hacia atrás
    diedro: float        # grados (90 = vertical)
    lado: int = 1        # 1 derecha, -1 izquierda


NS, NC = 16, 8           # paneles a lo largo y a lo ancho de cada mitad


def malla(p, ns=None, nc=None):
    """Vértices de los vórtices (A, B), puntos de control y normales de un panel."""
    ns, nc = ns or NS, nc or NC
    s = p.largo * (1 - np.cos(np.linspace(0, np.pi, ns + 1))) / 2    # más denso en raíz y punta
    g = math.radians(p.diedro)
    c = p.cuerda_raiz + (p.cuerda_punta - p.cuerda_raiz) * s / p.largo
    xba = p.x_ba + p.flecha * s / p.largo
    y = p.y0 + p.lado * s * math.cos(g)
    z = p.z0 + s * math.sin(g)
    f = np.linspace(0, 1, nc + 1)
    # rejilla (nc+1) x (ns+1) de puntos de la superficie
    X = xba[None, :] + f[:, None] * c[None, :]
    Y = np.broadcast_to(y, X.shape)
    Z = np.broadcast_to(z, X.shape)
    P = np.stack([X, Y, Z], axis=-1)
    a, b = [], []
    cp, n = [], []
    for i in range(nc):
        for j in range(ns):
            p00, p01, p10, p11 = P[i, j], P[i, j + 1], P[i + 1, j], P[i + 1, j + 1]
            A = p00 + 0.25 * (p10 - p00)
            B = p01 + 0.25 * (p11 - p01)
            if p.lado < 0:           # el vórtice siempre de izquierda a derecha (sentido +y)
                A, B = B, A
            C = 0.5 * ((p00 + 0.75 * (p10 - p00)) + (p01 + 0.75 * (p11 - p01)))
            nv = np.cross(p11 - p00, p01 - p10)
            nv = nv / np.linalg.norm(nv)
            if nv[2] < 0 or (abs(nv[2]) < 1e-9 and nv[1] * p.lado < 0):
                nv = -nv
            a.append(A), b.append(B), cp.append(C), n.append(nv)
    return np.array(a), np.array(b), np.array(cp), np.array(n)


def _segmento(P, A, B):
    """Velocidad inducida en P (M,3) por segmentos A->B (N,3) de circulación 1."""
    r1 = P[:, None, :] - A[None, :, :]
    r2 = P[:, None, :] - B[None, :, :]
    c = np.cross(r1, r2)
    c2 = np.einsum("ijk,ijk->ij", c, c)
    n1, n2 = np.linalg.norm(r1, axis=2), np.linalg.norm(r2, axis=2)
    r0 = (B - A)[None, :, :]
    k = np.einsum("ijk,ijk->ij", r0, r1 / n1[..., None] - r2 / n2[..., None])
    with np.errstate(divide="ignore", invalid="ignore"):
        v = c * (k / (4 * np.pi * c2))[..., None]
    v[~np.isfinite(v)] = 0.0
    v[c2 < 1e-10] = 0.0
    return v


def _semiinfinito(P, A):
    """Velocidad inducida en P por una línea de vórtice que sale de A hacia +x (al infinito), Γ=1."""
    r = P[:, None, :] - A[None, :, :]
    d = np.array([1.0, 0.0, 0.0])
    c = np.cross(np.broadcast_to(d, r.shape), r)
    c2 = np.einsum("ijk,ijk->ij", c, c)
    nr = np.linalg.norm(r, axis=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = c * ((1 + r[..., 0] / nr) / (4 * np.pi * c2))[..., None]
    v[~np.isfinite(v)] = 0.0
    v[c2 < 1e-10] = 0.0
    return v


def resolver(paneles, S, c_ref, x_ref, alfa=math.radians(1)):
    """CLα (1/rad) y punto neutro (x) de un conjunto de paneles, con referencia S y c_ref (mm)."""
    datos = [malla(p) for p in paneles]
    A = np.vstack([d[0] for d in datos])
    B = np.vstack([d[1] for d in datos])
    C = np.vstack([d[2] for d in datos])
    N = np.vstack([d[3] for d in datos])
    # herradura: estela que llega a A (desde el infinito), ligado A->B, estela que sale de B
    v = _segmento(C, A, B) + _semiinfinito(C, B) - _semiinfinito(C, A)
    M = np.einsum("ijk,ik->ij", v, N)
    Vinf = np.array([math.cos(alfa), 0.0, math.sin(alfa)])
    gam = np.linalg.solve(M, -N @ Vinf)
    l = B - A
    F = gam[:, None] * np.cross(np.broadcast_to(Vinf, l.shape), l)   # ρ = V = 1
    medio = 0.5 * (A + B)
    sust = F @ np.array([-math.sin(alfa), 0.0, math.cos(alfa)])
    cl = 2 * sust.sum() / S                                           # q = 1/2
    cm = -2 * np.sum((medio[:, 0] - x_ref) * F[:, 2]) / (S * c_ref)
    return cl / alfa, x_ref - c_ref * cm / cl


def paneles_avion(p, incluir_cola=True):
    """Paneles del ala (dos mitades) y de la cola horizontal o en V, como en el montaje."""
    av = p.avion
    a = p.ala
    res = []
    for lado in (1, -1):
        res.append(Panel(av.x_ala, lado * av.separacion_raices / 2, av.z_ala, a.cuerda_raiz, a.cuerda_punta,
                         a.envergadura, a.flecha, av.diedro_ala, lado))
    if incluir_cola and av.tipo_cola in ("convencional", "v"):
        e = p.estabilizador
        ang = av.angulo_v if av.tipo_cola == "v" else 0.0
        for lado in (1, -1):
            res.append(Panel(av.x_estab, 0.0, av.z_estab, e.cuerda_raiz, e.cuerda_punta, e.envergadura,
                             e.flecha, ang, lado))
    return res
