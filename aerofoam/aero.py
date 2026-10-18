"""Montaje del avión y cálculo aerodinámico sencillo (estimaciones de diseño).

Métodos:
- Perfiles: teoría del perfil delgado (la "placa plana" con curvatura): ángulo de sustentación
  nula y momento en el 25% a partir de la línea media real del perfil.
- Superficies: pendiente de sustentación de Helmbold (alargamiento y flecha), cuerda media
  aerodinámica (CMA) de un trapecio, centro aerodinámico en el 25% de la CMA.
- Punto neutro: ala + cola horizontal con la estela del ala (downwash) y eficiencia de cola 0,9.
  No se cuenta el efecto desestabilizador del fuselaje: por eso se recomienda dejar margen.
- Resistencia: fricción de placa plana (laminar o turbulenta según Reynolds) sobre la superficie
  mojada de cada pieza, con factores de forma, más resistencia inducida.
Coordenadas del avión: x hacia atrás desde el morro, y hacia la derecha, z hacia arriba (mm).
"""
import math
from dataclasses import dataclass, field

import numpy as np

from .geometria import ErrorGeometria
from .modelo3d import Parte
from .perfiles import interpolar, obtener_perfil
from .vlm import paneles_avion, resolver

# parte laminar de la capa límite según el acabado (el resto, turbulenta)
LAMINAR = {"rugoso": 0.0, "cinta": 0.2, "liso": 0.4}
ACABADOS = {"rugoso": "Porexpán sin forrar (rugoso)", "cinta": "Forrado con cinta o film",
            "liso": "Lijado y pintado / fibra"}

RHO = 1.225       # kg/m³
NU = 1.5e-5       # m²/s
G = 9.81
ETA_COLA = 0.9


# ---------------------------------------------------------------- perfiles
_cache_perfil = {}


def perfil_delgado(spec):
    """alfa0 (°), cm en el 25%, espesor relativo, área relativa (área / c²), x del centroide (/ c)."""
    if spec in _cache_perfil:
        return _cache_perfil[spec]
    try:
        _, (sup, inf) = obtener_perfil(spec)
    except (ValueError, OSError) as e:
        raise ErrorGeometria(str(e))
    th = np.linspace(1e-4, np.pi - 1e-4, 600)
    x = (1 - np.cos(th)) / 2
    yu, yl = interpolar(sup, x), interpolar(inf, x)
    dyc = np.gradient((yu + yl) / 2, x)
    alfa0 = -1 / np.pi * np.trapezoid(dyc * (np.cos(th) - 1), th)
    a1 = 2 / np.pi * np.trapezoid(dyc * np.cos(th), th)
    a2 = 2 / np.pi * np.trapezoid(dyc * np.cos(2 * th), th)
    esp = yu - yl
    area = float(np.trapezoid(esp, x))
    r = (math.degrees(alfa0), float(np.pi / 4 * (a2 - a1)), float(esp.max()), area,
         float(np.trapezoid(esp * x, x) / area) if area > 0 else 0.4)
    _cache_perfil[spec] = r
    return r


def contorno_perfil(spec, n=50):
    """Contorno cerrado (u, v) del perfil con cuerda 1, siempre con los mismos puntos."""
    _, (sup, inf) = obtener_perfil(spec)
    x = (1 - np.cos(np.linspace(0, np.pi, n))) / 2
    return np.vstack([np.column_stack([x, interpolar(sup, x)])[::-1], np.column_stack([x, interpolar(inf, x)])[1:]])


# ---------------------------------------------------------------- superficies
@dataclass
class Superficie:
    nombre: str
    S: float          # área real (mm²), contando las dos mitades si las hay
    b: float          # envergadura proyectada (mm)
    AR: float
    cma: float        # cuerda media aerodinámica (mm)
    x_ba_cma: float   # x del borde de ataque de la CMA
    x_ca: float       # centro aerodinámico (25% CMA)
    cla: float        # pendiente de sustentación (1/rad)
    alfa0: float      # ángulo de sustentación nula respecto a la referencia (°), con calado y torsión
    cm0: float
    tc: float         # espesor relativo medio
    volumen: float    # mm³ de corcho
    x_cg: float       # centro de gravedad del corcho
    mojada: float     # superficie mojada (mm²)


def superficie(nombre, ala, x_ba, mitades=2, diedro=0.0, separacion=0.0, calado=0.0):
    cr, ct, L = ala.cuerda_raiz, ala.cuerda_punta, ala.envergadura
    if cr <= 0 or ct <= 0 or L <= 0:
        raise ErrorGeometria(f"{nombre}: cuerdas y envergadura deben ser mayores que cero.")
    lam = ct / cr
    S = mitades * (cr + ct) / 2 * L
    b = mitades * L * math.cos(math.radians(diedro)) + (separacion if mitades == 2 else 0)
    if mitades == 1:
        b = L  # deriva: su "envergadura" es la altura
    AR = b * b / S if mitades == 2 else 2 * b * b / S   # deriva: efecto placa del fuselaje
    cma = 2 / 3 * cr * (1 + lam + lam ** 2) / (1 + lam)
    y_cma = L / 3 * (1 + 2 * lam) / (1 + lam)
    x_ba_cma = x_ba + ala.flecha * y_cma / L
    tan_c2 = (ala.flecha + (ct - cr) / 2) / L
    cla = 2 * math.pi * AR / (2 + math.sqrt(4 + AR * AR * (1 + tan_c2 ** 2)))
    pr, pt = perfil_delgado(ala.perfil_raiz), perfil_delgado(ala.perfil_punta)
    peso = lambda a, b_: (a * cr + b_ * ct) / (cr + ct)
    alfa0 = peso(pr[0], pt[0]) + peso(ala.torsion_raiz, ala.torsion_punta) - calado
    cm0 = peso(pr[1], pt[1])
    esc_r, esc_t = ala.escala_espesor_raiz / 100, ala.escala_espesor_punta / 100
    tc = peso(pr[2] * esc_r, pt[2] * esc_t)
    ar_, at_ = pr[3] * esc_r * cr * cr, pt[3] * esc_t * ct * ct
    volumen = mitades * L / 3 * (ar_ + at_ + math.sqrt(ar_ * at_))
    x_cg = x_ba_cma + peso(pr[4], pt[4]) * cma
    mojada = 2 * (1 + 0.2 * tc) * S
    return Superficie(nombre, S, b, AR, cma, x_ba_cma, x_ba_cma + 0.25 * cma, cla, alfa0, cm0, tc,
                      volumen, x_cg, mojada)


# ---------------------------------------------------------------- fuselaje
@dataclass
class DatosFuselaje:
    largo: float
    ancho: float
    alto: float
    volumen: float
    x_cg: float
    mojada: float
    planta: np.ndarray     # contorno (x, y) visto desde arriba
    lateral: np.ndarray    # contorno (x, z) visto de lado
    cuadernas: list        # [(x, contorno (y, z))] para el 3D


def datos_fuselaje(f):
    from .fuselaje import _stl, cuaderna_medidas, forma
    from .importar import muestrear_angulos, seccion_stl, silueta_stl
    if f.metodo == "stl" or (f.metodo == "silueta" and f.fuente == "stl"):
        tri = _stl(f)
        v0, v1, v2 = tri[:, 0], tri[:, 1], tri[:, 2]
        vol6 = np.einsum("ij,ij->i", v0, np.cross(v1, v2))
        volumen = abs(vol6.sum()) / 6
        x_cg = float(((v0 + v1 + v2)[:, 0] / 4 * vol6).sum() / vol6.sum()) if vol6.sum() else 0.0
        mojada = float(np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1).sum() / 2)
        L = float(tri[:, :, 0].max())
        lateral = silueta_stl(tri, "lateral", 80)
        planta = silueta_stl(tri, "planta", 80)
        cuadernas = []
        for x in np.linspace(L * 0.01, L * 0.99, 24):
            try:
                cuadernas.append((x, muestrear_angulos(seccion_stl(tri, x), 48)))
            except ErrorGeometria:
                pass
        return DatosFuselaje(L, float(np.ptp(tri[:, :, 1])), float(np.ptp(tri[:, :, 2])), volumen, x_cg, mojada,
                             planta, lateral, cuadernas)
    L = f.largo
    xs = np.linspace(0, L, 161)
    areas, perims, cuadernas = [], [], []
    for x in xs:
        c = cuaderna_medidas(f, x, 64)
        a = abs(0.5 * np.sum(c[:, 0] * np.roll(c[:, 1], -1) - np.roll(c[:, 0], -1) * c[:, 1]))
        if f.pared > 0:
            h = cuaderna_medidas(f, x, 64, f.pared)
            if h is not None:
                a -= abs(0.5 * np.sum(h[:, 0] * np.roll(h[:, 1], -1) - np.roll(h[:, 0], -1) * h[:, 1]))
        areas.append(a)
        perims.append(float(np.hypot(*np.diff(np.vstack([c, c[:1]]), axis=0).T).sum()))
    areas, perims = np.array(areas), np.array(perims)
    volumen = float(np.trapezoid(areas, xs))
    x_cg = float(np.trapezoid(areas * xs, xs) / volumen) if volumen > 0 else L / 2
    hh, hw, zc = forma(f, xs)
    planta = np.vstack([np.column_stack([xs, -hw]), np.column_stack([xs, hw])[::-1]])
    lateral = np.vstack([np.column_stack([xs, zc - hh]), np.column_stack([xs, zc + hh])[::-1]])
    for x in np.linspace(0, L, 25):
        cuadernas.append((x, cuaderna_medidas(f, x, 48)))
    return DatosFuselaje(L, f.ancho, f.alto, volumen, x_cg, float(np.trapezoid(perims, xs)), planta, lateral,
                         cuadernas)


# ---------------------------------------------------------------- avión
@dataclass
class Resultados:
    ala: Superficie
    cola_h: Superficie = None      # estabilizador (o la cola en V)
    cola_v: Superficie = None      # deriva
    fus: DatosFuselaje = None
    S_h_ef: float = 0.0            # área horizontal efectiva de la cola (mm²)
    S_v_ef: float = 0.0
    x_np: float = 0.0
    x_cg_rec: float = 0.0          # CG recomendado con el margen objetivo
    pesos: list = field(default_factory=list)   # [(nombre, g, x)]
    peso_est: float = 0.0
    cg_est: float = 0.0
    lineas: list = field(default_factory=list)  # informe
    acabado: str = "cinta"
    avisos: list = field(default_factory=list)


def _cf(re, laminar=0.0):
    """Coeficiente de fricción de placa plana con una parte laminar al principio y el resto turbulento
    (laminar de Blasius, turbulento de Schlichting)."""
    re = max(re, 1e3)

    def lam(r):
        return 1.328 / math.sqrt(max(r, 1.0))

    def turb(r):
        return 0.455 / math.log10(max(r, 10.0)) ** 2.58
    if laminar >= 1:
        return lam(re)
    if laminar <= 0:
        return turb(re)
    rt = re * laminar
    return turb(re) - laminar * (turb(rt) - lam(rt))


def calcular_avion(p):
    av = p.avion
    r = Resultados(ala=superficie("Ala", p.ala, av.x_ala, 2, av.diedro_ala, av.separacion_raices),
                   acabado=av.acabado)
    w = r.ala
    if av.tipo_cola == "convencional":
        r.cola_h = superficie("Estabilizador", p.estabilizador, av.x_estab, 2, 0, 0, av.calado_estab)
        r.cola_v = superficie("Deriva", p.deriva, av.x_deriva, 1)
        r.S_h_ef, r.S_v_ef = r.cola_h.S, r.cola_v.S
    elif av.tipo_cola == "v":
        g = math.radians(av.angulo_v)
        r.cola_h = superficie("Cola en V", p.estabilizador, av.x_estab, 2, av.angulo_v, 0, av.calado_estab)
        r.S_h_ef = r.cola_h.S * math.cos(g) ** 2
        r.S_v_ef = r.cola_h.S * math.sin(g) ** 2
    if av.con_fuselaje:
        try:
            r.fus = datos_fuselaje(p.fuselaje)
        except ErrorGeometria as e:
            r.avisos.append(f"Fuselaje no incluido: {e}")

    # punto neutro: red de vórtices (ala y cola juntas); si falla, fórmulas clásicas
    r.metodo_np = "fórmulas clásicas"
    try:
        w.cla, w.x_ca = resolver(paneles_avion(p, incluir_cola=False), w.S, w.cma, w.x_ca)
        if r.cola_h is not None:
            r.cla_total, r.x_np = resolver(paneles_avion(p), w.S, w.cma, w.x_ca)
        else:
            r.cla_total, r.x_np = w.cla, w.x_ca
        r.metodo_np = "red de vórtices"
    except (np.linalg.LinAlgError, ValueError, ZeroDivisionError):
        if r.cola_h is not None:
            deps = 2 * w.cla / (math.pi * w.AR)
            k = ETA_COLA * (r.S_h_ef / w.S) * (r.cola_h.cla / w.cla) * (1 - deps)
            r.x_np = (w.x_ca + k * r.cola_h.x_ca) / (1 + k)
        else:
            r.x_np = w.x_ca
    # el fuselaje adelanta el punto neutro (Gilruth-Multhopp, coeficiente K_f aproximado)
    r.dx_fus = 0.0
    if r.fus is not None and r.fus.largo > 0:
        pos = min(max((w.x_ba_cma + 0.25 * w.cma) / r.fus.largo, 0.05), 0.7)
        kf = 0.0011 * math.exp(5.3 * pos)                        # por grado
        dcm = kf * r.fus.ancho ** 2 * r.fus.largo / (w.S * w.cma)   # ΔCmα por grado
        r.dx_fus = -dcm / math.radians(r.cla_total if hasattr(r, "cla_total") else w.cla) * w.cma
        r.x_np += r.dx_fus
    r.x_cg_rec = r.x_np - av.margen / 100 * w.cma

    # pesos estimados
    mg = av.densidad * 1e-6            # g por mm³ (kg/m³ -> g/mm³)
    for s in (w, r.cola_h, r.cola_v):
        if s is not None:
            r.pesos.append((f"{s.nombre} (porexpán)", s.volumen * mg, s.x_cg))
    if r.fus is not None:
        r.pesos.append(("Fuselaje (porexpán)", r.fus.volumen * mg, r.fus.x_cg))
    for c in av.componentes:
        r.pesos.append((c.nombre, c.masa, c.x))
    r.peso_est = sum(m for _, m, _ in r.pesos)
    r.cg_est = sum(m * x for _, m, x in r.pesos) / r.peso_est if r.peso_est else 0.0

    # informe
    L = r.lineas
    peso = av.peso if av.peso > 0 else r.peso_est
    cg = av.cg if av.cg > 0 else r.cg_est
    if av.peso <= 0 or av.cg <= 0:
        r.avisos.append("Aún no has puesto tu peso o tu CG: se usa la estimación.")
    S = w.S * 1e-6
    W = peso / 1000 * G
    V = av.velocidad
    q = 0.5 * RHO * V * V
    L += ["GEOMETRÍA",
          f"Ala: envergadura {w.b:.0f} mm, superficie {w.S / 1e4:.1f} dm², alargamiento {w.AR:.1f}, "
          f"CMA {w.cma:.0f} mm (BA de la CMA a {w.x_ba_cma - av.x_ala:.0f} mm del BA de la raíz)"]
    if r.cola_h is not None:
        lh = r.cola_h.x_ca - cg
        vh = r.S_h_ef * lh / (w.S * w.cma)
        L.append(f"{r.cola_h.nombre}: {r.cola_h.S / 1e4:.1f} dm² (horizontal efectiva {r.S_h_ef / 1e4:.1f} dm²), "
                 f"brazo {lh:.0f} mm, volumen de cola horizontal Vh = {vh:.2f}  (normal 0,35–0,60)")
        if not 0.3 <= vh <= 0.7:
            r.avisos.append(f"Volumen de cola horizontal {vh:.2f} fuera de lo habitual (0,35–0,60).")
    if r.S_v_ef > 0:
        x_cv = r.cola_v.x_ca if r.cola_v is not None else r.cola_h.x_ca
        vv = r.S_v_ef * (x_cv - cg) / (w.S * w.b)
        L.append(f"Superficie vertical efectiva {r.S_v_ef / 1e4:.1f} dm², volumen de cola vertical "
                 f"Vv = {vv:.3f}  (normal 0,02–0,05)")
        if not 0.015 <= vv <= 0.06:
            r.avisos.append(f"Volumen de cola vertical {vv:.3f} fuera de lo habitual (0,02–0,05).")
    if r.fus is not None:
        L.append(f"Fuselaje: {r.fus.largo:.0f} mm de largo, {r.fus.ancho:.0f} × {r.fus.alto:.0f} mm")

    margen_real = (r.x_np - cg) / w.cma * 100
    L += ["", "ESTABILIDAD",
          f"Punto neutro ({r.metodo_np}" + (f", fuselaje {r.dx_fus:+.0f} mm" if r.dx_fus else "") + "): "
          f"{r.x_np:.0f} mm del morro = {r.x_np - av.x_ala:.0f} mm del BA de la raíz "
          f"({(r.x_np - w.x_ba_cma) / w.cma * 100:.0f}% de la CMA)",
          f"CG recomendado (margen {av.margen:g}%): {r.x_cg_rec:.0f} mm del morro = "
          f"{r.x_cg_rec - av.x_ala:.0f} mm del BA de la raíz",
          f"Tu CG: {cg:.0f} mm del morro = {cg - av.x_ala:.0f} mm del BA de la raíz  →  margen estático "
          f"{margen_real:.0f}%"]
    if margen_real < 3:
        r.avisos.append(f"Margen estático {margen_real:.0f}%: el CG está demasiado atrás, el avión será inestable.")
    elif margen_real > 25:
        r.avisos.append(f"Margen estático {margen_real:.0f}%: muy pesado de morro, le costará levantarlo.")
    if av.tipo_cola == "sin_cola" and w.cm0 < 0:
        r.avisos.append(f"Ala volante con Cm0 del perfil {w.cm0:.3f} (negativo): necesita perfil reflex "
                        f"o flecha con torsión para equilibrar.")

    # vuelo
    cl = W / (q * S)
    alfa = w.alfa0 + math.degrees(cl / w.cla)
    v_perd = math.sqrt(2 * W / (RHO * S * 0.9 * av.cl_max)) if av.cl_max > 0 else 0.0
    re_cma = V * w.cma / 1000 / NU
    polar = Polar(r)
    cd0, e = polar.cd0(V), polar.e
    cdi = cl * cl / (math.pi * e * w.AR)
    D = q * S * (cd0 + cdi)
    cl_opt = math.sqrt(cd0 * math.pi * e * w.AR)
    v_opt = math.sqrt(2 * W / (RHO * S * cl_opt))
    L += ["", f"VUELO  (peso {peso:.0f} g, {V:g} m/s = {V * 3.6:.0f} km/h)",
          f"Carga alar {peso / (w.S / 1e4):.1f} g/dm²  ·  Reynolds en la CMA {re_cma:,.0f}".replace(",", "."),
          f"CL necesario {cl:.2f}  →  ángulo del ala {alfa:.1f}° respecto a la referencia "
          f"(α de sustentación nula {w.alfa0:.1f}°)",
          f"Velocidad de pérdida ≈ {v_perd:.1f} m/s ({v_perd * 3.6:.0f} km/h) con CLmax del perfil {av.cl_max:g}",
          f"Resistencia: CD0 {cd0:.4f} ({ACABADOS.get(av.acabado, '').lower()}) + inducida {cdi:.4f} "
          f"(Oswald {e:.2f})  →  {D:.2f} N ({D / G * 1000:.0f} gf)",
          f"Finura L/D {cl / (cd0 + cdi):.1f}  ·  potencia en vuelo {D * V:.1f} W "
          f"(≈ {D * V / 0.5:.0f} W eléctricos con hélice y motor al 50%)",
          f"Mejor finura hacia {v_opt:.1f} m/s ({v_opt * 3.6:.0f} km/h)"]
    if cl > 0.9 * av.cl_max:
        r.avisos.append(f"A {V:g} m/s necesita CL {cl:.2f}: está cerca de la pérdida.")
    info_motor = {}
    if av.motor.activa:
        try:
            L += propulsion(av, polar, peso, v_perd, r.avisos, info_motor)
        except (ValueError, ZeroDivisionError) as ex:
            r.avisos.append(f"Motor y hélice: {ex}")
    v_mandos = av.v_mandos if av.v_mandos > 0 else info_motor.get("vmax") or 1.5 * V
    L += brazo_cola(p, r, cg)
    L += mandos(p, r, polar, cg, peso, v_mandos, v_perd)
    L += ["", "PESOS ESTIMADOS"] + [f"  {n}: {m:.0f} g a {x:.0f} mm" for n, m, x in r.pesos] + [
        f"  Total estimado {r.peso_est:.0f} g, CG estimado {r.cg_est:.0f} mm del morro "
        f"({r.cg_est - av.x_ala:.0f} mm del BA de la raíz)"]
    return r


# ---------------------------------------------------------------- resistencia a cualquier velocidad
class Polar:
    """Resistencia del avión: fricción de placa plana de cada pieza + inducida."""

    def __init__(self, r):
        w = r.ala
        self.S = w.S * 1e-6
        self.AR = w.AR
        self.cla = w.cla
        self.alfa0 = w.alfa0
        self.piezas = [(w.mojada, w.cma, 1 + 2 * w.tc + 60 * w.tc ** 4)]
        for s in (r.cola_h, r.cola_v):
            if s is not None:
                self.piezas.append((s.mojada, s.cma, 1 + 2 * s.tc + 60 * s.tc ** 4))
        if r.fus is not None:
            fin = r.fus.largo / max(1.0, (r.fus.ancho + r.fus.alto) / 2)
            self.piezas.append((r.fus.mojada, r.fus.largo, 1 + 60 / fin ** 3 + fin / 400))
        self.Sref = w.S
        self.laminar = LAMINAR.get(r.acabado, 0.2)
        self.e = min(0.95, max(0.6, 1.78 * (1 - 0.045 * w.AR ** 0.68) - 0.64))

    def cd0(self, V):
        V = max(V, 0.5)
        return 1.1 * sum(_cf(V * lon / 1000 / NU, self.laminar) * ff * moj for moj, lon, ff in self.piezas) / self.Sref

    def resistencia(self, V, cl):
        q = 0.5 * RHO * V * V
        return q * self.S * (self.cd0(V) + cl * cl / (math.pi * self.e * self.AR))


# ---------------------------------------------------------------- motor, batería y hélice
V_CELDA = 3.85      # V por celda a media carga


def _helice(m, J):
    """Coeficientes de empuje y potencia (aproximados a partir de paso/diámetro)."""
    pd = m.paso / m.diametro
    jz = 1.05 * pd                       # avance al que la hélice deja de empujar
    k = (m.palas / 2) ** 0.75
    x = min(max(J / jz, 0.0), 1.2)
    ct = k * (0.060 + 0.07 * pd) * max(0.0, 1 - x)   # ajustado a ensayos de una hélice de 10x4,7
    cp = k * (0.018 + 0.073 * pd) * max(0.15, 1 - 0.6 * x * x)
    return ct, cp


def punto_funcionamiento(m, gas, V):
    """Revoluciones, corrientes, potencia y empuje con el gas (0-1) a la velocidad V (m/s).
    Se busca dónde el par del motor iguala el de la hélice."""
    if m.kv <= 0 or m.diametro <= 0 or m.celdas < 1:
        raise ValueError("revisa Kv, diámetro de la hélice y celdas")
    D = m.diametro * 0.0254
    kvr = m.kv * 2 * math.pi / 60                    # rad/s por voltio
    vb = m.celdas * V_CELDA
    rb = m.celdas * m.r_celda / 1000
    rm = m.rm / 1000

    def i_motor(n):
        return (gas * vb - 2 * math.pi * n / kvr) / (rm + gas * gas * rb)

    def resto(n):
        ct, cp = _helice(m, V / (n * D))
        par_helice = cp * RHO * n * n * D ** 5 / (2 * math.pi)
        return (i_motor(n) - m.i0) / kvr - par_helice

    lo, hi = 1.0, gas * vb * kvr / (2 * math.pi)
    if hi <= lo or resto(lo) <= 0:
        return dict(n=0.0, rpm=0.0, im=0.0, ib=0.0, empuje=0.0, p_bat=0.0, v_bat=vb)
    for _ in range(60):
        mid = (lo + hi) / 2
        if resto(mid) > 0:
            lo = mid
        else:
            hi = mid
    n = (lo + hi) / 2
    im = max(0.0, i_motor(n))
    ib = gas * im
    ct, _ = _helice(m, V / (n * D))
    return dict(n=n, rpm=n * 60, im=im, ib=ib, empuje=ct * RHO * n * n * D ** 4,
                p_bat=ib * (vb - ib * rb), v_bat=vb - ib * rb)


def propulsion(av, polar, peso, v_perd, avisos, info=None):
    """Líneas del informe de motor, batería y hélice."""
    m = av.motor
    W = peso / 1000 * G
    masa = peso / 1000
    i_bat_max = m.c * m.capacidad / 1000
    est = punto_funcionamiento(m, 1.0, 0.0)
    paso_v = est["rpm"] * m.paso * 0.0254 / 60
    L = ["", f"MOTOR Y HÉLICE  ({m.celdas}S {m.capacidad:g} mAh {m.c:g}C · {m.kv:g} kv · "
             f"{m.diametro:g}x{m.paso:g}{'' if m.palas == 2 else f' {m.palas} palas'})",
         f"A tope, parado: {est['rpm']:.0f} rpm, {est['ib']:.1f} A, {est['p_bat']:.0f} W, "
         f"empuje {est['empuje'] / G * 1000:.0f} g (empuje/peso {est['empuje'] / W:.2f})",
         f"Velocidad de paso de la hélice {paso_v:.1f} m/s ({paso_v * 3.6:.0f} km/h)"]
    if est["im"] > m.i_max:
        avisos.append(f"A tope el motor pide {est['im']:.0f} A y su máximo es {m.i_max:g} A: hélice demasiado grande.")
    if est["ib"] > i_bat_max:
        avisos.append(f"A tope se piden {est['ib']:.0f} A y la batería da {i_bat_max:.0f} A ({m.c:g}C).")
    if est["empuje"] / W < 0.35:
        avisos.append(f"Empuje/peso {est['empuje'] / W:.2f}: muy justo para despegar y subir.")
    if paso_v < 1.5 * v_perd:
        avisos.append("La velocidad de paso de la hélice es baja para este avión: subirá y correrá poco.")

    # despegue: tiempo y distancia hasta la velocidad de rotación (1,2 · pérdida) a tope de gas
    vr = 1.2 * v_perd
    cl_suelo = polar.cla * math.radians(-polar.alfa0)
    mano = m.despegue == "mano"
    v = m.v_lanzamiento if mano else 0.0
    t = x = 0.0
    while v < vr and t < 30:
        q = 0.5 * RHO * v * v
        sust = min(q * polar.S * cl_suelo, W)
        empuje = punto_funcionamiento(m, 1.0, v)["empuje"]
        res = polar.resistencia(v, W / (q * polar.S)) if mano and v > 0.5 else polar.resistencia(v, cl_suelo)
        roz = 0.0 if mano else m.rozamiento * (W - sust)
        a = (empuje - res - roz) / masa
        if a <= 0:
            break
        dt = 0.02
        v += a * dt
        x += v * dt
        t += dt
    como = f"lanzado a mano a {m.v_lanzamiento:g} m/s" if mano else f"rodando (rodadura {m.rozamiento:g})"
    if v >= vr:
        L.append(f"Despegue {como}: alcanza la velocidad de rotación ({vr:.1f} m/s = {vr * 3.6:.0f} km/h) "
                 f"en {t:.1f} s y {x:.0f} m")
    else:
        L.append(f"Despegue {como}: NO alcanza la velocidad de rotación ({vr:.1f} m/s): "
                 f"se queda en {v:.1f} m/s")
        avisos.append("Con este motor y hélice no llega a la velocidad de despegue.")

    # velocidad máxima en horizontal
    vmax = 0.0
    for vv in np.arange(max(v_perd, 1.0), 60, 0.25):
        if punto_funcionamiento(m, 1.0, vv)["empuje"] >= polar.resistencia(vv, W / (0.5 * RHO * vv * vv * polar.S)):
            vmax = vv
    L.append(f"Velocidad máxima en horizontal ≈ {vmax:.1f} m/s ({vmax * 3.6:.0f} km/h)")
    if info is not None:
        info["vmax"] = vmax

    # crucero: gas necesario, consumo y autonomía
    V = av.velocidad
    D = polar.resistencia(V, W / (0.5 * RHO * V * V * polar.S))
    lo, hi = 0.0, 1.0
    if punto_funcionamiento(m, 1.0, V)["empuje"] < D:
        L.append(f"A {V:g} m/s no puede mantener el vuelo horizontal ni a tope de gas.")
    else:
        for _ in range(40):
            mid = (lo + hi) / 2
            if punto_funcionamiento(m, mid, V)["empuje"] < D:
                lo = mid
            else:
                hi = mid
        cr = punto_funcionamiento(m, hi, V)
        util = 0.8 * m.capacidad / 1000          # se usa el 80% de la batería
        a_tope = punto_funcionamiento(m, 1.0, V)
        subida = (a_tope["empuje"] - D) * V / W
        L += [f"Crucero a {V:g} m/s: gas {hi * 100:.0f}%, {cr['ib']:.1f} A, {cr['p_bat']:.0f} W  →  "
              f"autonomía ≈ {util / cr['ib'] * 60:.0f} min" if cr["ib"] > 0 else "",
              f"A tope de gas: autonomía ≈ {util / est['ib'] * 60:.1f} min  ·  subida a {V:g} m/s ≈ {subida:.1f} m/s"
              if est["ib"] > 0 else ""]
    return [l for l in L if l]


# ---------------------------------------------------------------- superficies de control
_cache_placa = {}
FACTOR_VISCOSO = 0.6     # los momentos de bisagra reales son ~60% de los de la teoría de placa plana


def placa_con_timon(E):
    """Placa plana (cuerda 1) con un timón del E de la cuerda, por vórtices discretos.
    Devuelve por radián: eficacia tau (dCl/dδ / 2π), dCm_c/4/dδ, Ch_δ, Ch_α (coef. de bisagra)."""
    E = round(min(max(E, 0.05), 0.6), 3)
    if E not in _cache_placa:
        n = 200
        xe = (1 - np.cos(np.linspace(0, np.pi, n + 1))) / 2
        dx = np.diff(xe)
        xv, xc = xe[:-1] + dx / 4, xe[:-1] + 3 * dx / 4
        A = 1 / (2 * np.pi * (xc[:, None] - xv[None, :]))
        xh = 1 - E
        flap = xv > xh
        res = []
        for pend in (np.where(xc > xh, 1.0, 0.0), np.ones(n)):    # timón deflectado / placa con ángulo
            g = np.linalg.solve(A, pend)
            res.append((2 * g.sum(), -2 * np.sum(g * (xv - 0.25)), -2 * np.sum(g[flap] * (xv[flap] - xh)) / E ** 2))
        (cl_d, cm_d, ch_d), (_, _, ch_a) = res
        _cache_placa[E] = (cl_d / (2 * np.pi), cm_d, ch_d, ch_a)
    return _cache_placa[E]


def _mando(ala, mitades, sep=0.0, diedro=0.0):
    """Geometría del timón cortado en un panel (con la V del alerón): None si no hay."""
    al = ala.aleron
    if not al.activo:
        return None
    L = ala.envergadura
    a, b = (al.desde, al.hasta if al.hasta > 0 else L) if al.dividir else (0.0, L)
    y = np.linspace(a, b, 60)
    c = ala.cuerda_raiz + (ala.cuerda_punta - ala.cuerda_raiz) * y / L
    cf = al.cuerda_raiz + (al.cuerda_punta - al.cuerda_raiz) * y / L
    yabs = sep / 2 + y * math.cos(math.radians(diedro))
    return dict(Sf=mitades * float(np.trapezoid(cf, y)), E=float(np.trapezoid(cf, y) / np.trapezoid(c, y)),
                cf=float(np.mean(cf)), envergadura=b - a, momento_c=float(np.trapezoid(c * yabs, y)),
                v=al.angulo, a=a, b=b)


def _servo(nombre, m, q, ar, delta, alfa, servo, avisos):
    """Línea con el momento de bisagra frente al par del servo."""
    tau, _, ch_d, ch_a = placa_con_timon(m["E"])
    k3d = ar / (ar + 2) * FACTOR_VISCOSO
    ch = k3d * (ch_d * math.radians(delta) + ch_a * math.radians(alfa))
    H = abs(q * (m["Sf"] / 2 * 1e-6) * (m["cf"] / 1000) * ch)        # N·m por cada superficie (una mitad)
    kgcm = H / G * 100
    uso = kgcm / servo * 100 if servo > 0 else 999
    estado = "bien" if uso <= 50 else "justo" if uso <= 80 else "INSUFICIENTE"
    if uso > 80:
        avisos.append(f"{nombre}: el servo va al {uso:.0f}% de su par: pon uno más fuerte o reduce recorrido.")
    if delta > m["v"] + 0.5:
        avisos.append(f"{nombre}: pides {delta:g}° y con la V de {m['v']:g}° solo puede bajar {m['v']:g}° "
                      f"(bisagra arriba).")
    return (f"  {nombre}: {m['Sf'] / 1e4:.2f} dm² ({m['E'] * 100:.0f}% de la cuerda, eficacia {tau:.2f})  ·  "
            f"bisagra {kgcm:.2f} kg·cm por servo a {delta:g}° → {uso:.0f}% del servo ({estado})")


def mandos(p, r, polar, cg, peso, v_mandos, v_perd):
    av, w = p.avion, r.ala
    L = ["", f"MANDOS  (fuerzas a {v_mandos:.1f} m/s = {v_mandos * 3.6:.0f} km/h y recorrido máximo; "
             f"supone brazo del servo = brazo del mando)"]
    q = 0.5 * RHO * v_mandos ** 2
    S, b, c = w.S, w.b, w.cma
    W = peso / 1000 * G
    alfa_vmax = w.alfa0 + math.degrees(W / (q * S * 1e-6) / w.cla) if q > 0 else 0.0
    cl_cruce = W / (0.5 * RHO * av.velocidad ** 2 * S * 1e-6)
    cl_max = 0.9 * av.cl_max
    margen = (r.x_np - cg) / c
    hay = False

    # alerones (o elevones en ala volante)
    ma = _mando(p.ala, 2, av.separacion_raices, av.diedro_ala)
    if ma:
        hay = True
        nombre = "Elevones" if av.tipo_cola == "sin_cola" else "Alerones"
        L.append(_servo(nombre, ma, q, w.AR, av.recorrido_aleron, alfa_vmax, av.servo_aleron, r.avisos))
        tau = placa_con_timon(ma["E"])[0]
        lam = p.ala.cuerda_punta / p.ala.cuerda_raiz
        clp = -w.cla / 6 * (1 + 3 * lam) / (1 + lam)
        cl_da = 2 * w.cla * tau * ma["momento_c"] / (S * b)
        pb2v = cl_da * math.radians(av.recorrido_aleron) / -clp
        p_gs = math.degrees(pb2v * 2 * av.velocidad / (b / 1000))
        tipo = ("lento" if pb2v < 0.05 else "normal" if pb2v <= 0.09 else "rápido" if pb2v <= 0.13 else
                "muy rápido (acrobático)")
        L.append(f"     Alabeo: pb/2V = {pb2v:.3f} ({tipo})  →  unos {p_gs:.0f}°/s a {av.velocidad:g} m/s")
        if av.tipo_cola == "sin_cola":
            # profundidad con los elevones: lift del timón detrás del CG + momento propio
            cm_d = placa_con_timon(ma["E"])[1] * ma["Sf"] / S * w.AR / (w.AR + 2)
            dcl = w.cla * tau * ma["Sf"] / S
            x_timon = w.x_ba_cma + (1 - ma["E"] / 2) * c
            cm_delta = cm_d - dcl * (x_timon - cg) / c
            _profundidad(L, r.avisos, cm_delta, cl_max - cl_cruce, margen, av.recorrido_aleron, "elevones")
    else:
        L.append("  Alerones: no hay (actívalos en la pestaña Alerón del ala para calcularlos)")

    # profundidad
    if av.tipo_cola in ("convencional", "v"):
        me = _mando(p.estabilizador, 2)
        nombre = "Timones de la V" if av.tipo_cola == "v" else "Profundidad"
        if me:
            hay = True
            h = r.cola_h
            L.append(_servo(nombre, me, q, h.AR, av.recorrido_profundidad, 0.0, av.servo_profundidad, r.avisos))
            tau = placa_con_timon(me["E"])[0]
            vh = r.S_h_ef * (h.x_ca - cg) / (S * c)
            cm_delta = -ETA_COLA * vh * h.cla * tau * me["Sf"] / h.S
            _profundidad(L, r.avisos, cm_delta, cl_max - cl_cruce, margen, av.recorrido_profundidad, "profundidad")
        else:
            L.append(f"  {nombre}: no hay (actívala en la pestaña Timón del estabilizador)")

    # dirección
    if av.tipo_cola == "convencional":
        md = _mando(p.deriva, 1)
        if md:
            hay = True
            v_ = r.cola_v
            L.append(_servo("Dirección", md, q, v_.AR, av.recorrido_direccion, 0.0, av.servo_direccion, r.avisos))
            tau = placa_con_timon(md["E"])[0]
            vv = r.S_v_ef * (v_.x_ca - cg) / (S * b)
            cn = ETA_COLA * vv * v_.cla * tau * md["Sf"] / v_.S
            tipo = "poca" if cn < 0.04 else "normal" if cn <= 0.12 else "mucha"
            L.append(f"     Eficacia de dirección Cnδ = {cn:.3f} /rad ({tipo}; normal 0,04–0,12)")
        else:
            L.append("  Dirección: no hay (actívala en la pestaña Timón de la deriva)")
    elif av.tipo_cola == "v":
        L.append(f"  En la cola en V los mismos timones hacen de dirección (eficacia ∝ sen² {av.angulo_v:g}°)")
    if hay:
        L.append("  (Momentos de bisagra estimados con placa plana × 0,6; el par real suele ser algo menor.)")
    return L


def _profundidad(L, avisos, cm_delta, dcl, margen, recorrido, nombre):
    """Grados de timón para llevar el avión desde el crucero hasta la pérdida con este CG."""
    if cm_delta >= 0 or dcl <= 0:
        return
    necesario = math.degrees(dcl * margen / -cm_delta)
    L.append(f"     Para llegar a la pérdida desde el crucero hacen falta ≈ {necesario:.0f}° de {nombre} "
             f"(tienes {recorrido:g}°)")
    if necesario > recorrido:
        avisos.append(f"Con este CG la {nombre} no basta para llevar el avión a la pérdida (aterrizajes con "
                      f"poco control): CG más atrás, más recorrido o timón más grande.")
    elif necesario < 0.3 * recorrido:
        avisos.append(f"Sobra mucho recorrido de {nombre}: el avión será muy sensible en cabeceo.")


def brazo_cola(p, r, cg):
    """Evalúa la distancia de la cola y propone superficies para unos volúmenes de cola normales."""
    if r.cola_h is None:
        return []
    w = r.ala
    lh = r.cola_h.x_ca - cg
    k = lh / w.cma
    tipo = ("muy corta" if k < 2.0 else "algo corta" if k < 2.5 else "buena" if k <= 4.0 else "larga")
    L = ["", "DISTANCIA DE LA COLA",
         f"Brazo de cola {lh:.0f} mm = {k:.1f} cuerdas medias ({tipo}; lo habitual es 2,5–4)  ·  "
         f"{lh / w.b * 100:.0f}% de la envergadura"]
    if k < 2.5:
        L.append("  Cola cerca: hace falta más estabilizador, el avión es más sensible al CG y amortigua "
                 "menos el cabeceo.")
    elif k > 4.0:
        L.append("  Cola lejos: muy estable y basta un estabilizador pequeño, pero el fuselaje pesa más "
                 "detrás y obliga a más peso en el morro.")
    s_h = 0.45 * w.S * w.cma / lh
    texto = (f"Para Vh = 0,45 con este brazo: estabilizador de {s_h / 1e4:.1f} dm² "
             f"(tienes {r.S_h_ef / 1e4:.1f} dm² efectivos)")
    if p.avion.tipo_cola == "v":
        texto += f" → cola en V de {s_h / math.cos(math.radians(p.avion.angulo_v)) ** 2 / 1e4:.1f} dm² en total"
    L.append(texto)
    if r.S_v_ef > 0:
        x_cv = r.cola_v.x_ca if r.cola_v is not None else r.cola_h.x_ca
        s_v = 0.035 * w.S * w.b / (x_cv - cg)
        L.append(f"Para Vv = 0,035: superficie vertical de {s_v / 1e4:.1f} dm² (tienes {r.S_v_ef / 1e4:.1f} dm²)")
    return L


# ---------------------------------------------------------------- dibujo y 3D
def _panel_3d(spec_r, spec_t, ala, x_ba, raiz, dir_env, normal, color, n=50):
    """Parte 3D de un panel: secciones de raíz y punta colocadas en el avión."""
    def seccion(spec, cuerda, torsion, origen):
        P = contorno_perfil(spec, n)
        u, v = P[:, 0] * cuerda, P[:, 1] * cuerda
        piv = ala.pivote_torsion / 100 * cuerda
        th = math.radians(torsion)
        du = u - piv
        u, v = piv + du * math.cos(th) - v * math.sin(th), du * math.sin(th) + v * math.cos(th)
        return origen + np.outer(u, (1, 0, 0)) + np.outer(v, normal)
    o_r = np.array([x_ba, *raiz], float)
    o_t = o_r + np.array([ala.flecha, 0, 0]) + ala.envergadura * np.array([0, *dir_env])
    return Parte(seccion(spec_r, ala.cuerda_raiz, ala.torsion_raiz, o_r),
                 seccion(spec_t, ala.cuerda_punta, ala.torsion_punta, o_t), color)


def partes_avion(p, r):
    """Avión montado en 3D (coordenadas x, y, z)."""
    av = p.avion
    partes = []
    g = math.radians(av.diedro_ala)
    for lado in (1, -1):
        partes.append(_panel_3d(p.ala.perfil_raiz, p.ala.perfil_punta, p.ala, av.x_ala,
                                (lado * av.separacion_raices / 2, av.z_ala),
                                (lado * math.cos(g), math.sin(g)), (0, -lado * math.sin(g), math.cos(g)), "#7fa8dc"))
    e = p.estabilizador
    if av.tipo_cola in ("convencional", "v"):
        gv = math.radians(av.angulo_v if av.tipo_cola == "v" else 0)
        for lado in (1, -1):
            partes.append(_panel_3d(e.perfil_raiz, e.perfil_punta, e, av.x_estab, (0, av.z_estab),
                                    (lado * math.cos(gv), math.sin(gv)), (0, -lado * math.sin(gv), math.cos(gv)),
                                    "#e8a35a"))
    if av.tipo_cola == "convencional":
        d = p.deriva
        partes.append(_panel_3d(d.perfil_raiz, d.perfil_punta, d, av.x_deriva, (0, av.z_deriva), (0, 1), (0, 1, 0),
                                "#e8a35a"))
    if r.fus is not None and len(r.fus.cuadernas) > 1:
        for (x1, c1), (x2, c2) in zip(r.fus.cuadernas, r.fus.cuadernas[1:]):
            a = np.column_stack([np.full(len(c1), x1), c1])
            b = np.column_stack([np.full(len(c2), x2), c2])
            partes.append(Parte(a, b, "#b9b9b9", tapas=False))
    return partes


def planta_avion(p, r):
    """Polígonos de la vista en planta [(puntos (x, y), color)]."""
    av = p.avion
    pol = []
    if r.fus is not None:
        pol.append((r.fus.planta, "#d9d9d9"))

    def trapecio(ala, x_ba, y0, lado, ang):
        y1 = y0 + lado * ala.envergadura * math.cos(math.radians(ang))
        return np.array([(x_ba, y0), (x_ba + ala.flecha, y1), (x_ba + ala.flecha + ala.cuerda_punta, y1),
                         (x_ba + ala.cuerda_raiz, y0)])
    for lado in (1, -1):
        pol.append((trapecio(p.ala, av.x_ala, lado * av.separacion_raices / 2, lado, av.diedro_ala), "#7fa8dc"))
        if av.tipo_cola in ("convencional", "v"):
            pol.append((trapecio(p.estabilizador, av.x_estab, 0, lado, av.angulo_v if av.tipo_cola == "v" else 0),
                        "#e8a35a"))
    if av.tipo_cola == "convencional":
        d = p.deriva
        t = 0.1 * d.cuerda_raiz / 2
        pol.append((np.array([(av.x_deriva, -t), (av.x_deriva + d.cuerda_raiz, 0), (av.x_deriva, t)]), "#c97a2a"))
    return pol


def lateral_avion(p, r):
    """Polígonos de la vista lateral [(puntos (x, z), color)]."""
    av = p.avion
    pol = []
    if r.fus is not None:
        pol.append((r.fus.lateral, "#d9d9d9"))

    def perfil(ala, x_ba, z, calado=0.0):
        P = contorno_perfil(ala.perfil_raiz, 40) * ala.cuerda_raiz
        th = math.radians(ala.torsion_raiz - calado)
        u, v = P[:, 0], P[:, 1]
        return np.column_stack([x_ba + u * math.cos(th) - v * math.sin(th), z + u * math.sin(th) + v * math.cos(th)])
    pol.append((perfil(p.ala, av.x_ala, av.z_ala), "#7fa8dc"))
    if av.tipo_cola in ("convencional", "v"):
        e = p.estabilizador
        if av.tipo_cola == "v":
            h = e.envergadura * math.sin(math.radians(av.angulo_v))
            pol.append((np.array([(av.x_estab, av.z_estab), (av.x_estab + e.flecha, av.z_estab + h),
                                  (av.x_estab + e.flecha + e.cuerda_punta, av.z_estab + h),
                                  (av.x_estab + e.cuerda_raiz, av.z_estab)]), "#e8a35a"))
        else:
            pol.append((perfil(e, av.x_estab, av.z_estab, av.calado_estab), "#e8a35a"))
    if av.tipo_cola == "convencional":
        d = p.deriva
        pol.append((np.array([(av.x_deriva, av.z_deriva), (av.x_deriva + d.flecha, av.z_deriva + d.envergadura),
                              (av.x_deriva + d.flecha + d.cuerda_punta, av.z_deriva + d.envergadura),
                              (av.x_deriva + d.cuerda_raiz, av.z_deriva)]), "#e8a35a"))
    return pol
