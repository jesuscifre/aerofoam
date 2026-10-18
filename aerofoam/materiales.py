"""Materiales de corte: densidad, acabado, velocidad y kerf por defecto.

La lista se guarda en la configuración del usuario (materiales.json, junto a maquina.json),
no en cada proyecto. Al elegir un material en un proyecto se copian sus valores a la
pestaña Corte (velocidad y kerf) y a la pestaña Avión (densidad y acabado).
"""
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Material:
    nombre: str = "Material"
    densidad: float = 20.0       # kg/m³
    acabado: str = "rugoso"      # 'rugoso' | 'cinta' | 'liso' (para la resistencia)
    velocidad: float = 150.0     # velocidad de corte (la F, según el modo de cálculo de la F)
    kerf: float = 1.0            # mm
    notas: str = ""


XPS = "XPS (poliestireno extruido)"


def de_fabrica():
    return [
        Material(XPS, 33.0, "cinta", 50.0, 1.0,
                 "Medido: 13 V, 11,7 W, hilo de 800 mm: corte bueno a 50, más rápido se queda atrás."),
        Material("Porexpán blanco EPS 15 kg/m³", 15.0, "rugoso", 200.0, 1.2, "Orientativo: calíbralo."),
        Material("Porexpán blanco EPS 20 kg/m³", 20.0, "rugoso", 180.0, 1.1, "Orientativo: calíbralo."),
        Material("Porexpán alta densidad EPS 25-30", 28.0, "rugoso", 140.0, 1.0, "Orientativo: calíbralo."),
    ]


def cargar(ruta):
    ruta = Path(ruta)
    if not ruta.exists():
        return de_fabrica()
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        nombres = {f.name for f in fields(Material)}
        lista = [Material(**{k: v for k, v in d.items() if k in nombres}) for d in datos]
        return lista or de_fabrica()
    except (OSError, ValueError, TypeError):
        return de_fabrica()


def guardar(lista, ruta):
    Path(ruta).write_text(json.dumps([asdict(m) for m in lista], indent=1, ensure_ascii=False), encoding="utf-8")


def buscar(lista, nombre):
    return next((m for m in lista if m.nombre == nombre), None)


def aplicar(p, mat):
    """Copia los valores del material al proyecto."""
    c = p.corte
    c.material = mat.nombre
    c.vel_corte = c.vel_entrada = mat.velocidad
    c.kerf_raiz = c.kerf_punta = mat.kerf
    p.avion.densidad = mat.densidad
    p.avion.acabado = mat.acabado
