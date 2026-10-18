"""Aprovechamiento del bloque: comprueba si caben dos alas cortadas desde extremos opuestos.

El ala 1 se corta con el cero en la esquina inferior izquierda del bloque. Para el
ala 2 se gira el bloque 180° (alrededor del hilo) y se corta igual, con el cero en
la esquina que ha quedado abajo: vista en el bloque sin girar, el ala 2 está boca
abajo y el hilo entra por la esquina superior del otro extremo. Al ser un giro (no
un espejo), con los mismos datos el ala 2 es igual que el ala 1.
Es solo informativo: el ala 2 no genera G-code.
"""
from dataclasses import dataclass, field

import numpy as np

from .geometria import ErrorGeometria, calcular
from .proyecto import proyecto_ala2


@dataclass
class ResultadoBloque:
    caras: dict                 # {1: {"A": trayectoria, "B": ...}, 2: {...}} en el sistema del bloque
    material: dict              # {"A": mm de corcho entre los dos cortes, "B": ...}
    avisos: list = field(default_factory=list)


def _en_cara(res, s, W):
    """Trayectoria del hilo a una distancia s de la torre 1."""
    return res.xy + (res.za - res.xy) * s / W


def _densificar(P, paso=0.5):
    trozos = [P[:1]]
    for a, b in zip(P[:-1], P[1:]):
        n = max(1, int(np.ceil(np.hypot(*(b - a)) / paso)))
        trozos.append(a + (b - a) * (np.arange(1, n + 1) / n)[:, None])
    return np.vstack(trozos)


def _distancia(P, Q):
    P, Q = _densificar(P), _densificar(Q)
    d = np.inf
    for i in range(0, len(P), 500):
        bloque = P[i:i + 500]
        d = min(d, np.sqrt(((bloque[:, None, :] - Q[None, :, :]) ** 2).sum(-1)).min())
    return d


def calcular_bloque(p, m, res1, con_ala2=True):
    """Coloca el ala 1 (ya calculada) y, si se pide, el ala 2 en el bloque."""
    c = p.corte
    W = m.distancia_torres
    d = c.dist_torre_bloque
    largo = c.bloque_largo
    alto = c.bloque_alto
    ancho = max(p.ala.envergadura, p.ala2.envergadura if con_ala2 else 0)
    caras_s = {"A": d, "B": d + ancho}   # cara del lado de la torre 1 / torre 2

    caras = {1: {k: _en_cara(res1, s, W) for k, s in caras_s.items()}}
    if not con_ala2:
        return ResultadoBloque(caras=caras, material={})
    if largo <= 0 or alto <= 0:
        raise ErrorGeometria("Pon el largo y el alto del bloque (pestaña Corte) para colocar la segunda ala.")

    p2 = proyecto_ala2(p)
    res2 = calcular(p2, m)
    avisos = [f"Ala 2: {a}" for a in res2.avisos]
    caras[2] = {}
    for k, s in caras_s.items():
        cara = _en_cara(res2, s, W)
        caras[2][k] = np.column_stack([largo - cara[:, 0], alto - cara[:, 1]])  # bloque girado 180°

    # corcho que queda entre los dos cortes (sin contar lo que quema el hilo)
    kerf = max(c.kerf_raiz, c.kerf_punta)
    material = {}
    for k in caras_s:
        material[k] = _distancia(caras[1][k][1:-1], caras[2][k][1:-1]) - kerf
    return ResultadoBloque(caras=caras, material=material, avisos=avisos)
