"""Calibración de velocidad de corte y kerf.

Se corta una fila de cuadrados, cada uno a una velocidad real distinta, que salen como piezas
sueltas. Midiendo el ancho de cada cuadrado: kerf = lado - ancho medido. Las esquinas
redondeadas indican que el hilo se queda atrás (poco calor para esa velocidad).

Las dos torres hacen el mismo recorrido (corte recto), así que la velocidad real del hilo es la
de cada torre. GRBL aplica la F a los 4 ejes juntos: para que el hilo vaya a v mm/min hay que
mandar F = v·√2.

Recorrido (cero en la esquina inferior del bloque): el hilo sube por el canto del bloque hasta la
base de los cuadrados y avanza por esa línea; en cada cuadrado recorre la base, sube por el lado
derecho, vuelve por arriba y baja por el izquierdo (la pieza queda suelta) y sigue hasta el
siguiente. Al final vuelve por la ranura ya cortada.
"""
import math
from datetime import datetime
import unicodedata

import numpy as np

from .gcode import _sustituir

VELOCIDADES_DEFECTO = "60 100 150 200 250 300"


def leer_velocidades(texto):
    try:
        v = [float(x.replace(",", ".")) for x in texto.replace(";", " ").split()]
    except ValueError:
        raise ValueError("Las velocidades deben ser números separados por espacios.")
    v = [x for x in v if x > 0]
    if not v:
        raise ValueError("Pon al menos una velocidad.")
    return v


def disposicion(velocidades, lado, separacion, base):
    """Posición de cada cuadrado y tamaño del bloque necesario."""
    entrada = separacion
    xs = [entrada + k * (lado + separacion) for k in range(len(velocidades))]
    largo = xs[-1] + lado + separacion
    alto = base + lado + separacion
    return xs, largo, alto


def velocidad_real(v, literal):
    """Velocidad real del hilo en la prueba: con F tal cual, GRBL reparte la F entre los 4 ejes y en
    un corte recto (las dos torres iguales) el hilo va a F/√2."""
    return v / math.sqrt(2) if literal else v


def gcode_calibracion(m, c, velocidades, lado=30.0, separacion=15.0, base=10.0, literal=True):
    """G-code de la prueba y datos (bloque necesario, tiempo).

    literal=True: cada velocidad se escribe tal cual como F (F30 = F30).
    literal=False: son velocidades reales del hilo y se manda F = v·√2."""
    if lado <= 5 or separacion < 3 or base < 0:
        raise ValueError("Revisa el lado (> 5 mm), la separación (≥ 3 mm) y la base (≥ 0).")

    xs, largo, alto = disposicion(velocidades, lado, separacion, base)
    nd = m.decimales
    e1, e2, e3, e4 = m.eje1, m.eje2, m.eje3, m.eje4

    def n(v):
        return f"{round(v, nd) + 0.0:.{nd}f}"

    lineas = [_sustituir(l, c) for l in m.cabecera.splitlines() if l.strip()]
    lineas += [
        f"(calibracion de velocidad y kerf - AeroFoam {datetime.now():%Y-%m-%d %H:%M})",
        (f"(cuadrados de {lado:g} mm a F {', '.join(f'{v:g}' for v in velocidades)})" if literal else
         f"(cuadrados de {lado:g} mm, velocidades reales {', '.join(f'{v:g}' for v in velocidades)} mm/min)"),
        f"(bloque minimo {largo:.0f} x {alto:.0f} mm; cero en su esquina inferior)",
        ("(F tal cual: con 4 ejes el hilo va a F / 1.414)" if literal else
         "(F = velocidad real x 1.414 porque GRBL reparte la F entre los 4 ejes)"),
    ]
    lineas += [_sustituir(l, c) for l in m.encender.splitlines() if l.strip()]
    if c.precalentamiento > 0:
        lineas.append(f"G4 P{c.precalentamiento:g}")

    pos = np.zeros(2)
    tiempo = 0.0

    def mover(x, y, v):
        nonlocal pos, tiempo
        d = math.hypot(x - pos[0], y - pos[1])
        if d < 1e-9:
            return
        f = v if literal else v * math.sqrt(2)
        lineas.append(f"G1 {e1}{n(x)} {e2}{n(y)} {e3}{n(x)} {e4}{n(y)} F{f:g}")
        tiempo += d / velocidad_real(v, literal)
        pos = np.array([x, y])

    rapido = max(c.vel_desplazamiento, 1.0)
    lineas.append("(subida por el canto del bloque)")
    mover(0.0, base, rapido)
    for k, (x0, v) in enumerate(zip(xs, velocidades), 1):
        lineas.append(f"(cuadrado {k}: F{v:g})" if literal else f"(cuadrado {k}: {v:g} mm/min reales)")
        mover(x0, base, v)                 # avance por la base hasta el cuadrado
        mover(x0 + lado, base, v)          # base
        mover(x0 + lado, base + lado, v)   # lado derecho
        mover(x0, base + lado, v)          # arriba
        mover(x0, base, v)                 # lado izquierdo: la pieza queda suelta
        mover(x0 + lado, base, v)          # vuelve a la esquina por la ranura de la base
    lineas.append("(vuelta por la ranura ya cortada)")
    mover(0.0, base, rapido)
    mover(0.0, 0.0, rapido)
    lineas += [_sustituir(l, c) for l in m.apagar.splitlines() if l.strip()]
    lineas += [_sustituir(l, c) for l in m.pie.splitlines() if l.strip()]
    texto = "\n".join(lineas) + "\n"
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return texto, {"largo": largo, "alto": alto, "tiempo_min": tiempo,
                   "excede": [v for v in velocidades if velocidad_real(v, literal) > m.vel_max]}


# ---------------------------------------------------------------- resultados
def kerfs(lado, medidas):
    """{velocidad: kerf} a partir de {velocidad: ancho medido}."""
    return {v: lado - w for v, w in medidas.items() if w and 0 < w < lado + 5}


def recomendar(kerf_por_v, vivas):
    """La velocidad más rápida con esquinas vivas (si se han marcado) y kerf razonable."""
    if not kerf_por_v:
        return None
    candidatas = [v for v in kerf_por_v if vivas.get(v)] or list(kerf_por_v)
    kmin = min(kerf_por_v[v] for v in candidatas)
    buenas = [v for v in candidatas if kerf_por_v[v] <= max(kmin * 1.5, kmin + 0.3)]
    return max(buenas) if buenas else max(candidatas)


def tabla_real(tabla, literal):
    """La tabla {velocidad de la prueba: kerf} pasada a velocidades reales del hilo."""
    return {velocidad_real(v, literal): k for v, k in tabla.items()}


def kerf_a_velocidad(tabla, v):
    """Kerf interpolado en la tabla {velocidad: kerf} (fuera de rango, el del extremo)."""
    vs = sorted(tabla)
    return float(np.interp(v, vs, [tabla[x] for x in vs]))


def texto_tabla(tabla):
    return " ".join(f"{v:g}:{k:.2f}" for v, k in sorted(tabla.items()))


def leer_tabla(texto):
    tabla = {}
    for par in (texto or "").split():
        try:
            v, k = par.split(":")
            tabla[float(v)] = float(k)
        except ValueError:
            continue
    return tabla


def velocidades_caras(res, info):
    """Velocidad media real de cada cara del bloque en los tramos de corte (mm/min)."""
    L, S = np.asarray(info["llegada"]), np.asarray(info["salida"])
    lr = lt = t = 0.0
    for i in range(1, len(res.tipos)):
        if res.tipos[i] != "corte":
            continue
        dt = L[i] - S[i - 1]
        if dt <= 0:
            continue
        lr += math.dist(res.raiz[i], res.raiz[i - 1])
        lt += math.dist(res.punta[i], res.punta[i - 1])
        t += dt
    return (lr / t, lt / t) if t > 0 else (0.0, 0.0)
