"""Vista en planta (desde arriba) del panel colocado en la máquina.

Eje horizontal: distancia a lo largo del hilo desde la torre 1 (mm).
Eje vertical: coordenada horizontal de la máquina (X), con el cero en la esquina
del bloque. Todo sale de las trayectorias de corte reales (con kerf, giro, etc.).
"""
import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Planta:
    s_raiz: float
    s_punta: float
    W: float                         # distancia entre torres
    raiz: tuple                      # (x BS, x BA) en la cara raíz
    punta: tuple                     # (x BS, x BA) en la cara punta
    varillas: list = field(default_factory=list)   # [(nombre, x raíz, x punta)]
    bisagra: tuple = None                          # (x raíz, x punta) de la bisagra del alerón
    datos: list = field(default_factory=list)      # líneas de texto con medidas


def _mm(v):
    """Número con un decimal como mucho (los tramos dan cuerdas como 216.666...)."""
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _tramos_varilla(tipos):
    """Índices [ini, fin) de cada grupo seguido de puntos 'varilla' del contorno."""
    tramos, ini = [], None
    for i, t in enumerate(tipos):
        if t == "varilla" and ini is None:
            ini = i
        elif t != "varilla" and ini is not None:
            tramos.append((ini, i))
            ini = None
    if ini is not None:
        tramos.append((ini, len(tipos)))
    return tramos


def calcular_planta(p, m, res):
    a, c = p.ala, p.corte
    W = m.distancia_torres
    d, L = c.dist_torre_bloque, a.envergadura
    s_r, s_t = (d, d + L) if a.raiz_lado == "XY" else (d + L, d)
    tipos = np.array(res.tipos)
    corte = tipos == "corte"
    corte[:3] = corte[-3:] = False     # sin los tramos de entrada y salida

    def extremos(cara):
        x = cara[corte, 0]
        return float(x.min()), float(x.max())   # BS (hacia el cero), BA

    raiz, punta = extremos(res.raiz), extremos(res.punta)

    # varillas: centro de cada grupo de puntos, emparejado con su nombre por posición
    varillas = []
    libres = list(a.varillas)
    for ini, fin in _tramos_varilla(res.tipos):
        xr = float((res.raiz[ini:fin, 0].min() + res.raiz[ini:fin, 0].max()) / 2)
        xt = float((res.punta[ini:fin, 0].min() + res.punta[ini:fin, 0].max()) / 2)
        nombre = ""
        if libres:
            v = min(libres, key=lambda v: abs((raiz[1] - v.pos_raiz) - xr))
            libres.remove(v)
            nombre = v.nombre
        varillas.append((nombre, xr, xt))

    bisagra = None
    if "aleron" in res.tipos:
        k = res.tipos.index("aleron")   # vértice de la V
        bisagra = (float(res.raiz[k, 0]), float(res.punta[k, 0]))

    cr, ct = a.cuerda_raiz, a.cuerda_punta
    flecha_ba = math.degrees(math.atan2(a.flecha, L))
    flecha_25 = math.degrees(math.atan2(a.flecha + 0.25 * (ct - cr), L))
    superficie = (cr + ct) / 2 * L / 1e4   # dm²
    datos = [
        f"Raíz: {_mm(cr)} mm ({a.perfil_raiz})  ·  junto a torre {'1' if a.raiz_lado == 'XY' else '2'}",
        f"Punta: {_mm(ct)} mm ({a.perfil_punta})  ·  estrechamiento {ct / cr:.2f}",
        f"Panel: {_mm(L)} mm  ·  superficie {superficie:.2f} dm²  ·  cuerda media {(cr + ct) / 2:.0f} mm",
        f"Flecha BA: {_mm(a.flecha)} mm ({flecha_ba:.1f}°)  ·  flecha al 25%: {flecha_25:.1f}°",
    ]
    if a.torsion_raiz or a.torsion_punta:
        datos.append(f"Calado: raíz {_mm(a.torsion_raiz)}°, punta {_mm(a.torsion_punta)}° "
                     f"(torsión {a.torsion_punta - a.torsion_raiz:+.1f}°)")
    if bisagra:
        al = a.aleron
        datos.append(f"Alerón: cuerda {al.cuerda_raiz:.0f} → {al.cuerda_punta:.0f} mm  ·  V de {al.angulo:g}°"
                     + (f"  ·  puente {al.puente:g} mm" if al.puente > 0 else ""))
    return Planta(s_raiz=s_r, s_punta=s_t, W=W, raiz=raiz, punta=punta, varillas=varillas, datos=datos,
                  bisagra=bisagra)
