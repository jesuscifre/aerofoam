"""Cálculo de la trayectoria del hilo.

Sistema local de cada sección (raíz / punta): mm, borde de ataque en x=0, cuerda
hacia +x, extradós hacia +y. El contorno se recorre como en los ficheros .dat:
borde de salida -> extradós -> borde de ataque -> intradós -> borde de salida.

En la máquina el borde de salida queda hacia el cero (el hilo entra por detrás),
y las trayectorias de las caras del bloque se proyectan sobre las dos torres.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from .perfiles import interpolar, mezclar, obtener_perfil
from .proyecto import sincronizar_recta

N_CIRCULO = 36
SECCIONES = ("raiz", "punta")


class ErrorGeometria(Exception):
    pass


@dataclass
class Resultado:
    raiz: np.ndarray        # trayectoria en la cara raíz del bloque (x, y)
    punta: np.ndarray       # trayectoria en la cara punta del bloque
    xy: np.ndarray          # trayectoria de la torre de los ejes 1-2
    za: np.ndarray          # trayectoria de la torre de los ejes 3-4
    tipos: list             # tipo de movimiento que llega a cada punto
    avisos: list = field(default_factory=list)
    nombres: dict = field(default_factory=dict)
    giro: float = 0.0       # grados que se ha girado el panel para orientarlo en el bloque
    extra: dict = field(default_factory=dict)   # datos para el modelo 3D (fuselajes)


# Reparto de puntos: coseno sobre t² concentra puntos en la nariz, que es donde
# la curva gira más (con el coseno simple las narices afiladas salían a tramos).
def t_de_x(x):
    return np.sqrt(np.arccos(np.clip(1 - 2 * np.asarray(x, float), -1, 1)) / np.pi)


def x_de_t(t):
    return (1 - np.cos(np.pi * np.asarray(t, float) ** 2)) / 2


def _rejilla(est_r, est_t, n, vacios):
    """Puntos x (fracción de cuerda) de raíz y punta con la misma cantidad y
    correspondencia, pasando exactamente por las estaciones dadas.

    Reparto coseno (más puntos en BA y BS). Los intervalos de `vacios` no llevan
    puntos intermedios. Devuelve (xs_raiz, xs_punta, índice de cada estación).
    """
    br = np.array([0.0, *est_r, 1.0])
    bt = np.array([0.0, *est_t, 1.0])
    tr, tt = t_de_x(br), t_de_x(bt)
    xr, xt, idx = [], [], []
    for k in range(len(br) - 1):
        if k > 0:
            idx.append(len(xr))
        if k in vacios:
            m = 1
        else:
            m = max(2, int(round(n * ((tr[k + 1] - tr[k]) + (tt[k + 1] - tt[k])) / 2)))
        u = np.arange(m) / m
        xr.extend(x_de_t(tr[k] + u * (tr[k + 1] - tr[k])))
        xt.extend(x_de_t(tt[k] + u * (tt[k + 1] - tt[k])))
    xr.append(1.0)
    xt.append(1.0)
    return np.array(xr), np.array(xt), idx


def _quitar_lazos(P, ventana=12):
    """Al desplazar una curva con entrantes más cerrados que el desplazamiento salen
    pequeños rizos. Se cortan: los puntos del rizo pasan a ser el punto de cruce
    (se mantiene el número de puntos para que raíz y punta sigan emparejadas)."""
    P = P.copy()
    n = len(P)

    def cruz(u, v):
        return u[0] * v[1] - u[1] * v[0]
    i = 0
    while i < n - 3:
        a, b = P[i], P[i + 1]
        for j in range(i + 2, min(n - 1, i + ventana)):
            c, d = P[j], P[j + 1]
            den = cruz(b - a, d - c)
            if abs(den) < 1e-12:
                continue
            t = cruz(c - a, d - c) / den
            u = cruz(c - a, b - a) / den
            if 0 < t < 1 and 0 < u < 1:
                P[i + 1:j + 1] = a + t * (b - a)
                i = j
                break
        i += 1
    return P


def _desplazar(contorno, d):
    """Desplaza el contorno d mm hacia fuera (d<0 hacia dentro)."""
    t = np.gradient(contorno, axis=0)
    nt = np.hypot(t[:, 0], t[:, 1])
    nt[nt == 0] = 1
    t = t / nt[:, None]
    normal = np.column_stack([t[:, 1], -t[:, 0]])  # contorno antihorario -> fuera
    return contorno + d * normal


def _nucleo(ala, s, perfil, C, x):
    """Altura del extradós y del intradós del núcleo (sin recubrimiento) en x (mm)."""
    esc = (ala.escala_espesor_raiz if s == "raiz" else ala.escala_espesor_punta) / 100
    piel = ala.recubrimiento_raiz if s == "raiz" else ala.recubrimiento_punta
    xs = np.array([x / C])
    ys, yi = _superficies(perfil[0], perfil[1], esc, xs, xs)
    return float(ys[0]) * C - piel, float(yi[0]) * C + piel


def _agujero(v, superficie, xc, ysn, yin, kerf):
    """Centro y radio de un agujero redondo, radio del hilo, y la y del punto por donde se entra."""
    r = v.diametro / 2
    if v.centro == "mitad":
        yc = (ysn + yin) / 2
    elif superficie == "extrados":
        yc = ysn - v.prof_centro
    else:
        yc = yin + v.prof_centro
    rw = r - kerf / 2
    y_entrada = yc + rw if superficie == "extrados" else yc - rw
    return yc, r, rw, y_entrada


def _desplazamiento_entrada(v, superficie, s, perfil, C, kerf, ala):
    """Cuánto se adelanta (hacia el BA) el punto de entrada en la superficie para que
    la entrada al agujero vaya inclinada."""
    if v.tipo != "redondo" or abs(v.inclinacion) < 1e-9:
        return 0.0
    if abs(v.inclinacion) >= 80:
        raise ErrorGeometria(f"'{v.nombre}': la inclinación debe estar entre -80° y 80°.")
    xc = v.pos_raiz if s == "raiz" else v.pos_punta
    ysn, yin = _nucleo(ala, s, perfil, C, xc)
    _, _, _, y_ent = _agujero(v, superficie, xc, ysn, yin, kerf)
    tg = math.tan(math.radians(v.inclinacion))
    x_e = xc
    for _ in range(3):  # la superficie no es plana: se afina un par de veces
        ysn, yin = _nucleo(ala, s, perfil, C, x_e)
        h = abs((ysn if superficie == "extrados" else yin) - y_ent) + kerf / 2
        x_e = xc - h * tg
    return xc - x_e


def _v_aleron(al, s, perfil, C, kerf, ala):
    """V del alerón (bisagra arriba) en una sección: x donde el hilo sale y vuelve al
    intradós (ya metidas en la cuña la mitad del kerf) y el vértice (x, y) del hilo."""
    cuerda_al = al.cuerda_raiz if s == "raiz" else al.cuerda_punta
    if not 0 < cuerda_al < 0.9 * C:
        raise ErrorGeometria(f"Alerón: la cuerda del alerón en la {s} debe estar entre 0 y el 90% de la cuerda.")
    if not 5 <= al.angulo <= 120:
        raise ErrorGeometria("Alerón: el ángulo de la V debe estar entre 5° y 120°.")
    if al.puente < 0:
        raise ErrorGeometria("Alerón: el puente no puede ser negativo.")
    xh = C - cuerda_al
    ys, yi = _nucleo(ala, s, perfil, C, xh)
    mitad = math.radians(al.angulo / 2)
    k2 = kerf / 2
    # vértice de las caras de la V: en la superficie (sin puente) o donde el quemado
    # del hilo deja justo el puente pedido
    yh = ys if al.puente <= 0 else ys - al.puente + k2 * (1 / math.sin(mitad) - 1)
    y_hilo = yh - k2 / math.sin(mitad)       # vértice del hilo (va medio kerf dentro de la cuña)
    if y_hilo - yi < 0.5:
        raise ErrorGeometria(f"Alerón: el perfil es demasiado fino en la bisagra ({s}).")
    tg = math.tan(mitad)

    def hasta_intrados(signo):
        """Donde la recta del hilo (paralela a la cara, medio kerf dentro de la cuña) llega
        al recorrido del hilo por el intradós (medio kerf por fuera del corcho)."""
        x = xh
        for _ in range(6):  # el intradós no es plano: se afina
            _, yi_x = _nucleo(ala, s, perfil, C, x)
            x = xh + signo * (y_hilo - (yi_x - k2)) * tg
        return x
    xa, xb = hasta_intrados(-1), hasta_intrados(+1)
    if xb - xa < 0.2:
        raise ErrorGeometria("Alerón: la V es demasiado estrecha para el grosor del corte del hilo.")
    vertice = (xh, y_hilo)
    if al.puente <= 0:  # sube hasta la superficie para separar el alerón y vuelve
        puntos = [vertice, (xh, ys), vertice]
    else:
        puntos = [vertice]
    return xa, xb, puntos


def _estaciones(ala, cuerda, kerf, perfiles):
    """Estaciones de cada superficie a partir de las varillas."""
    est = {"extrados": [], "intrados": []}
    for i, v in enumerate(ala.varillas):
        pos = {s: (v.pos_raiz if s == "raiz" else v.pos_punta)
               - _desplazamiento_entrada(v, v.superficie, s, perfiles[s], cuerda[s], kerf[s], ala)
               for s in SECCIONES}
        if v.tipo == "rectangular":
            for s in SECCIONES:
                if v.ancho / 2 - kerf[s] / 2 <= 0.01:
                    raise ErrorGeometria(f"'{v.nombre}': la ranura es más estrecha que el corte del hilo.")
            for rol, signo in (("a", -1), ("b", 1)):
                fr = {s: (pos[s] + signo * (v.ancho / 2 - kerf[s] / 2)) / cuerda[s] for s in SECCIONES}
                est[v.superficie].append(dict(v=v, rol=rol, fr=fr))
        else:
            est[v.superficie].append(dict(v=v, rol="c", fr={s: pos[s] / cuerda[s] for s in SECCIONES}))

    al = ala.aleron
    if al.activo:
        v = {s: _v_aleron(al, s, perfiles[s], cuerda[s], kerf[s], ala) for s in SECCIONES}
        for rol, k in (("va", 0), ("vb", 1)):
            est["intrados"].append(dict(v=al, rol=rol, fr={s: v[s][k] / cuerda[s] for s in SECCIONES},
                                        vertice={s: v[s][2] for s in SECCIONES}))

    for sup, lista in est.items():
        lista.sort(key=lambda e: e["fr"]["raiz"])
        for e in lista:
            for s in SECCIONES:
                if not 0.005 < e["fr"][s] < 0.995:
                    raise ErrorGeometria(f"'{e['v'].nombre}': posición fuera del perfil en la {s}.")
        for a, b in zip(lista, lista[1:]):
            for s in SECCIONES:
                if b["fr"][s] - a["fr"][s] < 1e-4:
                    raise ErrorGeometria(
                        f"'{a['v'].nombre}' y '{b['v'].nombre}' se solapan o cambian de orden entre raíz y punta.")
        for j, e in enumerate(lista):
            if e["rol"] in ("a", "va") and (j + 1 >= len(lista) or lista[j + 1]["v"] is not e["v"]):
                raise ErrorGeometria(f"'{e['v'].nombre}': hay una varilla dentro de la ranura.")
    return est


def _superficies(sup, inf, escala, xs_s, xs_i):
    """Ordenadas de extradós e intradós en las x dadas, escalando el espesor
    respecto a la línea media."""
    def y(sup_, x):
        return interpolar(sup_, x)
    ys = y(sup, xs_s)
    yi = y(inf, xs_i)
    if escala != 1.0:
        cs = (ys + y(inf, xs_s)) / 2
        ci = (y(sup, xs_i) + yi) / 2
        ys = cs + escala * (ys - cs)
        yi = ci + escala * (yi - ci)
    return ys, yi


def _seccion(ala, s, perfil, cuerda, kerf, rejillas, est, avisos):
    """Contorno de una sección en su sistema local, con varillas, kerf y torsión."""
    sup, inf = perfil
    C = cuerda
    esc = (ala.escala_espesor_raiz if s == "raiz" else ala.escala_espesor_punta) / 100
    piel = ala.recubrimiento_raiz if s == "raiz" else ala.recubrimiento_punta
    xs_s, xs_i = rejillas["extrados"][s], rejillas["intrados"][s]
    ys, yi = _superficies(sup, inf, esc, xs_s, xs_i)
    Xs, Ys, Xi, Yi = xs_s * C, ys * C, xs_i * C, yi * C

    def y_nucleo_sup(x):
        return float(np.interp(x, Xs, Ys)) - piel

    def y_nucleo_inf(x):
        return float(np.interp(x, Xi, Yi)) + piel

    nu = len(Xs)
    contorno = np.vstack([np.column_stack([Xs, Ys])[::-1], np.column_stack([Xi, Yi])[1:]])
    off = _quitar_lazos(_desplazar(contorno, kerf / 2 - piel))

    def indice(superficie, i):
        return nu - 1 - i if superficie == "extrados" else nu - 1 + i

    insertar = {}
    salida_varilla = set()
    salida_aleron = set()
    for superficie, lista in est.items():
        dentro = -1.0 if superficie == "extrados" else 1.0
        idx = rejillas[superficie]["idx"]
        for j, e in enumerate(lista):
            v = e["v"]
            li = indice(superficie, idx[j])
            P = off[li]
            if e["rol"] in ("va", "vb"):  # V del alerón: el vértice va entre sus dos estaciones
                if e["rol"] == "va":
                    lb = indice(superficie, idx[j + 1])
                    insertar[min(li, lb)] = [np.array(q, float) for q in e["vertice"][s]]
                    salida_aleron.add(max(li, lb))
                continue
            if v.tipo == "marca":
                tg = math.tan(math.radians(v.inclinacion))
                insertar[li] = [P + (v.prof_marca * tg, dentro * v.prof_marca), P.copy()]
            elif v.tipo == "redondo":
                xc = (v.pos_raiz if s == "raiz" else v.pos_punta)
                ysn, yin = y_nucleo_sup(xc), y_nucleo_inf(xc)
                yc, r, rw, _ = _agujero(v, superficie, xc, ysn, yin, kerf)
                if yc + r > ysn + 1e-6 or yc - r < yin - 1e-6:
                    avisos.append(f"'{v.nombre}': el agujero se sale del perfil en la {s}.")
                if rw <= 0.05:
                    raise ErrorGeometria(f"'{v.nombre}': el diámetro es menor que el corte del hilo.")
                a0 = math.pi / 2 if superficie == "extrados" else -math.pi / 2
                ang = a0 - 2 * math.pi * np.arange(N_CIRCULO + 1) / N_CIRCULO
                circulo = np.column_stack([xc + rw * np.cos(ang), yc + rw * np.sin(ang)])
                insertar[li] = [*circulo, P.copy()]
            elif e["rol"] == "a":
                lb = indice(superficie, idx[j + 1])
                primero, segundo = min(li, lb), max(li, lb)
                insertar[primero] = [off[primero] + (0, dentro * v.alto), off[segundo] + (0, dentro * v.alto)]
                salida_varilla.add(segundo)

    puntos, tipos = [], []
    for li, P in enumerate(off):
        puntos.append(P)
        tipos.append("varilla" if li in salida_varilla else "aleron" if li in salida_aleron else "corte")
        insertados = insertar.get(li, [])
        tipo_ins = "aleron" if li + 1 in salida_aleron else "varilla"
        for Q in insertados:
            puntos.append(Q)
            tipos.append(tipo_ins)
    pts = np.array(puntos)

    # torsión (positivo = morro abajo) alrededor del pivote, luego flecha y desplazamiento
    th = math.radians(ala.torsion_raiz if s == "raiz" else ala.torsion_punta)
    px = ala.pivote_torsion / 100 * C
    dx, dy = pts[:, 0] - px, pts[:, 1]
    pts = np.column_stack([px + dx * math.cos(th) - dy * math.sin(th), dx * math.sin(th) + dy * math.cos(th)])
    if s == "punta":
        pts = pts + (ala.flecha, ala.desplaz_vertical)
    return pts, tipos


def calcular(p, m):
    sincronizar_recta(p.ala, p.corte)
    ala, c = p.ala, p.corte
    avisos = []
    if ala.cuerda_raiz <= 0 or ala.cuerda_punta <= 0:
        raise ErrorGeometria("Las cuerdas deben ser mayores que cero.")
    if ala.envergadura <= 0:
        raise ErrorGeometria("La longitud del panel debe ser mayor que cero.")
    if ala.puntos < 10:
        raise ErrorGeometria("Usa al menos 10 puntos por superficie.")
    try:
        base = {"raiz": obtener_perfil(ala.perfil_raiz), "punta": obtener_perfil(ala.perfil_punta)}
    except (ValueError, OSError) as e:
        raise ErrorGeometria(str(e))
    perfiles = {}
    for s, u in (("raiz", ala.mezcla_raiz), ("punta", ala.mezcla_punta)):
        if u <= 1e-9 or base["raiz"] is base["punta"]:
            perfiles[s] = base["raiz"] if u <= 1e-9 else base["punta"]
        elif u >= 1 - 1e-9:
            perfiles[s] = base["punta"]
        else:  # sección intermedia de un ala con perfiles distintos (tramos)
            perfiles[s] = (f"{base['raiz'][0]} / {base['punta'][0]} ({u * 100:.0f}%)",
                           mezclar(base["raiz"][1], base["punta"][1], u))
    cuerda = {"raiz": ala.cuerda_raiz, "punta": ala.cuerda_punta}
    kerf = {"raiz": c.kerf_raiz, "punta": c.kerf_punta}

    est = _estaciones(ala, cuerda, kerf, {s: perfiles[s][1] for s in SECCIONES})
    rejillas = {}
    for superficie, lista in est.items():
        vacios = {j + 1 for j, e in enumerate(lista) if e["rol"] in ("a", "va")}
        xr, xt, idx = _rejilla([e["fr"]["raiz"] for e in lista], [e["fr"]["punta"] for e in lista],
                               ala.puntos, vacios)
        rejillas[superficie] = {"raiz": xr, "punta": xt, "idx": idx}

    sec = {}
    for s in SECCIONES:
        sec[s] = _seccion(ala, s, perfiles[s][1], cuerda[s], kerf[s], rejillas, est, avisos)
    (pr, tipos), (pt, tipos_t) = sec["raiz"], sec["punta"]
    assert len(pr) == len(pt) and tipos == tipos_t

    if c.invertir:  # boca abajo: espejo vertical antes de orientar y colocar
        for s in SECCIONES:
            sec[s] = (sec[s][0] * (1, -1), sec[s][1])

    # giro común a raíz y punta (el panel gira como un sólido, no cambia la torsión)
    giro = _angulo_orientacion(c, [sec[s] for s in SECCIONES])
    if giro:
        for s in SECCIONES:
            sec[s] = (_rotar(sec[s][0], giro), sec[s][1])

    W = m.distancia_torres
    d, L = c.dist_torre_bloque, ala.envergadura
    if d < 0:
        raise ErrorGeometria("La distancia de la torre al bloque no puede ser negativa.")
    if d + L > W:
        raise ErrorGeometria("El panel no cabe entre las torres (distancia + longitud > distancia entre torres).")
    s_r, s_t = (d, d + L) if ala.raiz_lado == "XY" else (d + L, d)

    def torres(R, T):
        return R + (T - R) * (0 - s_r) / (s_t - s_r), R + (T - R) * (W - s_r) / (s_t - s_r)

    # colocación en la máquina: BS hacia el cero; en altura, el BS de la raíz o el punto
    # más bajo de las dos caras a la altura indicada.
    # El tramo de entrada se mide en las torres, para que ninguna empiece detrás del cero.
    bs = {s: (sec[s][0][0] + sec[s][0][-1]) / 2 for s in SECCIONES}
    x_ref = max(bs["raiz"][0], bs["punta"][0])
    if c.referencia_altura == "base":
        y_ref = min(sec[s][0][:, 1].min() for s in SECCIONES)
    else:
        y_ref = bs["raiz"][1]

    def colocar(pts, dx=0.0):
        return np.column_stack([dx + x_ref - pts[:, 0], c.altura + pts[:, 1] - y_ref])

    bs_xy, bs_za = torres(colocar(bs["raiz"][None, :]), colocar(bs["punta"][None, :]))
    dx = c.x_inicio - min(bs_xy[0, 0], bs_za[0, 0])

    caras = {}
    for s in SECCIONES:
        contorno = colocar(sec[s][0], dx)
        b = colocar(bs[s][None, :], dx)[0]
        caras[s] = np.vstack([[0, 0], [0, b[1]], b, contorno, b, [0, b[1]], [0, 0]])
    tipos = ["inicio", "desplazamiento", "entrada", *tipos, "corte", "entrada", "desplazamiento"]

    R, T = caras["raiz"], caras["punta"]
    xy, za = torres(R, T)

    # sin homing: el cero es donde se coloca el hilo, así que se comprueba el recorrido total
    for nombre, tray in (("torre XY", xy), ("torre ZA", za)):
        if tray[:, 0].min() < -1e-6 or tray[:, 1].min() < -1e-6:
            avisos.append(f"La {nombre} pasa por detrás o por debajo del cero: sube la altura o la entrada.")
        ancho = tray[:, 0].max() - min(0.0, tray[:, 0].min())
        alto = tray[:, 1].max() - min(0.0, tray[:, 1].min())
        if ancho > m.recorrido_x or alto > m.recorrido_y:
            avisos.append(f"La {nombre} necesita {ancho:.0f} x {alto:.0f} mm y la máquina recorre "
                          f"{m.recorrido_x:g} x {m.recorrido_y:g} mm.")
    if c.bloque_largo > 0 and c.bloque_alto > 0:
        for s, cara in (("raíz", R), ("punta", T)):
            perfil = cara[3:-3]
            if (perfil[:, 0].max() > c.bloque_largo or perfil[:, 1].max() > c.bloque_alto
                    or perfil[:, 1].min() < 0):
                avisos.append(f"El perfil de la {s} se sale del bloque.")

    return Resultado(raiz=R, punta=T, xy=xy, za=za, tipos=tipos, avisos=avisos,
                     nombres={s: perfiles[s][0] for s in SECCIONES}, giro=-giro)


def _rotar(pts, grados):
    a = math.radians(grados)
    ca, sa = math.cos(a), math.sin(a)
    return np.column_stack([pts[:, 0] * ca - pts[:, 1] * sa, pts[:, 0] * sa + pts[:, 1] * ca])


def _envolvente_inferior(pts):
    """Parte inferior de la envolvente convexa (x ascendente)."""
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]
    h = []
    for p in pts:
        while len(h) >= 2 and ((h[-1][0] - h[-2][0]) * (p[1] - h[-2][1])
                               - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0])) <= 0:
            h.pop()
        h.append(p)
    return np.array(h)


def _centroide(pts):
    x, y = pts[:, 0], pts[:, 1]
    cr = x * np.roll(y, -1) - np.roll(x, -1) * y
    a = cr.sum() / 2
    if abs(a) < 1e-12:
        return pts.mean(axis=0)
    return np.array([((x + np.roll(x, -1)) * cr).sum(), ((y + np.roll(y, -1)) * cr).sum()]) / (6 * a)


def _intrados(pts, tipos):
    """Puntos del intradós (sin varillas), x ascendente, y la cuerda (x_ba, x_bs)."""
    tipos = np.array(tipos)
    i_ba = int(np.argmin(pts[:, 0]))
    sel = np.arange(len(pts)) >= i_ba
    inf = pts[sel & (tipos == "corte")]
    return inf[np.argsort(inf[:, 0])], pts[i_ba, 0], pts[:, 0].max()


def _angulo_orientacion(c, secciones):
    """Ángulo (grados, antihorario en el sistema del perfil) común a las dos secciones."""
    contornos = [np.asarray(p)[np.array(t) == "corte"] for p, t in secciones]
    todos = np.vstack(contornos)
    if c.orientacion == "manual":
        return -c.angulo_manual  # en la máquina el eje x va invertido respecto al perfil
    if c.orientacion == "intrados":
        # como quedaría apoyado en una mesa: el tramo de la envolvente inferior
        # sobre el que cae el centro de gravedad queda horizontal
        h = _envolvente_inferior(todos)
        cg = np.mean([_centroide(p) for p in contornos], axis=0)
        mejor, err_min = 0.0, math.inf
        for a, b in zip(h, h[1:]):
            g = -math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            xa, xb, xc = _rotar(np.array([a, b, cg]), g)[:, 0]
            err = max(0.0, xa - xc, xc - xb)
            if err < err_min:
                mejor, err_min = g, err
        return mejor
    if c.orientacion == "tramo":
        # el tramo del intradós de la raíz entre los dos % de cuerda queda horizontal
        inf, x_ba, x_bs = _intrados(*secciones[0])
        x1, x2 = (x_ba + f / 100 * (x_bs - x_ba) for f in (c.tramo_desde, c.tramo_hasta))
        if not 0 <= c.tramo_desde < c.tramo_hasta <= 100:
            raise ErrorGeometria("El tramo del intradós debe ir de un % menor a uno mayor (0-100).")
        y1, y2 = np.interp([x1, x2], inf[:, 0], inf[:, 1])
        return -math.degrees(math.atan2(y2 - y1, x2 - x1))
    if c.orientacion == "min_alto":
        todos = np.vstack([p for p, _ in secciones])

        def alto(g):
            y = _rotar(todos, g)[:, 1]
            return y.max() - y.min()
        angs = np.arange(-30.0, 30.01, 0.5)
        g = angs[int(np.argmin([alto(a) for a in angs]))]
        for paso in (0.1, 0.02):
            fino = np.arange(g - 5 * paso, g + 5 * paso + 1e-9, paso)
            g = fino[int(np.argmin([alto(a) for a in fino]))]
        return float(g)
    return 0.0
