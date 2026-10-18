"""Datos del proyecto (ala + corte) y de la máquina, con guardado en JSON."""
import copy
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class Varilla:
    nombre: str = "Varilla"
    tipo: str = "redondo"          # 'marca' | 'redondo' | 'rectangular'
    superficie: str = "intrados"   # 'extrados' | 'intrados'
    pos_raiz: float = 60.0         # mm desde el borde de ataque de la raíz al centro
    pos_punta: float = 45.0        # mm desde el borde de ataque de la punta al centro
    diametro: float = 6.0          # redondo
    ancho: float = 6.0             # rectangular
    alto: float = 3.0              # rectangular: profundidad de la ranura
    prof_marca: float = 3.0        # marca: profundidad de la ranura fina
    centro: str = "mitad"          # redondo: 'mitad' (mitad del espesor) | 'profundidad'
    prof_centro: float = 5.0       # redondo: mm desde la superficie al centro
    inclinacion: float = 0.0       # marca/redondo: grados respecto a la perpendicular (+ hacia el BS)


@dataclass
class Aleron:
    """Alerón o flap con bisagra arriba: se corta una V abierta por abajo."""
    nombre = "Alerón"                  # (no es un campo; para los mensajes)
    activo: bool = False
    cuerda_raiz: float = 50.0          # mm desde el BS hasta la bisagra, en la raíz del panel
    cuerda_punta: float = 40.0         # ídem en la punta del panel
    angulo: float = 35.0               # apertura total de la V (grados)
    puente: float = 0.0                # mm de corcho bajo el extradós que no se cortan (0 = separa)
    dividir: bool = False              # partir el panel en tramos para que el alerón ocupe una parte
    desde: float = 0.0                 # mm desde la raíz donde empieza el alerón
    hasta: float = 0.0                 # mm desde la raíz donde acaba (0 = hasta la punta)


@dataclass
class Ala:
    recta: bool = False                # ala recta: la punta copia todo de la raíz
    perfil_raiz: str = "NACA 2412"
    perfil_punta: str = "NACA 2412"
    cuerda_raiz: float = 250.0
    cuerda_punta: float = 180.0
    envergadura: float = 500.0         # longitud del panel (distancia raíz-punta)
    flecha: float = 0.0                # desplazamiento del BA de la punta hacia atrás
    desplaz_vertical: float = 0.0      # desplazamiento vertical de la punta
    torsion_raiz: float = 0.0          # grados, positivo = morro abajo
    torsion_punta: float = 0.0
    pivote_torsion: float = 25.0       # % de la cuerda
    escala_espesor_raiz: float = 100.0
    escala_espesor_punta: float = 100.0
    recubrimiento_raiz: float = 0.0    # espesor del entelado/chapa a restar
    recubrimiento_punta: float = 0.0
    puntos: int = 120                  # puntos por superficie
    raiz_lado: str = "XY"              # torre en la que queda la raíz: 'XY' | 'ZA'
    varillas: list = field(default_factory=list)
    aleron: Aleron = field(default_factory=Aleron)
    # mezcla de perfiles de cada sección (0 = perfil raíz, 1 = perfil punta); la usan los tramos
    mezcla_raiz: float = 0.0
    mezcla_punta: float = 1.0


@dataclass
class Corte:
    material: str = "XPS (poliestireno extruido)"   # ver Opciones > Materiales
    dist_torre_bloque: float = 150.0   # torre XY -> cara del bloque más cercana
    # el cero es la esquina inferior del bloque del lado del borde de salida (sin homing)
    bloque_largo: float = 0.0          # medidas del bloque para dibujarlo y comprobar (0 = no)
    bloque_alto: float = 0.0
    x_inicio: float = 20.0             # esquina del bloque -> borde de salida (tramo de entrada)
    altura: float = 30.0               # ver referencia_altura
    referencia_altura: str = "bs"      # 'bs' (BS de la raíz) | 'base' (punto más bajo = margen)
    orientacion: str = "cuerda"        # 'cuerda' | 'intrados' | 'tramo' | 'min_alto' | 'manual'
    angulo_manual: float = 0.0         # grados, positivo = antihorario visto en la pantalla
    tramo_desde: float = 30.0          # 'tramo': % de cuerda de la raíz
    tramo_hasta: float = 90.0
    invertir: bool = False             # cortar el perfil boca abajo (extradós abajo)
    kerf_raiz: float = 1.0             # ancho quemado por el hilo
    kerf_punta: float = 1.0
    vel_corte: float = 50.0            # mm/min (F)
    vel_entrada: float = 50.0
    vel_varillas: float = 150.0
    vel_desplazamiento: float = 300.0
    modo_velocidad: str = "f_bruto"      # 'cara_rapida' | 'g93' | 'f_bruto'
    potencia: float = 1000.0           # valor S del M3
    precalentamiento: float = 3.0      # segundos de espera tras encender
    pausa_varillas: float = 0.0        # segundos de pausa en los cambios de dirección de las varillas
    # calibración: velocidades probadas y kerf medido ("velocidad:kerf ...")
    calib_velocidades: str = "60 100 150 200 250 300"
    calib_lado: float = 30.0
    calib_f_literal: bool = True       # las velocidades de la prueba son la F del G-code (F30 = F30)
    calib_tabla: str = ""


@dataclass
class Maquina:
    distancia_torres: float = 690.0
    recorrido_x: float = 900.0
    recorrido_y: float = 300.0
    vel_max: float = 300.0
    eje1: str = "X"
    eje2: str = "Y"
    eje3: str = "A"                    # torre 2 horizontal
    eje4: str = "Z"                    # torre 2 vertical
    decimales: int = 3
    cabecera: str = "G21\nG90\nG94"
    pie: str = "M2"
    encender: str = "M3 S{potencia}"
    apagar: str = "M5"


def _estabilizador():
    return Ala(perfil_raiz="NACA 0009", perfil_punta="NACA 0009", cuerda_raiz=130.0, cuerda_punta=90.0,
               envergadura=260.0, flecha=20.0)


def _deriva():
    return Ala(perfil_raiz="NACA 0009", perfil_punta="NACA 0009", cuerda_raiz=150.0, cuerda_punta=90.0,
               envergadura=170.0, flecha=50.0)


@dataclass
class Componente:
    nombre: str = "Componente"
    masa: float = 10.0          # g
    x: float = 100.0            # mm desde el morro


def _componentes():
    return [Componente("Motor", 60, 15), Componente("Variador", 25, 60), Componente("Batería", 150, 110),
            Componente("Receptor", 10, 180), Componente("Servos (x3)", 27, 300)]


@dataclass
class Propulsion:
    activa: bool = True
    # batería (LiPo)
    celdas: int = 3
    capacidad: float = 1300.0          # mAh
    c: float = 25.0                    # descarga máxima en C
    r_celda: float = 5.0               # resistencia interna por celda (mΩ)
    # motor sin escobillas
    kv: float = 1000.0                 # rpm/V
    rm: float = 100.0                  # resistencia del bobinado (mΩ)
    i0: float = 0.8                    # corriente en vacío (A)
    i_max: float = 20.0                # corriente máxima del motor (A)
    # hélice
    diametro: float = 10.0             # pulgadas
    paso: float = 4.7                  # pulgadas
    palas: int = 2
    # despegue
    despegue: str = "mano"             # 'mano' | 'rodando'
    v_lanzamiento: float = 5.0         # m/s al soltarlo a mano
    rozamiento: float = 0.08           # coeficiente de rodadura (asfalto 0,04, hierba 0,08-0,12)


@dataclass
class Avion:
    tipo_cola: str = "convencional"     # 'convencional' | 'v' | 'sin_cola' (ala volante)
    con_fuselaje: bool = True
    # posiciones: x hacia atrás desde el morro, z hacia arriba desde el eje del fuselaje (mm)
    x_ala: float = 230.0                # borde de ataque de la raíz del ala
    z_ala: float = 0.0
    diedro_ala: float = 2.0             # grados de cada mitad
    separacion_raices: float = 0.0      # mm entre las raíces de las dos mitades (0 = se unen en el centro)
    x_estab: float = 700.0              # borde de ataque de la raíz del estabilizador (o de la cola en V)
    z_estab: float = 10.0
    angulo_v: float = 40.0              # cola en V: grados de cada mitad sobre la horizontal
    calado_estab: float = 0.0           # incidencia del estabilizador respecto al ala (grados)
    x_deriva: float = 690.0
    z_deriva: float = 10.0
    # pesos
    densidad: float = 33.0              # kg/m³ del corcho (XPS ~33, porexpán blanco 15-20)
    componentes: list = field(default_factory=_componentes)
    peso: float = 0.0                   # g: el que se usa en los cálculos (0 = aún sin poner)
    cg: float = 0.0                     # mm desde el morro (0 = aún sin poner)
    # vuelo
    velocidad: float = 12.0             # m/s
    cl_max: float = 1.0                 # del perfil del ala
    margen: float = 10.0                # margen estático objetivo (% de la CMA)
    acabado: str = "cinta"              # 'rugoso' (porexpán sin forrar) | 'cinta' (cinta o film) | 'liso' (pintado)
    motor: Propulsion = field(default_factory=Propulsion)
    # mandos: recorrido máximo (°) y par de los servos (kg·cm)
    recorrido_aleron: float = 15.0
    recorrido_profundidad: float = 12.0
    recorrido_direccion: float = 20.0
    servo_aleron: float = 1.6
    servo_profundidad: float = 1.6
    servo_direccion: float = 1.6
    v_mandos: float = 0.0               # m/s para las fuerzas (0 = la velocidad máxima)


def _fuselaje():
    from .fuselaje import Fuselaje
    return Fuselaje()


@dataclass
class Proyecto:
    pieza: str = "ala"                             # 'ala' | 'estabilizador' | 'deriva' | 'fuselaje' | 'avion'
    ala: Ala = field(default_factory=Ala)
    corte: Corte = field(default_factory=Corte)
    # segunda ala (solo informativa): se corta girando el bloque 180°
    doble: bool = False                            # ya se ha preparado el ala 2
    ala2: Ala = field(default_factory=Ala)
    corte2: Corte = field(default_factory=Corte)   # solo se usan los CAMPOS_COLOCACION
    mismas_varillas: bool = True
    fuselaje: object = field(default_factory=_fuselaje)
    estabilizador: Ala = field(default_factory=_estabilizador)
    deriva: Ala = field(default_factory=_deriva)
    avion: Avion = field(default_factory=Avion)


# campos de Corte propios de cada ala; el resto (bloque, hilo, velocidades) es común
CAMPOS_COLOCACION = ("x_inicio", "altura", "referencia_altura", "orientacion", "angulo_manual",
                     "tramo_desde", "tramo_hasta", "invertir")


def proyecto_ala2(p):
    """Proyecto equivalente para cortar el ala 2 (en su propio sistema, cero en su esquina)."""
    corte = copy.deepcopy(p.corte)
    for c in CAMPOS_COLOCACION:
        setattr(corte, c, getattr(p.corte2, c))
    ala = copy.deepcopy(p.ala2)
    if p.mismas_varillas:
        ala.varillas = copy.deepcopy(p.ala.varillas)
    return Proyecto(ala=ala, corte=corte)


CAMPOS_PUNTA = {"perfil_punta": "perfil_raiz", "cuerda_punta": "cuerda_raiz",
                "torsion_punta": "torsion_raiz", "escala_espesor_punta": "escala_espesor_raiz",
                "recubrimiento_punta": "recubrimiento_raiz"}


def sincronizar_recta(a, corte=None):
    """En un ala recta copia los datos de la raíz a la punta (in situ)."""
    if not a.recta:
        return
    for punta, raiz in CAMPOS_PUNTA.items():
        setattr(a, punta, getattr(a, raiz))
    a.flecha = 0.0
    a.desplaz_vertical = 0.0
    if corte is not None:
        corte.kerf_punta = corte.kerf_raiz
    for v in a.varillas:
        v.pos_punta = v.pos_raiz
    a.aleron.cuerda_punta = a.aleron.cuerda_raiz


def _desde_dict(cls, d):
    nombres = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (d or {}).items() if k in nombres})


def proyecto_desde_dict(d):
    def ala(dd):
        a = _desde_dict(Ala, dd)
        a.varillas = [_desde_dict(Varilla, v) for v in (dd or {}).get("varillas", [])]
        a.aleron = _desde_dict(Aleron, (dd or {}).get("aleron"))
        return a
    return Proyecto(ala=ala(d.get("ala")), corte=_desde_dict(Corte, d.get("corte")),
                    doble=d.get("doble", False), ala2=ala(d.get("ala2")),
                    corte2=_desde_dict(Corte, d.get("corte2")), mismas_varillas=d.get("mismas_varillas", True),
                    pieza=d.get("pieza", "ala"), fuselaje=_desde_dict(type(_fuselaje()), d.get("fuselaje")),
                    estabilizador=ala(d["estabilizador"]) if "estabilizador" in d else _estabilizador(),
                    deriva=ala(d["deriva"]) if "deriva" in d else _deriva(),
                    avion=_avion(d.get("avion")))


def _avion(d):
    a = _desde_dict(Avion, d)
    if d and "componentes" in d:
        a.componentes = [_desde_dict(Componente, c) for c in d["componentes"]]
    a.motor = _desde_dict(Propulsion, (d or {}).get("motor"))
    return a


def guardar_proyecto(p, ruta):
    Path(ruta).write_text(json.dumps(asdict(p), indent=2, ensure_ascii=False), encoding="utf-8")


def cargar_proyecto(ruta):
    return proyecto_desde_dict(json.loads(Path(ruta).read_text(encoding="utf-8")))


def guardar_maquina(m, ruta):
    Path(ruta).write_text(json.dumps(asdict(m), indent=2, ensure_ascii=False), encoding="utf-8")


def cargar_maquina(ruta):
    ruta = Path(ruta)
    if not ruta.exists():
        return Maquina()
    return _desde_dict(Maquina, json.loads(ruta.read_text(encoding="utf-8")))
