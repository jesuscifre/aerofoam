"""Fuselajes, con tres métodos:

- silueta: se corta la vista lateral o la vista en planta (el mismo contorno en las dos caras
  del bloque); luego se gira el bloque, se corta la otra vista y se redondea lijando.
  La forma sale de las medidas, de un DXF o de un STL.
- tramos: el fuselaje se parte a lo largo en tramos; cada tramo se corta con el hilo a lo
  largo del fuselaje, con la cuaderna de delante en una cara y la de detrás en la otra.
  Opcionalmente hueco (grosor de pared). La forma sale de las medidas.
- stl: como tramos, pero las cuadernas son los cortes reales del modelo 3D.

Ejes de la forma: x a lo largo (morro en x = 0), y lateral, z altura.
"""
from dataclasses import dataclass

import numpy as np

from .corte2d import cortar, desplazar_cerrado, preparar_contorno, remuestrear
from .geometria import ErrorGeometria, _quitar_lazos
from .importar import cargar_stl, contorno_dxf, muestrear_angulos, seccion_stl, silueta_stl

SEMIEJE_MIN = 2.0   # mm: las cuadernas no pueden ser un punto (el morro se redondea así)


@dataclass
class Fuselaje:
    metodo: str = "silueta"        # 'silueta' | 'tramos' | 'stl'
    fuente: str = "medidas"        # siluetas: 'medidas' | 'dxf' | 'stl'
    vista: str = "lateral"         # siluetas: 'lateral' | 'planta'
    # forma por medidas
    largo: float = 800.0
    alto: float = 100.0            # alto máximo
    ancho: float = 80.0            # ancho máximo
    pos_max: float = 30.0          # % del largo donde es más grueso
    morro: float = 2.0             # 1 = en punta, 2 = redondo, 3 o más = romo
    alto_cola: float = 20.0
    ancho_cola: float = 15.0
    subida_cola: float = 20.0      # cuánto sube el centro de la cola (mm)
    seccion: float = 2.5           # forma de las cuadernas: 2 = elipse, 4 o más = rectángulo redondeado
    # ficheros
    dxf: str = ""
    escala_dxf: float = 1.0
    stl: str = ""
    eje_stl: str = "X"             # eje del STL a lo largo del fuselaje
    arriba_stl: str = "Z"          # eje del STL hacia arriba
    escala_stl: float = 1.0
    # tramos
    n_tramos: int = 3
    cortes: str = ""               # posiciones de corte en mm separadas por comas ("" = tramos iguales)
    pared: float = 0.0             # grosor de pared para vaciar (0 = macizo)
    puntos: int = 160              # puntos por contorno
    colocar_auto: bool = True      # buscar para cada tramo dónde poner el bloque a lo largo del hilo


# ---------------------------------------------------------------- forma por medidas
def _suave(u):
    u = np.clip(u, 0, 1)
    return u * u * (3 - 2 * u)


def forma(f, x):
    """(semialto, semiancho, altura del centro) a lo largo del fuselaje."""
    if f.largo <= 0 or f.alto <= 0 or f.ancho <= 0:
        raise ErrorGeometria("Fuselaje: el largo, el alto y el ancho deben ser mayores que cero.")
    if f.morro < 1:
        raise ErrorGeometria("Fuselaje: la forma del morro debe ser 1 o más.")
    L = f.largo
    xm = float(np.clip(f.pos_max / 100 * L, 1.0, L - 1.0))
    x = np.asarray(x, float)
    t = np.clip(x / xm, 0, 1)
    nariz = (1 - (1 - t) ** f.morro) ** (1 / f.morro)
    s = _suave((x - xm) / (L - xm))
    fh = np.where(x <= xm, nariz, 1 - (1 - f.alto_cola / f.alto) * s)
    fw = np.where(x <= xm, nariz, 1 - (1 - f.ancho_cola / f.ancho) * s)
    zc = np.where(x <= xm, 0.0, f.subida_cola * s)
    return f.alto / 2 * fh, f.ancho / 2 * fw, zc


def silueta_medidas(f, vista, n):
    x = f.largo * (1 - np.cos(np.linspace(0, np.pi / 2, n)))   # más puntos en el morro
    hh, hw, zc = forma(f, x)
    if vista == "lateral":
        abajo, arriba = zc - hh, zc + hh
    else:
        abajo, arriba = -hw, hw
    return np.vstack([np.column_stack([x, abajo]), np.column_stack([x, arriba])[::-1][:-1]])


def cuaderna_medidas(f, x, n, menos=0.0):
    """Cuaderna (superelipse) en la estación x, n puntos desde la izquierda en sentido antihorario.
    menos: se resta a los semiejes (para el hueco)."""
    hh, hw, zc = (float(v) for v in forma(f, x))
    a, b = max(hw, SEMIEJE_MIN) - menos, max(hh, SEMIEJE_MIN) - menos
    if a <= 1.0 or b <= 1.0:
        return None
    e = 2.0 / max(f.seccion, 1.0)
    ang = np.pi + 2 * np.pi * np.arange(n) / n
    c, s = np.cos(ang), np.sin(ang)
    return np.column_stack([a * np.sign(c) * np.abs(c) ** e, zc + b * np.sign(s) * np.abs(s) ** e])


# ---------------------------------------------------------------- piezas
def _estaciones(f, L):
    if f.cortes.strip():
        try:
            xs = sorted({float(v.replace(",", ".")) for v in f.cortes.replace(";", " ").split()} | {0.0, L})
        except ValueError:
            raise ErrorGeometria("Fuselaje: las posiciones de corte deben ser números separados por espacios.")
        xs = [x for x in xs if 0 <= x <= L]
    else:
        if f.n_tramos < 1:
            raise ErrorGeometria("Fuselaje: al menos un tramo.")
        xs = list(np.linspace(0, L, f.n_tramos + 1))
    return [(a, b) for a, b in zip(xs, xs[1:]) if b - a >= 5]


_cache_stl = {}


def _stl(f):
    if not f.stl:
        raise ErrorGeometria("Fuselaje: elige el fichero STL.")
    from .perfiles import resolver_ruta
    ruta = resolver_ruta(f.stl)
    if not ruta.exists():
        raise ErrorGeometria(f"No encuentro el STL '{f.stl}'.")
    clave = (str(ruta), ruta.stat().st_mtime, f.eje_stl, f.arriba_stl, f.escala_stl)
    if clave not in _cache_stl:
        _cache_stl.clear()
        _cache_stl[clave] = {"tri": cargar_stl(ruta, f.eje_stl, f.arriba_stl, f.escala_stl)}
    return _cache_stl[clave]["tri"]


def silueta_cache(f, vista, n):
    """Silueta de un STL, guardada para no recalcularla en cada cambio."""
    tri = _stl(f)
    datos = next(iter(_cache_stl.values()))
    if (vista, n) not in datos:
        datos[(vista, n)] = silueta_stl(tri, vista, n)
    return datos[(vista, n)]


def _cortar_tramo(f, a, b, p, m, L, hueco, nombres):
    """Corta un tramo; con colocación automática prueba varias posiciones del bloque a lo largo
    del hilo y se queda con la que menos tiene que subir/alejar la pieza."""
    if not f.colocar_auto:
        return cortar(a, b, p, m, L, interior=hueco, nombres=nombres), p.corte.dist_torre_bloque
    W = m.distancia_torres
    margen = 20.0                       # el bloque no puede pegarse a las torres
    libre = W - L - 2 * margen
    if libre < 0:
        raise ErrorGeometria(f"El tramo de {L:.0f} mm no cabe entre las torres (deja {margen:g} mm a cada lado).")
    # cuenta rápida: con la pieza apoyada a la altura indicada, cuánto bajaría cada torre
    # (lineal en la posición del bloque); se elige la posición que menos obliga a subirla
    ds = margen + np.linspace(0, libre, 121)
    base = min(a[:, 1].min(), b[:, 1].min())
    dif = b - a
    bajada = []
    for d in ds:
        t1 = a[:, 1] - dif[:, 1] * d / L
        t2 = a[:, 1] + dif[:, 1] * (W - d) / L
        bajada.append(max(0.0, base - min(t1.min(), t2.min())))
    bajada = np.array(bajada)
    # entre las posiciones casi igual de buenas, la más centrada
    buenas = np.where(bajada <= bajada.min() + 0.5)[0]
    d = float(ds[buenas[np.argmin(np.abs(ds[buenas] - (W - L) / 2))]])
    return cortar(a, b, p, m, L, interior=hueco, nombres=nombres, dist_torre=d), d


def piezas(p, m):
    """[(etiqueta, Resultado, descripción para el G-code)] de lo que hay que cortar."""
    f = p.fuselaje
    n = max(20, int(f.puntos))
    if f.metodo == "silueta":
        if f.fuente == "dxf":
            if not f.dxf:
                raise ErrorGeometria("Fuselaje: elige el fichero DXF.")
            from .perfiles import resolver_ruta
            cont = contorno_dxf(resolver_ruta(f.dxf), f.escala_dxf)
            espesor = f.ancho if f.vista == "lateral" else f.alto
        elif f.fuente == "stl":
            tri = _stl(f)
            cont = silueta_cache(f, f.vista, n)
            espesor = float(np.ptp(tri[:, :, 1] if f.vista == "lateral" else tri[:, :, 2]))
        else:
            cont = silueta_medidas(f, f.vista, n)
            espesor = f.ancho if f.vista == "lateral" else f.alto
        cont = remuestrear(preparar_contorno(cont), 2 * n)
        vista = "lateral" if f.vista == "lateral" else "en planta"
        res = cortar(cont, cont, p, m, max(espesor, 10.0), kerf=(p.corte.kerf_raiz, p.corte.kerf_raiz),
                     nombres={"raiz": f"silueta {vista}", "punta": f"silueta {vista}"})
        largo = float(np.ptp(cont[:, 0]))
        res.extra = {"silueta": cont, "vista": f.vista, "espesor": max(espesor, 10.0)}
        return [(f"Silueta {vista} ({largo:.0f} mm)", res, f"fuselaje: silueta {vista}, {largo:.0f} mm")]

    if f.metodo == "stl":
        tri = _stl(f)
        L = float(tri[:, :, 0].max())

        def cuaderna(x, menos=0.0):
            x = min(max(x, L * 0.002), L * 0.998)
            sec = seccion_stl(tri, x)
            P = muestrear_angulos(sec, n)
            if menos > 0:
                P = _quitar_lazos(desplazar_cerrado(P, -menos))
                cent = P.mean(axis=0)
                if np.ptp(P[:, 0]) < 2 or np.ptp(P[:, 1]) < 2 or np.any(
                        np.hypot(*(P - cent).T) > np.hypot(*(muestrear_angulos(sec, n) - cent).T)):
                    return None
            return P
    else:
        L = f.largo

        def cuaderna(x, menos=0.0):
            return cuaderna_medidas(f, x, n, menos)

    resultado = []
    for k, (x1, x2) in enumerate(_estaciones(f, L), 1):
        a, b = cuaderna(x1), cuaderna(x2)
        hueco = None
        etiqueta = f"Tramo {k}: {x1:.0f}–{x2:.0f} mm"
        if f.pared > 0:
            ha, hb = cuaderna(x1, f.pared), cuaderna(x2, f.pared)
            if ha is not None and hb is not None:
                hueco = (ha, hb)
                etiqueta += " (hueco)"
            else:
                etiqueta += " (macizo: muy estrecho para vaciar)"
        res, d = _cortar_tramo(f, a, b, p, m, x2 - x1, hueco,
                               {"raiz": f"cuaderna {x1:.0f} mm", "punta": f"cuaderna {x2:.0f} mm"})
        res.extra = {"x1": x1, "x2": x2, "a": a, "b": b, "hueco": hueco}
        lugar = f"bloque a {d:.0f} mm de la torre 1, cuaderna de {x1:.0f} mm hacia la torre 1"
        res.avisos.insert(0, f"Coloca el {lugar}.")
        resultado.append((etiqueta, res, f"fuselaje: tramo {k} de {x1:.0f} a {x2:.0f} mm; {lugar}"))
    if not resultado:
        raise ErrorGeometria("Fuselaje: no hay ningún tramo de al menos 5 mm.")
    return resultado
