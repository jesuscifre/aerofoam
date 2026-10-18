"""Motor de corte genérico entre dos contornos cerrados (uno en cada cara del bloque).

Lo usan los fuselajes. Los dos contornos deben tener el mismo número de puntos y
corresponderse punto a punto (el hilo une el punto i de una cara con el i de la otra).
El punto 0 es por donde entra el hilo (el más a la izquierda, hacia el cero).
Opcionalmente un contorno interior (hueco) al que se llega por una ranura.
"""
import numpy as np

from .geometria import ErrorGeometria, Resultado, _quitar_lazos


def area(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def preparar_contorno(P):
    """Contorno cerrado sin repetir el primer punto, antihorario y empezando por el
    punto más a la izquierda."""
    P = np.asarray(P, float)
    if len(P) > 1 and np.hypot(*(P[0] - P[-1])) < 1e-9:
        P = P[:-1]
    if area(P) < 0:
        P = P[::-1]
    i = int(np.argmin(P[:, 0] + 1e-9 * np.abs(P[:, 1] - P[:, 1].mean())))
    return np.roll(P, -i, axis=0)


def remuestrear(P, n):
    """n puntos repartidos por igual a lo largo de un contorno cerrado (empieza en P[0])."""
    Q = np.vstack([P, P[:1]])
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(Q, axis=0).T))]
    t = np.linspace(0, s[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, s, Q[:, 0]), np.interp(t, s, Q[:, 1])])


def desplazar_cerrado(P, d):
    """Desplaza un contorno cerrado antihorario d mm hacia fuera (d < 0 hacia dentro)."""
    t = np.roll(P, -1, axis=0) - np.roll(P, 1, axis=0)
    nt = np.hypot(t[:, 0], t[:, 1])
    nt[nt == 0] = 1
    t = t / nt[:, None]
    return P + d * np.column_stack([t[:, 1], -t[:, 0]])


def cortar(cara_a, cara_b, p, m, longitud, interior=None, kerf=None, nombres=None, dist_torre=None):
    """Trayectoria completa del hilo. cara_a está en la cara del bloque junto a la torre 1.

    interior: (hueco_a, hueco_b) o None. kerf: (kerf cara a, kerf cara b).
    """
    c = p.corte
    ka, kb = kerf if kerf else (c.kerf_raiz, c.kerf_punta)
    A, B = np.asarray(cara_a, float), np.asarray(cara_b, float)
    if A.shape != B.shape:
        raise ErrorGeometria("Las dos caras deben tener el mismo número de puntos.")

    caminos = {}
    for k, (P, kerf_cara) in enumerate(((A, ka), (B, kb))):
        fuera = _quitar_lazos(desplazar_cerrado(P, kerf_cara / 2))
        pts = [*fuera, fuera[0]]
        tipos = ["corte"] * len(fuera) + ["corte"]
        if interior is not None:
            h = np.asarray(interior[k], float)
            dentro = _quitar_lazos(desplazar_cerrado(h, -kerf_cara / 2))
            pts += [*dentro, dentro[0], fuera[0]]
            tipos += ["entrada"] + ["corte"] * (len(dentro) - 1) + ["corte", "entrada"]
        caminos[k] = (np.array(pts), tipos)
    (pa, tipos), (pb, _) = caminos[0], caminos[1]

    W = m.distancia_torres
    d = c.dist_torre_bloque if dist_torre is None else dist_torre
    if longitud <= 0:
        raise ErrorGeometria("La pieza debe tener longitud.")
    if d < 0 or d + longitud > W:
        raise ErrorGeometria(f"La pieza ({longitud:.0f} mm) no cabe entre las torres "
                             f"(distancia a la torre 1 + longitud > {W:g} mm).")
    s_a, s_b = d, d + longitud

    def torres(Pa, Pb):
        return Pa + (Pb - Pa) * (0 - s_a) / (s_b - s_a), Pa + (Pb - Pa) * (W - s_a) / (s_b - s_a)

    # entrada mínima medida en las torres; en altura, el punto más bajo a la altura indicada
    ea, eb = pa[0], pb[0]
    ta, tb = torres(ea[None, :], eb[None, :])
    dx = c.x_inicio - min(ta[0, 0], tb[0, 0])
    dy = c.altura - min(pa[:, 1].min(), pb[:, 1].min())
    pa, pb = pa + (dx, dy), pb + (dx, dy)
    # si la pieza se estrecha mucho, el hilo prolongado hasta las torres se abre más que la
    # pieza: se sube/aleja lo justo para que ninguna torre baje del cero
    avisos = []
    ta, tb = torres(pa, pb)
    sube = max(0.0, -min(ta[:, 1].min(), tb[:, 1].min()))
    aleja = max(0.0, -min(ta[:, 0].min(), tb[:, 0].min()))
    if sube > 1e-6 or aleja > 1e-6:
        pa, pb = pa + (aleja, sube), pb + (aleja, sube)
        if sube > 1e-6:
            avisos.append(f"Pieza subida {sube:.1f} mm para que las torres no bajen del cero "
                          f"(el hilo se abre hacia las torres).")
        if aleja > 1e-6:
            avisos.append(f"Pieza alejada {aleja:.1f} mm del cero para que las torres no vayan detrás de él.")

    def completar(P):
        e = P[0]
        return np.vstack([[0, 0], [0, e[1]], P, [0, e[1]], [0, 0]])
    R, T = completar(pa), completar(pb)
    tipos = ["inicio", "desplazamiento", "entrada", *tipos[1:], "entrada", "desplazamiento"]
    xy, za = torres(R, T)

    for nombre, tray in (("torre 1", xy), ("torre 2", za)):
        if tray[:, 0].min() < -1e-6 or tray[:, 1].min() < -1e-6:
            avisos.append(f"La {nombre} pasa por detrás o por debajo del cero: sube la altura o la entrada.")
        ancho = tray[:, 0].max() - min(0.0, tray[:, 0].min())
        alto = tray[:, 1].max() - min(0.0, tray[:, 1].min())
        if ancho > m.recorrido_x or alto > m.recorrido_y:
            avisos.append(f"La {nombre} necesita {ancho:.0f} x {alto:.0f} mm y la máquina recorre "
                          f"{m.recorrido_x:g} x {m.recorrido_y:g} mm.")
    if c.bloque_largo > 0 and c.bloque_alto > 0:
        for nombre, cara in (("torre 1", R), ("torre 2", T)):
            pieza = cara[3:-2]
            if pieza[:, 0].max() > c.bloque_largo or pieza[:, 1].max() > c.bloque_alto:
                avisos.append(f"La pieza se sale del bloque en la cara de la {nombre}.")
    return Resultado(raiz=R, punta=T, xy=xy, za=za, tipos=tipos, avisos=avisos,
                     nombres=nombres or {"raiz": "", "punta": ""})
