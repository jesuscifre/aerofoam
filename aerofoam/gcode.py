"""Generación de G-code para GRBL de 4 ejes.

GRBL aplica la F a la distancia combinada de los 4 ejes, así que si se pone la
velocidad tal cual el hilo no corta a esa velocidad. Modos:
  cara_rapida: F calculada por segmento para que la cara del bloque que más
               recorre vaya a la velocidad pedida (recomendado).
  g93:         lo mismo, pero en modo tiempo inverso (G93, F = 1/minutos).
  f_bruto:     F tal cual en todos los movimientos (como hacen otros programas).
"""
import math
import unicodedata
from datetime import datetime

MODOS = {
    "cara_rapida": "F corregida (cara más rápida)",
    "g93": "Tiempo inverso G93",
    "f_bruto": "F sin corregir",
}


def _sustituir(texto, c):
    return (texto.replace("{potencia}", f"{c.potencia:g}")
                 .replace("{precalentamiento}", f"{c.precalentamiento:g}"))


def generar(res, p, m, nombre="ala", descripcion=None):
    c = p.corte
    vel = {"corte": c.vel_corte, "entrada": c.vel_entrada, "varilla": c.vel_varillas, "aleron": c.vel_varillas,
           "desplazamiento": c.vel_desplazamiento}
    for k, v in vel.items():
        if v <= 0:
            raise ValueError(f"La velocidad de {k} debe ser mayor que cero.")
    e1, e2, e3, e4 = m.eje1, m.eje2, m.eje3, m.eje4
    nd = m.decimales

    def n(v):
        return f"{round(v, nd) + 0.0:.{nd}f}"  # + 0.0 evita escribir -0.000

    a = p.ala
    lineas = [_sustituir(l, c) for l in m.cabecera.splitlines() if l.strip()]
    lineas += [
        f"({nombre} - AeroFoam {datetime.now():%Y-%m-%d %H:%M})",
        f"({descripcion})" if descripcion else
        f"(raiz {res.nombres.get('raiz', '')} {a.cuerda_raiz:g}mm, punta {res.nombres.get('punta', '')} {a.cuerda_punta:g}mm, panel {a.envergadura:g}mm)",
        f"(velocidad corte {c.vel_corte:g} mm/min, modo {MODOS[c.modo_velocidad]})",
        "(el hilo debe estar en el cero de trabajo al empezar)",
    ]
    if c.modo_velocidad == "g93":
        lineas.append("G93")
    lineas += [_sustituir(l, c) for l in m.encender.splitlines() if l.strip()]
    if c.precalentamiento > 0:
        lineas.append(f"G4 P{c.precalentamiento:g}")

    def giro(i):
        """Grados que gira la trayectoria (en la cara raíz) en el punto i."""
        if i + 1 >= len(res.raiz):
            return 0.0
        u = res.raiz[i] - res.raiz[i - 1]
        w = res.raiz[i + 1] - res.raiz[i]
        nu, nw = math.hypot(*u), math.hypot(*w)
        if nu < 1e-6 or nw < 1e-6:
            return 0.0
        return math.degrees(math.acos(max(-1.0, min(1.0, (u[0] * w[0] + u[1] * w[1]) / (nu * nw)))))

    tiempo = 0.0
    # momento (min) en que el hilo llega a cada punto y en que sale de él (tras una pausa)
    llegada = [0.0] * len(res.tipos)
    salida = [0.0] * len(res.tipos)
    vmax_torre = 0.0
    limitados = 0
    ultimo_f = None
    ultimo_tipo = None
    for i in range(1, len(res.tipos)):
        dxy = math.dist(res.xy[i], res.xy[i - 1])
        dza = math.dist(res.za[i], res.za[i - 1])
        dtorre = max(dxy, dza)
        if dtorre < 1e-9:
            llegada[i] = salida[i] = tiempo
            continue
        tipo = res.tipos[i]
        v = vel[tipo]
        if tipo == "desplazamiento":
            dist = dtorre
        else:
            dist = max(math.dist(res.raiz[i], res.raiz[i - 1]), math.dist(res.punta[i], res.punta[i - 1]))
            if dist < 1e-9:
                dist = dtorre
        if c.modo_velocidad == "f_bruto":
            t = math.hypot(dxy, dza) / v  # GRBL reparte la F entre los 4 ejes
        else:
            t = dist / v  # minutos
        if dtorre / t > m.vel_max and c.modo_velocidad != "f_bruto":  # la torre no puede ir tan rápido: se alarga el tiempo
            t = dtorre / m.vel_max
            limitados += 1
        vmax_torre = max(vmax_torre, dtorre / t)
        tiempo += t
        llegada[i] = tiempo

        if tipo != ultimo_tipo:
            lineas.append(f"({tipo})")
            ultimo_tipo = tipo
        mov = f"G1 {e1}{n(res.xy[i][0])} {e2}{n(res.xy[i][1])} {e3}{n(res.za[i][0])} {e4}{n(res.za[i][1])}"
        if c.modo_velocidad == "cara_rapida":
            f = f"{math.hypot(dxy, dza) / t:.1f}"
        elif c.modo_velocidad == "g93":
            f = f"{1 / t:.3f}"
        else:
            f = f"{v:.1f}"
        if f != ultimo_f or c.modo_velocidad == "g93":
            mov += f" F{f}"
            ultimo_f = f
        lineas.append(mov)
        # pausa en los cambios de dirección de las varillas, para que el hilo se enderece
        if (c.pausa_varillas > 0 and {"varilla", "aleron"} & set(res.tipos[i:i + 2]) and giro(i) > 30):
            lineas.append(f"G4 P{c.pausa_varillas:g}")
            tiempo += c.pausa_varillas / 60
        salida[i] = tiempo

    lineas += [_sustituir(l, c) for l in m.apagar.splitlines() if l.strip()]
    if c.modo_velocidad == "g93":
        lineas.append("G94")
    lineas += [_sustituir(l, c) for l in m.pie.splitlines() if l.strip()]
    texto = "\n".join(lineas) + "\n"
    # GRBL solo entiende ASCII: se quitan acentos de los comentarios
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    info = {"tiempo_min": tiempo, "vmax_torre": vmax_torre, "limitados": limitados, "lineas": len(lineas),
            "llegada": llegada, "salida": salida}
    return texto, info
