"""Lectura de perfiles alares (.dat de una o dos tiras de puntos) y generador NACA de 4 dígitos.

Todos los perfiles se devuelven normalizados: cuerda 1, borde de ataque en (0, 0),
y dos superficies (extradós, intradós) como arrays Nx2 con x ascendente de 0 a 1,
muestreadas densamente sobre una spline que pasa por todos los puntos del fichero.
"""
import re
from pathlib import Path

import numpy as np

from .rutas import DIR_CATALOGO, DIR_MIS_PERFILES, DOCUMENTOS, RECURSOS

_NUM = r"[-+]?(?:\d+[.,]?\d*|[.,]\d+)(?:[eE][-+]?\d+)?"
_PAR = re.compile(rf"^\s*({_NUM})[\s,;]+({_NUM})\s*$")

_cache = {}


def _f(txt):
    return float(txt.replace(",", "."))


def _spline(s, v):
    """Segundas derivadas de una spline cúbica natural v(s) (algoritmo de Thomas)."""
    n = len(s)
    h = np.diff(s)
    a = np.zeros(n)
    b = np.ones(n)
    c = np.zeros(n)
    d = np.zeros(n)
    a[1:-1] = h[:-1]
    b[1:-1] = 2 * (h[:-1] + h[1:])
    c[1:-1] = h[1:]
    d[1:-1] = 6 * (np.diff(v[1:]) / h[1:] - np.diff(v[:-1]) / h[:-1])
    for i in range(1, n):
        w = a[i] / b[i - 1]
        b[i] -= w * c[i - 1]
        d[i] -= w * d[i - 1]
    M = np.zeros(n)
    M[-1] = d[-1] / b[-1]
    for i in range(n - 2, -1, -1):
        M[i] = (d[i] - c[i] * M[i + 1]) / b[i]
    return M


def _evaluar(s, v, M, sq):
    k = np.clip(np.searchsorted(s, sq) - 1, 0, len(s) - 2)
    h = s[k + 1] - s[k]
    a = (s[k + 1] - sq) / h
    c = (sq - s[k]) / h
    return a * v[k] + c * v[k + 1] + ((a**3 - a) * M[k] + (c**3 - c) * M[k + 1]) * h**2 / 6


N_DENSO = 1500  # puntos por superficie de la curva interpolada


def _quitar_cierres(P):
    """Corrige defectos típicos de los .dat:
    - puntos de 'cierre' en el borde de salida (p. ej. un (1, 0) después del último
      punto real) que hacen un gancho;
    - puntos que hacen retroceder el contorno (p. ej. un signo perdido en el BA),
      que harían un lazo.
    """
    def giro(a, b, c):
        u, v = b - a, c - b
        nu, nv = np.hypot(*u), np.hypot(*v)
        if nu < 1e-12 or nv < 1e-12:
            return 0.0
        return np.degrees(np.arccos(np.clip(np.dot(u, v) / (nu * nv), -1, 1)))
    while len(P) > 6 and giro(P[-3], P[-2], P[-1]) > 45:
        P = P[:-1]
    while len(P) > 6 and giro(P[0], P[1], P[2]) > 45:
        P = P[1:]
    i = 1
    while i < len(P) - 1:
        if giro(P[i - 1], P[i], P[i + 1]) > 150:
            # vuelta atrás: se quita el punto que repite el camino
            quitar = i + 1 if np.hypot(*(P[i + 1] - P[i - 1])) < np.hypot(*(P[i] - P[i - 1])) else i
            P = np.delete(P, quitar, axis=0)
            P = P[np.r_[True, np.hypot(*np.diff(P, axis=0).T) > 1e-9]]
            i = max(1, i - 1)
        else:
            i += 1
    return P


def preparar(contorno):
    return _preparar(contorno)[:2]


def _preparar(contorno):
    """Normaliza un contorno ordenado BS -> extradós -> BA -> intradós -> BS.

    Pasa una spline paramétrica (por longitud de arco) por todos los puntos,
    busca el borde de ataque en la curva suave (el punto más adelantado, aunque no
    coincida con ningún punto del fichero) y devuelve extradós e intradós muy densos,
    con x ascendente de 0 a 1 y el borde de ataque en (0, 0).
    """
    P = np.asarray(contorno, float)
    # puntos repetidos seguidos rompen la parametrización
    P = P[np.r_[True, np.hypot(*np.diff(P, axis=0).T) > 1e-9]]
    if len(P) < 5:
        raise ValueError("El perfil tiene muy pocos puntos.")
    P = _quitar_cierres(P)
    # sentido antihorario = extradós primero
    area = np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
    if area < 0:
        P = P[::-1]
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    Mx, My = _spline(s, P[:, 0]), _spline(s, P[:, 1])
    fino = np.linspace(0, s[-1], 20001)
    s_ba = fino[int(np.argmin(_evaluar(s, P[:, 0], Mx, fino)))]
    # afinar el mínimo de x
    for paso in (s[-1] / 20000, s[-1] / 2e6):
        loc = np.linspace(s_ba - paso, s_ba + paso, 201)
        s_ba = loc[int(np.argmin(_evaluar(s, P[:, 0], Mx, loc)))]
    u = (1 - np.cos(np.linspace(0, np.pi, N_DENSO))) / 2
    lados = []
    for s0, s1 in ((s_ba, 0.0), (s_ba, s[-1])):  # desde el BA hacia cada BS
        sq = s0 + (s1 - s0) * u
        lados.append(np.column_stack([_evaluar(s, P[:, 0], Mx, sq), _evaluar(s, P[:, 1], My, sq)]))
    ba = lados[0][0].copy()
    cuerda = max(l[:, 0].max() for l in lados) - ba[0]
    if cuerda <= 0:
        raise ValueError("El perfil no tiene cuerda.")
    sup, inf = ((l - ba) / cuerda for l in lados)
    for l in (sup, inf):
        l[:, 0] = np.maximum.accumulate(l[:, 0])  # x siempre creciente
        l[0] = 0.0
    xx = np.linspace(0.05, 0.95, 50)
    if np.mean(np.interp(xx, sup[:, 0], sup[:, 1]) - np.interp(xx, inf[:, 0], inf[:, 1])) < 0:
        sup, inf = inf, sup
    return sup, inf, ba, cuerda


def leer_dat(ruta):
    """Lee un .dat: una sola tira de puntos BS->BA->BS, o dos tiras (extradós e intradós, cada una
    del BA al BS) precedidas de una línea con el número de puntos de cada una."""
    ruta = Path(ruta)
    nombre = ruta.stem
    pares = []
    for linea in ruta.read_text(encoding="latin-1").splitlines():
        m = _PAR.match(linea)
        if m:
            pares.append((_f(m[1]), _f(m[2])))
        elif not pares and linea.strip():
            nombre = linea.strip()
    pts = np.array(pares, float)
    if len(pts) < 5:
        raise ValueError(f"'{ruta.name}' no parece un fichero de perfil válido.")
    if pts[0, 0] > 1.5 and pts[0, 1] > 1.5:  # dos tiras: extradós e intradós, ambos BA -> BS
        nu, nl = int(pts[0, 0]), int(pts[0, 1])
        contorno = np.vstack([pts[1:1 + nu][::-1], pts[1 + nu:1 + nu + nl]])
    else:  # una tira
        contorno = pts
    return nombre, preparar(contorno)


def naca4(codigo, n=200):
    """Perfil NACA de 4 dígitos con borde de salida cerrado."""
    codigo = codigo.strip()
    if len(codigo) != 4 or not codigo.isdigit():
        raise ValueError(f"NACA '{codigo}' no válido: usa 4 dígitos, p. ej. NACA 2412.")
    m = int(codigo[0]) / 100
    p = int(codigo[1]) / 10
    t = int(codigo[2:]) / 100
    x = (1 - np.cos(np.linspace(0, np.pi, n))) / 2
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1036 * x**4)
    if m > 0 and p > 0:
        yc = np.where(x < p, m / p**2 * (2 * p * x - x**2), m / (1 - p)**2 * ((1 - 2 * p) + 2 * p * x - x**2))
        dyc = np.where(x < p, 2 * m / p**2 * (p - x), 2 * m / (1 - p)**2 * (p - x))
    else:
        yc = np.zeros_like(x)
        dyc = np.zeros_like(x)
    th = np.arctan(dyc)
    sup = np.column_stack([x - yt * np.sin(th), yc + yt * np.cos(th)])
    inf = np.column_stack([x + yt * np.sin(th), yc - yt * np.cos(th)])
    return preparar(np.vstack([sup[::-1], inf[1:]]))


def mezclar(a, b, u):
    """Perfil intermedio: u=0 es el perfil a, u=1 el perfil b (mezcla punto a punto
    a igual % de cuerda, como la sección del ala entre una raíz y una punta distintas)."""
    x = (1 - np.cos(np.linspace(0, np.pi, N_DENSO))) / 2
    return tuple(np.column_stack([x, (1 - u) * interpolar(sa, x) + u * interpolar(sb, x)])
                 for sa, sb in zip(a, b))


def interpolar(superficie, x):
    """y de una superficie (ya interpolada y muy densa) en las x pedidas."""
    return np.interp(x, superficie[:, 0], superficie[:, 1])


def _ficheros_dat():
    """Todos los .dat disponibles: los propios del usuario tienen prioridad sobre el catálogo."""
    vistos = {}
    for carpeta in (DIR_MIS_PERFILES, DIR_CATALOGO):
        if carpeta.exists():
            for f in carpeta.glob("*.dat"):
                vistos.setdefault(f.stem.lower(), f)
    return vistos


MIS_PERFILES = "Mis perfiles"


def listar():
    """Perfiles disponibles: {clave del fichero: datos del catálogo (nombre, categoría, descripción...)}.
    Los .dat que no están en el catálogo (los que añade el usuario) salen en 'Mis perfiles'."""
    cat = {}
    ruta_cat = DIR_CATALOGO / "catalogo.json"
    if ruta_cat.exists():
        import json
        try:
            cat = json.loads(ruta_cat.read_text(encoding="utf-8")).get("perfiles", {})
        except (OSError, ValueError, AttributeError):
            cat = {}
    ficheros = sorted(_ficheros_dat().values(), key=lambda f: f.stem.lower())
    return {f.stem: cat.get(f.stem, {"nombre": f.stem, "descripcion": "", "categoria": MIS_PERFILES})
            for f in ficheros}


def resolver_ruta(spec):
    ruta = Path(spec)
    if ruta.is_absolute():
        return ruta
    if ruta.suffix == "" and len(ruta.parts) == 1:  # nombre del catálogo, p. ej. 's1223'
        f = _ficheros_dat().get(spec.lower())
        if f:
            return f
    for base in (DOCUMENTOS, RECURSOS):  # rutas relativas, p. ej. 'perfiles/s1020.dat'
        if (base / ruta).exists():
            return base / ruta
    if len(ruta.parts) > 1 and ruta.parts[0] == "perfiles":  # proyectos antiguos
        f = _ficheros_dat().get(ruta.stem.lower())
        if f:
            return f
    return DOCUMENTOS / ruta


def obtener_perfil(spec):
    """'NACA 2412' o ruta a un .dat (relativa a la carpeta del programa o absoluta).

    Devuelve (nombre, (extrados, intrados)).
    """
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("Falta elegir el perfil.")
    ruta = resolver_ruta(spec)
    # 'NACA 2412' se calcula con la fórmula; 'naca2412' del catálogo se lee del fichero
    if not ruta.exists() and spec.upper().startswith("NACA"):
        clave = ("naca", spec.upper())
        if clave not in _cache:
            _cache[clave] = (spec.upper(), naca4(spec[4:]))
        return _cache[clave]
    if not ruta.exists():
        raise ValueError(f"No encuentro el perfil '{spec}'.")
    clave = ("dat", str(ruta), ruta.stat().st_mtime)
    if clave not in _cache:
        _cache[clave] = leer_dat(ruta)
    return _cache[clave]
