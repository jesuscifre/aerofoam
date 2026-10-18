"""División del panel en tramos para que el alerón ocupe solo una parte.

Si el alerón va de `desde` a `hasta` (mm desde la raíz), el panel se parte en hasta
tres tramos: antes del alerón, con alerón y después. Cada tramo es un panel completo
que se corta por separado; sus secciones son las del panel original en esos puntos
(cuerda, calado, espesor, varillas y perfil interpolados).
"""
import copy

from .geometria import ErrorGeometria


def _lerp(a, b, f):
    return a + (b - a) * f


def _tramo(p, s1, s2, con_aleron):
    q = copy.deepcopy(p)
    o, a = p.ala, q.ala
    L = o.envergadura
    f1, f2 = s1 / L, s2 / L
    for raiz, punta in (("cuerda_raiz", "cuerda_punta"), ("torsion_raiz", "torsion_punta"),
                        ("escala_espesor_raiz", "escala_espesor_punta"),
                        ("recubrimiento_raiz", "recubrimiento_punta"), ("mezcla_raiz", "mezcla_punta")):
        r, t = getattr(o, raiz), getattr(o, punta)
        setattr(a, raiz, _lerp(r, t, f1))
        setattr(a, punta, _lerp(r, t, f2))
    a.envergadura = s2 - s1
    a.flecha = o.flecha * (f2 - f1)
    a.desplaz_vertical = o.desplaz_vertical * (f2 - f1)
    a.recta = False
    for v, vo in zip(a.varillas, o.varillas):
        v.pos_raiz, v.pos_punta = _lerp(vo.pos_raiz, vo.pos_punta, f1), _lerp(vo.pos_raiz, vo.pos_punta, f2)
    al, alo = a.aleron, o.aleron
    al.activo = con_aleron
    al.dividir = False
    al.cuerda_raiz = _lerp(alo.cuerda_raiz, alo.cuerda_punta, f1)
    al.cuerda_punta = _lerp(alo.cuerda_raiz, alo.cuerda_punta, f2)
    return q


def dividir(p):
    """[(etiqueta, proyecto del tramo)]. Sin división devuelve el panel entero."""
    al = p.ala.aleron
    L = p.ala.envergadura
    if not (al.activo and al.dividir):
        return [("Panel completo", p)]
    a = al.desde
    b = al.hasta if al.hasta > 0 else L
    if not 0 <= a < b <= L:
        raise ErrorGeometria("Alerón: 'desde' y 'hasta' deben cumplir 0 ≤ desde < hasta ≤ longitud del panel.")
    cortes = sorted({0.0, float(a), float(b), float(L)})
    tramos = []
    for s1, s2 in zip(cortes, cortes[1:]):
        if s2 - s1 < 1.0:
            continue
        con = s1 >= a - 1e-6 and s2 <= b + 1e-6
        etiqueta = f"Tramo {len(tramos) + 1}: {s1:g}–{s2:g} mm" + (" (alerón)" if con else "")
        tramos.append((etiqueta, _tramo(p, s1, s2, con)))
    return tramos
