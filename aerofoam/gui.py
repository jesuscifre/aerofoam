"""Interfaz gráfica de AeroFoam (tkinter + matplotlib)."""
import copy
import json
from dataclasses import replace
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Polygon, Rectangle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from . import __version__
from .bloque import calcular_bloque
from .gcode import MODOS, generar
from .geometria import ErrorGeometria, calcular
from .perfiles import interpolar, listar, obtener_perfil
from .planta import calcular_planta
from .modelo3d import a_stl, caja, partes_ala, partes_fuselaje
from .aero import ACABADOS, calcular_avion, lateral_avion, partes_avion, planta_avion
from .tramos import dividir
from . import calibracion as calib
from . import materiales as mats
from .fuselaje import _estaciones, _stl, forma, piezas as piezas_fuselaje, silueta_cache
from .proyecto import (CAMPOS_PUNTA, Ala, Componente, Proyecto, Varilla, cargar_maquina, cargar_proyecto,
                       guardar_maquina, guardar_proyecto, sincronizar_recta)

from .rutas import (DIR_CATALOGO, DIR_MIS_PERFILES, DIR_PROYECTOS, DOCUMENTOS, MAQUINA_JSON, MATERIALES_JSON, RECURSOS,
                    RECIENTES_JSON, preparar)
VELOCIDADES_SIM = ("x1", "x2", "x5", "x10", "x20", "x50")

TIPOS_VARILLA = {"redondo": "Redondo (agujero)", "marca": "Marca (ranura fina)",
                 "rectangular": "Rectangular (larguero)"}
SUPERFICIES = {"extrados": "Extradós (arriba)", "intrados": "Intradós (abajo)"}
CENTROS = {"mitad": "Mitad del espesor", "profundidad": "Profundidad desde superficie"}
ORIENTACIONES = {"cuerda": "Cuerda horizontal", "intrados": "Apoyado en la mesa (intradós)",
                 "tramo": "Tramo del intradós paralelo",
                 "min_alto": "Mínimo espesor de bloque", "manual": "Ángulo manual"}
REFERENCIAS = {"bs": "Borde de salida de la raíz", "base": "Punto más bajo (margen a la base)"}
PIEZAS = {"ala": "Ala", "estabilizador": "Estabilizador / cola en V", "deriva": "Deriva",
          "fuselaje": "Fuselaje", "avion": "Avión: montaje y cálculo"}
PESTANAS_MODO = {
    "ala": ("Ala", "Ala 2", "Varillas", "Alerón", "Corte", "Máquina"),
    "estabilizador": ("Ala", "Varillas", "Alerón", "Corte", "Máquina"),
    "deriva": ("Ala", "Varillas", "Alerón", "Corte", "Máquina"),
    "fuselaje": ("Fuselaje", "Corte", "Máquina"),
    "avion": ("Avión",),
}
DESPEGUES = {"mano": "Lanzado a mano", "rodando": "Rodando por el suelo"}
TIPOS_COLA = {"convencional": "Convencional (estabilizador + deriva)", "v": "Cola en V",
              "sin_cola": "Sin cola (ala volante)"}
METODOS_FUS = {"silueta": "Siluetas (vista lateral / en planta)", "tramos": "Tramos entre cuadernas",
               "stl": "Tramos desde un STL"}
FUENTES_FUS = {"medidas": "Medidas", "dxf": "Fichero DXF", "stl": "Fichero STL"}
VISTAS_FUS = {"lateral": "Lateral (de lado)", "planta": "En planta (desde arriba)"}
EJES_STL = {"X": "X", "Y": "Y", "Z": "Z"}
LADOS = {"XY": "Torre 1 (ejes 1-2)", "ZA": "Torre 2 (ejes 3-4)"}

COLORES = {1: ("#1f4fa0", "#b02020"), 2: ("#1a8a4a", "#d07a00")}


def num(txt):
    return float(str(txt).replace(",", "."))


def fmt(v):
    return f"{v:g}" if isinstance(v, float) else str(v)


class Formulario:
    """Enlaza campos de texto/combos/casillas con atributos de los objetos del modelo."""

    def __init__(self, al_cambiar):
        self.campos = []
        self.al_cambiar = al_cambiar
        self.cargando = False

    def fila(self, padre, fila, obj, attr, etiqueta, tipo="float", opciones=None, unidad="", ancho=12):
        var = tk.StringVar()
        if tipo == "bool":
            w = ttk.Checkbutton(padre, text=etiqueta, variable=var, onvalue="1", offvalue="0")
            w.grid(row=fila, column=0, columnspan=3, sticky="w", padx=4, pady=2)
        else:
            ttk.Label(padre, text=etiqueta).grid(row=fila, column=0, sticky="w", padx=4, pady=2)
            if opciones:
                w = ttk.Combobox(padre, textvariable=var, values=list(opciones.values()), state="readonly",
                                 width=max(ancho, 24))
            else:
                w = ttk.Entry(padre, textvariable=var, width=ancho)
            w.grid(row=fila, column=1, sticky="we", padx=4, pady=2)
            if unidad:
                ttk.Label(padre, text=unidad).grid(row=fila, column=2, sticky="w")
        campo = dict(var=var, obj=obj, attr=attr, tipo=tipo, opciones=opciones, widget=w)
        self.agregar(campo)
        return campo

    def agregar(self, campo):
        self.campos.append(campo)
        campo["var"].trace_add("write", lambda *_: self._cambio(campo))

    def _cambio(self, c):
        if self.cargando:
            return
        txt = c["var"].get()
        try:
            if c["opciones"]:
                val = next(k for k, v in c["opciones"].items() if v == txt)
            elif c["tipo"] == "float":
                val = num(txt)
            elif c["tipo"] == "int":
                val = int(round(num(txt)))
            elif c["tipo"] == "bool":
                val = txt == "1"
            else:
                val = txt
        except (ValueError, StopIteration):
            c["widget"].configure(style="Error.TEntry")
            return
        if isinstance(c["widget"], ttk.Entry) and not isinstance(c["widget"], ttk.Combobox):
            c["widget"].configure(style="TEntry")
        setattr(c["obj"](), c["attr"], val)
        self.al_cambiar()

    def refrescar(self, filtro=None):
        """Vuelve a mostrar los valores del modelo. `filtro`: conjunto de atributos o función(campo)."""
        self.cargando = True
        for c in self.campos:
            if filtro is not None and not (filtro(c) if callable(filtro) else c["attr"] in filtro):
                continue
            v = getattr(c["obj"](), c["attr"])
            if c["tipo"] == "bool":
                c["var"].set("1" if v else "0")
            else:
                c["var"].set(c["opciones"].get(v, v) if c["opciones"] else fmt(v))
        self.cargando = False


class DialogoVarilla(tk.Toplevel):
    USADOS = {"redondo": {"diametro", "centro", "prof_centro", "inclinacion"},
              "marca": {"prof_marca", "inclinacion"},
              "rectangular": {"ancho", "alto"}}

    def __init__(self, padre, varilla, recta=False):
        super().__init__(padre)
        self.recta = recta
        self.title("Varilla / larguero")
        self.transient(padre)
        self.resizable(False, False)
        self.v = copy.deepcopy(varilla)
        self.resultado = None
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        self.form = Formulario(self._actualizar)
        V = lambda: self.v
        filas = [
            ("nombre", "Nombre", "str", None, ""),
            ("tipo", "Tipo", None, TIPOS_VARILLA, ""),
            ("superficie", "Entra por", None, SUPERFICIES, ""),
            ("pos_raiz", "Posición en raíz (desde BA)", "float", None, "mm"),
            ("pos_punta", "Posición en punta (desde BA)", "float", None, "mm"),
            ("diametro", "Diámetro", "float", None, "mm"),
            ("centro", "Centro del agujero", None, CENTROS, ""),
            ("prof_centro", "Profundidad del centro", "float", None, "mm"),
            ("prof_marca", "Profundidad de la marca", "float", None, "mm"),
            ("ancho", "Ancho de la ranura", "float", None, "mm"),
            ("alto", "Profundidad de la ranura", "float", None, "mm"),
            ("inclinacion", "Inclinación de la entrada", "float", None, "°"),
        ]
        self.widgets = {}
        for i, (attr, et, tipo, ops, ud) in enumerate(filas):
            c = self.form.fila(f, i, V, attr, et, tipo or "str", ops, ud, ancho=20)
            self.widgets[attr] = c["widget"]
        ttk.Label(f, text="Las posiciones se miden desde el borde de ataque hasta el centro.\n"
                          "Inclinación: 0 = perpendicular; + inclina la entrada hacia el borde de salida.",
                  foreground="gray").grid(row=len(filas), column=0, columnspan=3, sticky="w", pady=(6, 0))
        b = ttk.Frame(f)
        b.grid(row=len(filas) + 1, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(b, text="Aceptar", command=self._ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancelar", command=self.destroy).pack(side="left")
        self.form.refrescar()
        self._actualizar()
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window()

    def _actualizar(self):
        usados = self.USADOS[self.v.tipo]
        for attr in ("diametro", "centro", "prof_centro", "prof_marca", "ancho", "alto", "inclinacion"):
            self.widgets[attr].configure(state=("readonly" if attr == "centro" else "normal")
                                         if attr in usados else "disabled")
        if self.recta:
            self.widgets["pos_punta"].configure(state="disabled")
            if self.v.pos_punta != self.v.pos_raiz:
                self.v.pos_punta = self.v.pos_raiz
                self.form.refrescar({"pos_punta"})
        if self.v.tipo == "redondo" and self.v.centro == "mitad":
            self.widgets["prof_centro"].configure(state="disabled")

    def _ok(self):
        self.resultado = self.v
        self.destroy()


class Vista:
    """Dibujo con escala 1:1, zoom con la rueda, arrastrar para mover y doble clic para encuadrar."""

    def __init__(self, padre, coords):
        self.coords = coords
        self.fig = Figure(figsize=(8, 6), dpi=100)
        self.fig.subplots_adjust(left=0.06, right=0.99, top=0.99, bottom=0.05)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=padre)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.vista = None
        self.caja = (0, 0, 100, 100)
        self._arrastre = None
        self.canvas.mpl_connect("scroll_event", self._rueda)
        self.canvas.mpl_connect("button_press_event", self._pulsar)
        self.canvas.mpl_connect("motion_notify_event", self._mover)
        self.canvas.mpl_connect("button_release_event", self._soltar)
        self.canvas.mpl_connect("resize_event", lambda e: self.aplicar())

    def nuevo(self):
        ax = self.ax
        ax.clear()
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.3)
        return ax

    def mostrar(self, puntos):
        todos = np.vstack(puntos)
        self.caja = (*todos.min(axis=0), *todos.max(axis=0))
        self.aplicar()

    def aplicar(self):
        if self.vista is None:
            x0, y0, x1, y1 = self.caja
            m = 0.06 * max(x1 - x0, y1 - y0, 1)
            x0, x1, y0, y1 = x0 - m, x1 + m, y0 - m, y1 + m
        else:
            (x0, x1), (y0, y1) = self.vista
        bb = self.ax.get_window_extent()
        ratio = bb.height / bb.width if bb.width > 0 else 0.6
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = x1 - x0, y1 - y0
        if self.vista is None and h / w > ratio:
            w = h / ratio
        else:
            h = w * ratio
        self.ax.set_xlim(cx - w / 2, cx + w / 2)
        self.ax.set_ylim(cy - h / 2, cy + h / 2)
        self.canvas.draw_idle()

    def encuadrar(self):
        self.vista = None
        self.aplicar()

    def _guardar(self):
        self.vista = (self.ax.get_xlim(), self.ax.get_ylim())
        self.canvas.draw_idle()

    def _rueda(self, e):
        if e.xdata is None:
            return
        f = 1 / 1.25 if e.button == "up" else 1.25
        (x0, x1), (y0, y1) = self.ax.get_xlim(), self.ax.get_ylim()
        self.ax.set_xlim(e.xdata + (x0 - e.xdata) * f, e.xdata + (x1 - e.xdata) * f)
        self.ax.set_ylim(e.ydata + (y0 - e.ydata) * f, e.ydata + (y1 - e.ydata) * f)
        self._guardar()

    def _pulsar(self, e):
        if e.inaxes is not self.ax or e.button not in (1, 2, 3):
            return
        if e.dblclick:
            self.encuadrar()
            return
        self._arrastre = (e.x, e.y, self.ax.get_xlim(), self.ax.get_ylim())

    def _mover(self, e):
        if e.inaxes is self.ax and e.xdata is not None:
            self.coords.set(f"x {e.xdata:7.1f}   y {e.ydata:7.1f} mm")
        if self._arrastre is None:
            return
        px, py, (x0, x1), (y0, y1) = self._arrastre
        bb = self.ax.get_window_extent()
        dx = (e.x - px) * (x1 - x0) / bb.width
        dy = (e.y - py) * (y1 - y0) / bb.height
        self.ax.set_xlim(x0 - dx, x1 - dx)
        self.ax.set_ylim(y0 - dy, y1 - dy)
        self._guardar()

    def _soltar(self, e):
        self._arrastre = None


class DialogoCalibracion(tk.Toplevel):
    """Prueba de cuadrados a varias velocidades: G-code, medidas, kerf y velocidad recomendada."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        c = app.p.corte
        self.title("Calibrar velocidad de corte y kerf")
        self.transient(app)
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, wraplength=560, justify="left", text=(
            "1. Exporta la prueba y córtala con el calor que uses normalmente. Salen cuadrados sueltos, "
            "cada uno a una velocidad distinta.\n"
            "2. Mide el ancho de cada cuadrado (de lado a lado, en las dos caras del bloque y haz la media) "
            "y marca los que tengan las esquinas vivas: si están redondeadas, el hilo se ha quedado atrás.\n"
            "3. Calcula: el kerf es lo que falta hasta el lado teórico. Aplica la velocidad elegida al proyecto.\n"
            "Repite la prueba con otro ajuste de la fuente para comparar.")).grid(row=0, column=0, columnspan=4,
                                                                                   sticky="w")
        self.literal = tk.BooleanVar(value=c.calib_f_literal)
        ttk.Checkbutton(f, text="Las velocidades son la F del G-code (si pones 30, el código lleva F30)",
                        variable=self.literal, command=self._cambio_modo).grid(row=10, column=0, columnspan=4,
                                                                               sticky="w", pady=(8, 0))
        self.v_vel = tk.StringVar(value=c.calib_velocidades)
        self.v_lado = tk.StringVar(value=f"{c.calib_lado:g}")
        self.v_sep = tk.StringVar(value="15")
        self.v_base = tk.StringVar(value="10")
        self.et_vel = tk.StringVar()
        filas = ((self.et_vel, self.v_vel, 28), ("Lado de los cuadrados (mm)", self.v_lado, 8),
                 ("Separación (mm)", self.v_sep, 8), ("Altura de la base (mm)", self.v_base, 8))
        for i, (et, var, an) in enumerate(filas, 1):
            if isinstance(et, tk.StringVar):
                ttk.Label(f, textvariable=et).grid(row=i, column=0, sticky="w", pady=2)
            else:
                ttk.Label(f, text=et).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(f, textvariable=var, width=an).grid(row=i, column=1, columnspan=2, sticky="w", pady=2)
            var.trace_add("write", lambda *_: self._datos())
        self.info = tk.StringVar()
        self.etiqueta_info = ttk.Label(f, textvariable=self.info, foreground="#1a7a3a", wraplength=560, justify="left")
        self.etiqueta_info.grid(row=5, column=0, columnspan=4, sticky="w")
        ttk.Button(f, text="Exportar G-code de la prueba...", command=self.exportar).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(f, text="Preparar tabla de medidas", command=self.tabla).grid(row=6, column=2, sticky="w")
        self.marco_tabla = ttk.Frame(f)
        self.marco_tabla.grid(row=7, column=0, columnspan=4, sticky="we", pady=4)
        self.resultado = tk.StringVar()
        ttk.Label(f, textvariable=self.resultado, wraplength=560, justify="left").grid(
            row=8, column=0, columnspan=4, sticky="w")
        bb = ttk.Frame(f)
        bb.grid(row=9, column=0, columnspan=4, sticky="we", pady=(6, 0))
        ttk.Label(bb, text="Velocidad elegida").pack(side="left")
        self.v_elegida = tk.StringVar()
        self.combo = ttk.Combobox(bb, textvariable=self.v_elegida, width=8, state="readonly")
        self.combo.pack(side="left", padx=4)
        ttk.Button(bb, text="Aplicar al proyecto", command=self.aplicar).pack(side="right")
        self.filas = {}
        self.kerf = calib.leer_tabla(c.calib_tabla)
        self._cambio_modo(inicial=True)
        self._datos()
        self.tabla()
        if self.kerf:
            for v, k in self.kerf.items():
                if v in self.filas:
                    self.filas[v][0].set(f"{float(self.v_lado.get().replace(',', '.')) - k:.2f}")
            self.calcular()

    def _unidad(self, v):
        return f"F{v:g}" if self.literal.get() else f"{v:g} mm/min"

    def _cambio_modo(self, inicial=False):
        self.et_vel.set("Velocidades a probar (F del G-code)" if self.literal.get()
                        else "Velocidades reales del hilo (mm/min)")
        if not inicial:
            self.app.p.corte.calib_f_literal = self.literal.get()
            self._datos()
            self.tabla()
            self.calcular()

    def _leer(self):
        num = lambda s: float(s.replace(",", "."))
        return (calib.leer_velocidades(self.v_vel.get()), num(self.v_lado.get()), num(self.v_sep.get()),
                num(self.v_base.get()))

    def _datos(self):
        try:
            v, lado, sep, base = self._leer()
            _, info = calib.gcode_calibracion(self.app.m, self.app.p.corte, v, lado, sep, base, self.literal.get())
            texto = (f"Bloque mínimo {info['largo']:.0f} × {info['alto']:.0f} mm (más el ancho que quieras), "
                     f"duración ≈ {info['tiempo_min']:.0f} min")
            if info["excede"]:
                texto += (f"\nOjo: {', '.join(self._unidad(x) for x in info['excede'])} superan la velocidad máxima "
                          f"de tu máquina ({self.app.m.vel_max:g} mm/min, pestaña Máquina). Bórralas si tus torres "
                          f"no pueden ir tan rápido.")
            self.info.set(texto)
            self.etiqueta_info.configure(foreground="#b06000" if info["excede"] else "#1a7a3a")
        except ValueError as e:
            self.info.set(str(e))

    def exportar(self):
        try:
            v, lado, sep, base = self._leer()
            g, _ = calib.gcode_calibracion(self.app.m, self.app.p.corte, v, lado, sep, base, self.literal.get())
        except ValueError as e:
            messagebox.showerror("AeroFoam", str(e), parent=self)
            return
        ruta = filedialog.asksaveasfilename(parent=self, title="Exportar prueba de calibración",
                                            initialfile="calibracion.gcode", defaultextension=".gcode",
                                            filetypes=[("G-code", "*.gcode *.nc *.gc *.tap"), ("Todos", "*.*")])
        if ruta:
            Path(ruta).write_text(g, encoding="ascii", newline="\n")
            self.app.p.corte.calib_velocidades = self.v_vel.get()
            self.app.p.corte.calib_lado = lado
            messagebox.showinfo("AeroFoam", f"Prueba guardada en:\n{ruta}\n\nPon el cero en la esquina inferior "
                                            f"del bloque, del lado por donde empieza.", parent=self)

    def tabla(self):
        for w in self.marco_tabla.winfo_children():
            w.destroy()
        try:
            vs = self._leer()[0]
        except ValueError:
            return
        anteriores = {v: (fila[0].get(), fila[1].get()) for v, fila in self.filas.items()}
        self.filas = {}
        for j, et in enumerate(("Velocidad", "Ancho medido (mm)", "Esquinas vivas", "Kerf (mm)")):
            ttk.Label(self.marco_tabla, text=et, font=("Segoe UI", 9, "bold")).grid(row=0, column=j, padx=6)
        for i, v in enumerate(vs, 1):
            medida, viva = tk.StringVar(), tk.BooleanVar()
            if v in anteriores:
                medida.set(anteriores[v][0])
                viva.set(anteriores[v][1])
            kerf = tk.StringVar()
            ttk.Label(self.marco_tabla, text=self._unidad(v)).grid(row=i, column=0, padx=6)
            ttk.Entry(self.marco_tabla, textvariable=medida, width=8).grid(row=i, column=1)
            ttk.Checkbutton(self.marco_tabla, variable=viva).grid(row=i, column=2)
            ttk.Label(self.marco_tabla, textvariable=kerf).grid(row=i, column=3)
            medida.trace_add("write", lambda *_: self.calcular())
            viva.trace_add("write", lambda *_: self.calcular())
            self.filas[v] = (medida, viva, kerf)

    def calcular(self):
        try:
            lado = float(self.v_lado.get().replace(",", "."))
        except ValueError:
            return
        medidas = {}
        for v, (medida, _, kerf) in self.filas.items():
            try:
                medidas[v] = float(medida.get().replace(",", "."))
            except ValueError:
                kerf.set("")
        self.kerf = calib.kerfs(lado, medidas)
        for v, (_, _, kerf) in self.filas.items():
            kerf.set(f"{self.kerf[v]:.2f}" if v in self.kerf else "")
        vivas = {v: fila[1].get() for v, fila in self.filas.items()}
        rec = calib.recomendar(self.kerf, vivas)
        self.combo.configure(values=[f"{v:g}" for v in sorted(self.kerf)])
        if rec is None:
            self.resultado.set("")
            return
        self.v_elegida.set(f"{rec:g}")
        sin_marcar = not any(vivas.get(v) for v in self.kerf)
        self.resultado.set(
            f"Recomendada: {self._unidad(rec)} (kerf {self.kerf[rec]:.2f} mm) — la más rápida "
            + ("con poco kerf. Marca qué cuadrados tienen las esquinas vivas para afinar."
               if sin_marcar else "con esquinas vivas y poco kerf.")
            + "\nSi ninguna te convence, baja un poco el calor y repite la prueba.")

    def aplicar(self):
        if not self.kerf or not self.v_elegida.get():
            messagebox.showinfo("AeroFoam", "Mete primero las medidas.", parent=self)
            return
        app, c = self.app, self.app.p.corte
        v = float(self.v_elegida.get())
        c.calib_tabla = calib.texto_tabla(self.kerf)
        c.calib_velocidades = self.v_vel.get()
        c.calib_lado = float(self.v_lado.get().replace(",", "."))
        literal = self.literal.get()
        c.calib_f_literal = literal
        # misma forma de dar la velocidad que en la prueba: F tal cual o velocidad real
        c.modo_velocidad = "f_bruto" if literal else "cara_rapida"
        c.vel_corte = c.vel_entrada = v
        # kerf de cada cara según la velocidad real a la que va cada una en esta pieza
        real = calib.tabla_real(self.kerf, literal)
        k_r = k_t = self.kerf[v] if v in self.kerf else calib.kerf_a_velocidad(real, calib.velocidad_real(v, literal))
        detalle = ""
        try:
            if app.p.pieza in ("ala", "estabilizador", "deriva"):
                p = app._p_activo()
                res = calcular(p, app.m)
                _, info = generar(res, p, app.m)
                vr, vt = calib.velocidades_caras(res, info)
                k_r, k_t = calib.kerf_a_velocidad(real, vr), calib.kerf_a_velocidad(real, vt)
                detalle = (f"\nEl hilo irá en la raíz a {vr:.0f} mm/min reales → kerf {k_r:.2f} mm;  en la punta a "
                           f"{vt:.0f} mm/min → kerf {k_t:.2f} mm")
        except (ErrorGeometria, ValueError):
            pass
        c.kerf_raiz, c.kerf_punta = round(k_r, 2), round(k_t, 2)
        app.form.refrescar()
        app.recalcular()
        modo = "F sin corregir" if literal else "F corregida"
        if calib.velocidad_real(v, literal) > app.m.vel_max:
            detalle += (f"\n\nOjo: tu máquina está limitada a {app.m.vel_max:g} mm/min (pestaña Máquina), así que "
                        f"las torres no pasarán de ahí y el hilo irá más despacio que {v:g}. Si tus torres pueden ir "
                        f"más rápido, sube ese máximo y vuelve a aplicar.")
        messagebox.showinfo("AeroFoam", f"Aplicado: corte y entrada a F{c.vel_corte:g} ({modo}).{detalle}\n\n"
                                        f"Si cambias mucho las cuerdas, vuelve a pulsar 'Aplicar' para "
                                        f"recalcular el kerf de cada cara.", parent=self)


class DialogoMateriales(tk.Toplevel):
    """Opciones > Materiales: lista de materiales con su densidad, acabado, velocidad y kerf."""
    COLS = (("densidad", "Densidad (kg/m³)", 100), ("acabado", "Acabado", 150), ("velocidad", "Velocidad", 80),
            ("kerf", "Kerf (mm)", 70))

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Materiales")
        self.transient(app)
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, wraplength=640, justify="left", foreground="gray", text=(
            "Al elegir un material en la pestaña Corte se ponen su velocidad y su kerf, y en la pestaña Avión su "
            "densidad y su acabado. La velocidad es la F que pones (según el modo de 'Cálculo de la F'). "
            "La lista se guarda para todos los proyectos.")).pack(anchor="w")
        self.arbol = ttk.Treeview(f, columns=[c[0] for c in self.COLS], show="tree headings", height=8,
                                  selectmode="browse")
        self.arbol.heading("#0", text="Material")
        self.arbol.column("#0", width=260)
        for c, et, w in self.COLS:
            self.arbol.heading(c, text=et)
            self.arbol.column(c, width=w, anchor="center")
        self.arbol.pack(fill="both", expand=True, pady=6)
        self.arbol.bind("<Double-1>", lambda e: self.editar())
        self.notas = tk.StringVar()
        ttk.Label(f, textvariable=self.notas, foreground="gray", wraplength=640, justify="left").pack(anchor="w")
        self.arbol.bind("<<TreeviewSelect>>", lambda e: self._ver_notas())
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(6, 0))
        for et, cmd in (("Añadir", self.anadir), ("Editar", self.editar), ("Duplicar", self.duplicar),
                        ("Eliminar", self.eliminar)):
            ttk.Button(b, text=et, command=cmd).pack(side="left", padx=2)
        ttk.Button(b, text="Restaurar los de fábrica", command=self.restaurar).pack(side="right", padx=2)
        b2 = ttk.Frame(f)
        b2.pack(fill="x", pady=(4, 0))
        ttk.Button(b2, text="Guardar en el material elegido la velocidad y el kerf del proyecto",
                   command=self.desde_proyecto).pack(side="left", padx=2)
        ttk.Button(b2, text="Cerrar", command=self.destroy).pack(side="right", padx=2)
        self.refrescar()

    def refrescar(self, sel=None):
        self.arbol.delete(*self.arbol.get_children())
        for i, m in enumerate(self.app.materiales):
            self.arbol.insert("", "end", iid=str(i), text=m.nombre,
                              values=(f"{m.densidad:g}", ACABADOS.get(m.acabado, m.acabado), f"{m.velocidad:g}",
                                      f"{m.kerf:g}"))
        if sel is not None and 0 <= sel < len(self.app.materiales):
            self.arbol.selection_set(str(sel))
        self._ver_notas()

    def _sel(self):
        s = self.arbol.selection()
        return int(s[0]) if s else None

    def _ver_notas(self):
        i = self._sel()
        self.notas.set(self.app.materiales[i].notas if i is not None else "")

    def _guardar(self, sel=None):
        try:
            mats.guardar(self.app.materiales, MATERIALES_JSON)
        except OSError as e:
            messagebox.showerror("AeroFoam", f"No se pudo guardar la lista de materiales:\n{e}", parent=self)
        self.app._refrescar_materiales()
        self.refrescar(sel)

    def _formulario(self, m):
        w = tk.Toplevel(self)
        w.title("Material")
        w.transient(self)
        w.resizable(False, False)
        m = copy.deepcopy(m)
        res = {}
        fr = ttk.Frame(w, padding=10)
        fr.pack()
        form = Formulario(lambda: None)
        for i, (attr, et, tipo, ops, ud) in enumerate((
                ("nombre", "Nombre", "str", None, ""), ("densidad", "Densidad", "float", None, "kg/m³"),
                ("acabado", "Acabado", "str", ACABADOS, ""), ("velocidad", "Velocidad de corte", "float", None, "mm/min"),
                ("kerf", "Kerf", "float", None, "mm"), ("notas", "Notas", "str", None, ""))):
            form.fila(fr, i, lambda: m, attr, et, tipo, ops, ud, ancho=34)
        form.refrescar()

        def ok():
            if not m.nombre.strip():
                messagebox.showerror("AeroFoam", "Ponle un nombre.", parent=w)
                return
            res["m"] = m
            w.destroy()
        bb = ttk.Frame(fr)
        bb.grid(row=7, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(bb, text="Aceptar", command=ok).pack(side="left", padx=4)
        ttk.Button(bb, text="Cancelar", command=w.destroy).pack(side="left")
        w.bind("<Return>", lambda e: ok())
        w.grab_set()
        w.wait_window()
        return res.get("m")

    def anadir(self):
        m = self._formulario(mats.Material(nombre="Material nuevo"))
        if m:
            self.app.materiales.append(m)
            self._guardar(len(self.app.materiales) - 1)

    def editar(self):
        i = self._sel()
        if i is None:
            return
        anterior = self.app.materiales[i].nombre
        m = self._formulario(self.app.materiales[i])
        if m:
            self.app.materiales[i] = m
            if self.app.p.corte.material == anterior:   # el proyecto sigue con el material renombrado
                self.app.p.corte.material = m.nombre
            self._guardar(i)

    def duplicar(self):
        i = self._sel()
        if i is None:
            return
        m = copy.deepcopy(self.app.materiales[i])
        m.nombre += " (copia)"
        self.app.materiales.insert(i + 1, m)
        self._guardar(i + 1)

    def eliminar(self):
        i = self._sel()
        if i is None:
            return
        if len(self.app.materiales) == 1:
            messagebox.showinfo("AeroFoam", "Tiene que quedar al menos un material.", parent=self)
            return
        if messagebox.askyesno("AeroFoam", f"¿Eliminar '{self.app.materiales[i].nombre}'?", parent=self):
            del self.app.materiales[i]
            self._guardar()

    def restaurar(self):
        if messagebox.askyesno("AeroFoam", "¿Volver a los materiales de fábrica? Se pierden los cambios de la lista.",
                               parent=self):
            self.app.materiales[:] = mats.de_fabrica()
            self._guardar()

    def desde_proyecto(self):
        i = self._sel()
        if i is None:
            messagebox.showinfo("AeroFoam", "Elige primero un material de la lista.", parent=self)
            return
        c = self.app.p.corte
        m = self.app.materiales[i]
        m.velocidad, m.kerf = c.vel_corte, c.kerf_raiz
        self._guardar(i)


class Vista3D:
    """Modelo 3D: arrastrar para girar, rueda para acercar, Encuadrar para volver al inicio."""
    INICIO = (22, -58)

    def __init__(self, padre):
        self.fig = Figure(figsize=(8, 6), dpi=100)
        self.fig.subplots_adjust(left=0, right=1, top=0.95, bottom=0)
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.canvas = FigureCanvasTkAgg(self.fig, master=padre)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.vista = None
        self.partes = []
        self.canvas.mpl_connect("scroll_event", self._rueda)

    def dibujar(self, partes, titulo=""):
        ax = self.ax
        elev, azim = (ax.elev, ax.azim) if self.partes else self.INICIO
        ax.clear()
        self.partes = partes
        if not partes:
            ax.set_axis_off()
            ax.text2D(0.5, 0.5, "Sin pieza (revisa los errores)", transform=ax.transAxes, ha="center")
            self.canvas.draw_idle()
            return
        ax.set_axis_on()
        for q in partes:
            A, B = np.vstack([q.a, q.a[:1]]), np.vstack([q.b, q.b[:1]])
            caras = np.stack([A[:-1], A[1:], B[1:], B[:-1]], axis=1)
            ax.add_collection3d(Poly3DCollection(list(caras), facecolors=self._sombra(caras, q.color),
                                                 edgecolors="none", alpha=q.alfa))
            if q.tapas:
                tapas = [q.a, q.b]
                ax.add_collection3d(Poly3DCollection(tapas, facecolors=self._sombra(tapas, q.color),
                                                     edgecolors="#555", linewidths=0.3, alpha=q.alfa))
        self._limites()
        ax.view_init(elev, azim)
        for eje in (ax.xaxis, ax.yaxis, ax.zaxis):
            eje.pane.fill = False
            eje.pane.set_edgecolor("#dddddd")
            eje._axinfo["grid"]["color"] = (0.85, 0.85, 0.85, 1)
            eje.set_tick_params(labelsize=7)
        ax.set_title(titulo, fontsize=9)
        self.canvas.draw_idle()

    @staticmethod
    def _sombra(caras, color, luz=(0.4, -0.6, 0.7)):
        """Color de cada cara según su orientación respecto a una luz (sombreado sencillo)."""
        from matplotlib.colors import to_rgb
        base = np.array(to_rgb(color))
        luz = np.array(luz) / np.linalg.norm(luz)
        if isinstance(caras, np.ndarray):  # cuadriláteros (M, 4, 3): todos de una vez
            n = np.cross(caras[:, 2] - caras[:, 0], caras[:, 3] - caras[:, 1])
        else:                              # tapas: polígonos sueltos
            n = np.array([np.cross(c[1] - c[0], c[len(c) // 2] - c[0]) for c in caras])
        n = n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
        return np.clip(base[None, :] * (0.5 + 0.5 * np.abs(n @ luz))[:, None], 0, 1)

    def _limites(self, factor=1.0):
        lo, hi = caja(self.partes)
        centro, tam = (lo + hi) / 2, np.maximum(hi - lo, 1.0)
        self.ax.set_box_aspect(tuple(tam))
        for fijar, c, t in zip((self.ax.set_xlim, self.ax.set_ylim, self.ax.set_zlim), centro, tam):
            fijar(c - t / 2 * factor, c + t / 2 * factor)

    def encuadrar(self):
        if self.partes:
            self._limites()
            self.ax.view_init(*self.INICIO)
            self.canvas.draw_idle()

    def _rueda(self, e):
        f = 1 / 1.2 if e.button == "up" else 1.2
        for obtener, fijar in ((self.ax.get_xlim, self.ax.set_xlim), (self.ax.get_ylim, self.ax.set_ylim),
                               (self.ax.get_zlim, self.ax.set_zlim)):
            a, b = obtener()
            c, t = (a + b) / 2, (b - a) / 2 * f
            fijar(c - t, c + t)
        self.canvas.draw_idle()


class App(tk.Tk):
    ATTRS_PUNTA = set(CAMPOS_PUNTA) | {"flecha", "desplaz_vertical", "kerf_punta"}

    def __init__(self):
        super().__init__()
        self.geometry("1350x820")
        self.minsize(1000, 650)
        estilo = ttk.Style(self)
        estilo.configure("Error.TEntry", foreground="red")
        for icono in (Path(__file__).with_name("aerofoam.ico"), RECURSOS / "aerofoam.ico"):
            if icono.exists():
                try:
                    self.iconbitmap(default=str(icono))
                except tk.TclError:
                    pass
                break
        self.p = Proyecto()
        self.m = cargar_maquina(MAQUINA_JSON)
        self.ruta = None
        self.res = None
        self.bloque = None
        self.info = None
        self.planta = None
        self.pc = self.p          # proyecto que se corta (el panel o el tramo elegido)
        self.tramos = []
        self._tramo_idx = 0
        self.piezas = []
        self._pieza_idx = 0
        self.descripcion = None
        self.marcos_pestana = {}
        self._tarea = None
        self._historial, self._rehacer = [], []
        self._estado_ok = copy.deepcopy(self.p)
        self._sim = None          # tarea de la animación
        self.sim_t = 0.0          # minutos simulados
        self.sim_art = None
        self.form = Formulario(self.programar)
        self.catalogo = listar()
        self.materiales = mats.cargar(MATERIALES_JSON)
        self.categoria = tk.StringVar(value="Todas")
        self.combos_perfil = []
        self.info_perfil = []
        self.botones_punta = {}
        self._menu()
        self._interfaz()
        self.form.refrescar()
        self._refrescar_textos()
        self.refrescar_varillas()
        self._titulo()
        self.protocol("WM_DELETE_WINDOW", self.salir)
        self.recalcular()

    @property
    def ala(self):
        """Ala sobre la que trabajan las pestañas: el ala, el estabilizador o la deriva."""
        return {"estabilizador": self.p.estabilizador, "deriva": self.p.deriva}.get(self.p.pieza, self.p.ala)

    def _p_activo(self):
        """Proyecto con el ala activa en el sitio del ala (para cortar estabilizador o deriva)."""
        if self.p.pieza in ("estabilizador", "deriva"):
            return replace(self.p, ala=self.ala)
        return self.p

    # ---------- construcción ----------
    def _menu(self):
        mb = tk.Menu(self)
        ar = tk.Menu(mb, tearoff=False)
        ar.add_command(label="Nuevo proyecto", command=self.nuevo)
        ar.add_command(label="Abrir proyecto...", command=self.abrir, accelerator="Ctrl+O")
        self.menu_recientes = tk.Menu(ar, tearoff=False)
        ar.add_cascade(label="Proyectos recientes", menu=self.menu_recientes)
        ar.add_command(label="Guardar proyecto", command=self.guardar, accelerator="Ctrl+S")
        ar.add_command(label="Guardar proyecto como...", command=self.guardar_como)
        ar.add_separator()
        ar.add_command(label="Exportar G-code...", command=self.exportar, accelerator="Ctrl+E")
        ar.add_command(label="Exportar modelo 3D (STL)...", command=self.exportar_stl)
        ar.add_separator()
        ar.add_command(label="Salir", command=self.salir)
        mb.add_cascade(label="Archivo", menu=ar)
        ed = tk.Menu(mb, tearoff=False)
        ed.add_command(label="Deshacer", command=self.deshacer, accelerator="Ctrl+Z")
        ed.add_command(label="Rehacer", command=self.rehacer, accelerator="Ctrl+Y")
        mb.add_cascade(label="Editar", menu=ed)
        he = tk.Menu(mb, tearoff=False)
        he.add_command(label="Calibrar velocidad y kerf...", command=lambda: DialogoCalibracion(self))
        mb.add_cascade(label="Herramientas", menu=he)
        op = tk.Menu(mb, tearoff=False)
        op.add_command(label="Materiales...", command=lambda: DialogoMateriales(self))
        mb.add_cascade(label="Opciones", menu=op)
        self.config(menu=mb)
        self._menu_recientes()
        self.bind_all("<Control-z>", lambda e: self.deshacer())
        self.bind_all("<Control-y>", lambda e: self.rehacer())
        self.bind_all("<Control-Z>", lambda e: self.rehacer())
        self.bind_all("<Control-o>", lambda e: self.abrir())
        self.bind_all("<Control-s>", lambda e: self.guardar())
        self.bind_all("<Control-e>", lambda e: self.exportar())

    def _interfaz(self):
        pan = ttk.PanedWindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True)
        izq = ttk.Frame(pan, padding=4)
        der = ttk.Frame(pan, padding=4)
        pan.add(izq, weight=0)
        pan.add(der, weight=1)

        arriba = ttk.Frame(izq)
        arriba.pack(fill="x", pady=(0, 4))
        self.form.fila(arriba, 0, lambda: self.p, "pieza", "Pieza", opciones=PIEZAS)
        nb = ttk.Notebook(izq)
        nb.pack(fill="both", expand=True)
        self.pestanas = nb
        self._pestana_ala(nb, "Ala", lambda: self.ala)
        self._pestana_ala(nb, "Ala 2", lambda: self.p.ala2, lambda: self.p.corte2)
        self._pestana_varillas(nb)
        self._pestana_aleron(nb)
        self._pestana_fuselaje(nb)
        self._pestana_avion(nb)
        self._pestana_corte(nb)
        self._pestana_maquina(nb)
        self._modo = None
        for titulo in ("Fuselaje", "Avión"):
            nb.hide(self.marcos_pestana[titulo])

        barra = ttk.Frame(der)
        barra.pack(fill="x")
        ttk.Button(barra, text="Ver G-code", command=self.ver_gcode).pack(side="left", padx=2)
        ttk.Button(barra, text="Exportar G-code...", command=self.exportar).pack(side="left", padx=2)
        ttk.Label(barra, text="   Vista:").pack(side="left")
        self.modo_vista = tk.StringVar(value="corte")
        for valor, texto in (("corte", "Corte"), ("planta", "Planta"), ("3d", "3D")):
            ttk.Radiobutton(barra, text=texto, value=valor, variable=self.modo_vista,
                            command=self._mostrar_vista).pack(side="left", padx=2)
        self.ver_torres = tk.BooleanVar(value=True)
        ttk.Checkbutton(barra, text="Mostrar torres", variable=self.ver_torres,
                        command=self.dibujar).pack(side="left", padx=10)
        ttk.Button(barra, text="Encuadrar", command=lambda: self.vista_activa().encuadrar()).pack(side="left")
        self.coords = tk.StringVar()
        ttk.Label(barra, textvariable=self.coords, font=("Consolas", 9)).pack(side="right", padx=4)

        # simulación del corte
        barra2 = ttk.Frame(der)
        barra2.pack(fill="x", pady=(2, 0))
        ttk.Label(barra2, text="Simulación:").pack(side="left", padx=(2, 4))
        self.boton_play = ttk.Button(barra2, text="▶ Reproducir", width=13, command=self.sim_play)
        self.boton_play.pack(side="left")
        ttk.Button(barra2, text="⏹", width=3, command=self.sim_parar).pack(side="left", padx=2)
        self.sim_vel = tk.StringVar(value="x5")
        ttk.Combobox(barra2, textvariable=self.sim_vel, values=VELOCIDADES_SIM, width=4,
                     state="readonly").pack(side="left", padx=4)
        self.sim_barra = tk.DoubleVar(value=0.0)
        ttk.Scale(barra2, from_=0.0, to=1.0, variable=self.sim_barra, length=220,
                  command=lambda v: self._sim_mover_barra(float(v))).pack(side="left", padx=4)
        self.sim_texto = tk.StringVar()
        ttk.Label(barra2, textvariable=self.sim_texto, font=("Consolas", 9)).pack(side="left", padx=4)
        ttk.Label(barra2, text="Rueda: zoom · Arrastrar: mover · Doble clic: encuadrar",
                  foreground="gray").pack(side="right", padx=4)

        self.estado = tk.Text(der, height=5, wrap="word", relief="flat", background=self.cget("background"))
        self.estado.pack(side="bottom", fill="x")
        self.estado.tag_configure("error", foreground="#c00000")
        self.estado.tag_configure("aviso", foreground="#b06000")
        self.estado.tag_configure("bien", foreground="#1a7a3a")

        # vistas: corte del ala 1, bloque con las dos alas (solo en la pestaña Ala 2) y planta
        self.panel_resultados = ttk.Frame(der, padding=(6, 0, 0, 0))
        ttk.Label(self.panel_resultados, text="Resultados del cálculo",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        caja = ttk.Frame(self.panel_resultados)
        caja.pack(fill="both", expand=True)
        self.texto_avion = tk.Text(caja, width=58, wrap="word", font=("Segoe UI", 9), relief="flat",
                                   background=self.cget("background"), padx=4)
        barra_txt = ttk.Scrollbar(caja, orient="vertical", command=self.texto_avion.yview)
        self.texto_avion.configure(yscrollcommand=barra_txt.set)
        barra_txt.pack(side="right", fill="y")
        self.texto_avion.pack(side="left", fill="both", expand=True)
        self.texto_avion.tag_configure("titulo", font=("Segoe UI", 9, "bold"), spacing1=4)
        self.texto_avion.tag_configure("aviso", foreground="#b06000")
        ttk.Label(self.panel_resultados, foreground="gray", wraplength=400, justify="left",
                  text="Estimaciones con métodos sencillos (perfil delgado, placa plana). El CG suele acertar "
                       "con pocos mm de margen, pero el primer vuelo manda: empieza con el CG algo adelantado."
                  ).pack(anchor="w", pady=4)
        self.zona_vistas = ttk.Frame(der)
        self.zona_vistas.pack(fill="both", expand=True)
        self.marcos = [ttk.Frame(self.zona_vistas) for _ in range(4)]
        self.v1 = Vista(self.marcos[0], self.coords)
        self.v2 = Vista(self.marcos[1], self.coords)
        self.v3 = Vista(self.marcos[2], self.coords)
        self.v4 = Vista3D(self.marcos[3])
        self.vistas = (self.v1, self.v2, self.v3, self.v4)
        self.marcos[0].pack(fill="both", expand=True)
        nb.bind("<<NotebookTabChanged>>", lambda e: self._cambio_pestana())

    def en_ala2(self):
        return self.pestanas.tab(self.pestanas.select(), "text") == "Ala 2"

    def _n_vista(self):
        if self.en_ala2():
            return 1
        return {"corte": 0, "planta": 2, "3d": 3}[self.modo_vista.get()]

    def vista_activa(self):
        return self.vistas[self._n_vista()]

    def _mostrar_vista(self):
        n = self._n_vista()
        if self.marcos[n].winfo_ismapped():
            return False
        for i, fr in enumerate(self.marcos):
            if i != n:
                fr.pack_forget()
        self.marcos[n].pack(fill="both", expand=True)
        if n == 3:
            self._dibujar_3d()
        return True

    def _cambio_pestana(self):
        if not self._mostrar_vista():
            return
        if self.en_ala2() and not self.p.doble:  # la primera vez parte de un ala igual
            self.copiar_ala1()
        else:
            self.recalcular()

    def _marco(self, nb, titulo):
        """Pestaña con barra de desplazamiento (aparece solo si el contenido no cabe)."""
        pagina = ttk.Frame(nb)
        nb.add(pagina, text=titulo)
        self.marcos_pestana[titulo] = pagina
        fondo = ttk.Style(self).lookup("TFrame", "background") or self.cget("background")
        lienzo = tk.Canvas(pagina, highlightthickness=0, borderwidth=0, background=fondo)
        barra = ttk.Scrollbar(pagina, orient="vertical", command=lienzo.yview)
        lienzo.configure(yscrollcommand=barra.set)
        lienzo.pack(side="left", fill="both", expand=True)
        f = ttk.Frame(lienzo, padding=8)
        ventana = lienzo.create_window((0, 0), window=f, anchor="nw")

        def ajustar(e=None):
            lienzo.configure(scrollregion=(0, 0, f.winfo_reqwidth(), f.winfo_reqheight()))
            if int(lienzo.cget("width")) < f.winfo_reqwidth():
                lienzo.configure(width=f.winfo_reqwidth())
            necesita = f.winfo_reqheight() > lienzo.winfo_height() > 1
            if necesita and not barra.winfo_ismapped():
                barra.pack(side="right", fill="y", before=lienzo)
            elif not necesita and barra.winfo_ismapped():
                barra.pack_forget()
                lienzo.yview_moveto(0)

        def rueda(e):
            if f.winfo_reqheight() > lienzo.winfo_height():
                lienzo.yview_scroll(int(-e.delta / 120), "units")

        f.bind("<Configure>", ajustar)
        lienzo.bind("<Configure>", lambda e: (lienzo.itemconfigure(ventana, width=e.width), ajustar()))
        pagina.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", rueda))
        pagina.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))
        f.columnconfigure(1, weight=1)
        return f

    def _seccion(self, f, fila, texto):
        ttk.Label(f, text=texto, font=("Segoe UI", 9, "bold")).grid(
            row=fila, column=0, columnspan=3, sticky="w", pady=(10, 2))

    def _pestana_ala(self, nb, titulo, A, C2=None):
        f = self._marco(nb, titulo)
        fi = self.form.fila
        r = 0
        if C2 is not None:  # segunda ala
            ttk.Label(f, foreground="gray", justify="left", wraplength=360,
                      text="Solo informativo, para ver si caben dos alas en el bloque (no genera G-code). "
                           "El ala 2 se dibuja como quedará al girar el bloque 180° y cortarla igual que "
                           "el ala 1: boca abajo, entrando por la esquina de arriba del otro extremo.").grid(
                row=r, column=0, columnspan=3, sticky="w", padx=4); r += 1
            b = ttk.Frame(f)
            b.grid(row=r, column=0, columnspan=3, sticky="w", padx=4, pady=2)
            ttk.Button(b, text="Copiar todo del ala 1", command=self.copiar_ala1).pack(side="left")
            ttk.Label(b, text="  Con los mismos datos sale un ala igual.",
                      foreground="gray").pack(side="left")
            r += 1
            fi(f, r, lambda: self.p, "mismas_varillas", "Mismas varillas que el ala 1", "bool"); r += 1
        fi(f, r, A, "recta", "Ala recta (la punta es igual que la raíz)", "bool"); r += 1
        self._seccion(f, r, "Perfiles  (elige, busca escribiendo, o pon 'NACA 2412')"); r += 1
        categorias = ["Todas"] + sorted({d.get("categoria", "Mis perfiles") for d in self.catalogo.values()})
        ttk.Label(f, text="Categoría").grid(row=r, column=0, sticky="w", padx=4, pady=2)
        cb = ttk.Combobox(f, textvariable=self.categoria, values=categorias, state="readonly", width=24)
        cb.grid(row=r, column=1, sticky="we", padx=4, pady=2)
        cb.bind("<<ComboboxSelected>>", lambda e: self._filtrar_perfiles())
        r += 1
        for attr, et in (("perfil_raiz", "Perfil raíz"), ("perfil_punta", "Perfil punta")):
            ttk.Label(f, text=et).grid(row=r, column=0, sticky="w", padx=4, pady=2)
            var = tk.StringVar()
            w = ttk.Combobox(f, textvariable=var, width=24, height=25)
            w.grid(row=r, column=1, sticky="we", padx=4, pady=2)
            campo = dict(var=var, obj=A, attr=attr, tipo="str", opciones=None, widget=w)
            self.form.agregar(campo)
            w.bind("<<ComboboxSelected>>", lambda e, c=campo: self._perfil_elegido(c))
            w.bind("<KeyRelease>", lambda e, c=campo: self._filtrar_perfiles(c))
            self.combos_perfil.append(campo)
            boton = ttk.Button(f, text="...", width=3, command=lambda c=campo: self._elegir_perfil(c))
            boton.grid(row=r, column=2)
            if attr == "perfil_punta":
                self.botones_punta[titulo] = (A, boton)
            r += 1
            info = tk.StringVar()
            self.info_perfil.append((campo, info))
            ttk.Label(f, textvariable=info, foreground="gray", wraplength=360).grid(
                row=r, column=0, columnspan=3, sticky="w", padx=4)
            r += 1
        self._filtrar_perfiles()
        self._seccion(f, r, "Dimensiones"); r += 1
        for attr, et in (("cuerda_raiz", "Cuerda raíz"), ("cuerda_punta", "Cuerda punta"),
                         ("envergadura", "Longitud del panel"), ("flecha", "Flecha (BA punta hacia atrás)"),
                         ("desplaz_vertical", "Desplazamiento vertical punta")):
            fi(f, r, A, attr, et, unidad="mm"); r += 1
        self._seccion(f, r, "Torsión y espesor"); r += 1
        fi(f, r, A, "torsion_raiz", "Calado raíz (+ morro abajo)", unidad="°"); r += 1
        fi(f, r, A, "torsion_punta", "Calado punta (+ morro abajo)", unidad="°"); r += 1
        fi(f, r, A, "pivote_torsion", "Eje de torsión", unidad="% cuerda"); r += 1
        fi(f, r, A, "escala_espesor_raiz", "Espesor raíz", unidad="%"); r += 1
        fi(f, r, A, "escala_espesor_punta", "Espesor punta", unidad="%"); r += 1
        fi(f, r, A, "recubrimiento_raiz", "Recubrimiento raíz", unidad="mm"); r += 1
        fi(f, r, A, "recubrimiento_punta", "Recubrimiento punta", unidad="mm"); r += 1
        self._seccion(f, r, "Colocación"); r += 1
        fi(f, r, A, "raiz_lado", "Raíz junto a", opciones=LADOS); r += 1
        fi(f, r, A, "puntos", "Puntos por superficie", "int"); r += 1
        if C2 is not None:
            self._seccion(f, r, "Posición  (con el bloque girado, cero en su esquina de abajo)"); r += 1
            self._campos_colocacion(f, r, C2)

    def _campos_colocacion(self, f, r, C):
        fi = self.form.fila
        fi(f, r, C, "x_inicio", "Entrada (esquina → BS, mínimo)", unidad="mm"); r += 1
        fi(f, r, C, "altura", "Altura", unidad="mm"); r += 1
        fi(f, r, C, "referencia_altura", "Altura medida en", opciones=REFERENCIAS); r += 1
        fi(f, r, C, "orientacion", "Orientación", opciones=ORIENTACIONES); r += 1
        fi(f, r, C, "tramo_desde", "Tramo del intradós: desde", unidad="% cuerda"); r += 1
        fi(f, r, C, "tramo_hasta", "Tramo del intradós: hasta", unidad="% cuerda"); r += 1
        fi(f, r, C, "angulo_manual", "Ángulo manual (+ antihorario)", unidad="°"); r += 1
        fi(f, r, C, "invertir", "Invertir (extradós abajo)", "bool"); r += 1
        return r

    def _pestana_varillas(self, nb):
        f = self._marco(nb, "Varillas")
        ttk.Label(f, text="Agujeros de varillas, marcas y ranuras de larguero del ala 1.\n"
                          "Cada una con su posición en raíz y en punta.",
                  foreground="gray").grid(row=0, column=0, columnspan=2, sticky="w")
        cols = ("tipo", "sup", "raiz", "punta", "medida")
        self.arbol = ttk.Treeview(f, columns=cols, show="tree headings", height=12, selectmode="browse")
        self.arbol.heading("#0", text="Nombre")
        self.arbol.column("#0", width=100)
        for c, t, w in zip(cols, ("Tipo", "Lado", "Raíz", "Punta", "Medida"), (80, 60, 50, 50, 60)):
            self.arbol.heading(c, text=t)
            self.arbol.column(c, width=w, anchor="center")
        self.arbol.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=6)
        f.rowconfigure(1, weight=1)
        self.arbol.bind("<Double-1>", lambda e: self.editar_varilla())
        b = ttk.Frame(f)
        b.grid(row=2, column=0, columnspan=2, sticky="w")
        for t, cmd in (("Añadir", self.anadir_varilla), ("Editar", self.editar_varilla),
                       ("Duplicar", self.duplicar_varilla), ("Eliminar", self.eliminar_varilla)):
            ttk.Button(b, text=t, command=cmd).pack(side="left", padx=2)

    def _pestana_aleron(self, nb):
        f = self._marco(nb, "Alerón")
        AL = lambda: self.ala.aleron
        fi = self.form.fila
        r = 0
        fi(f, r, AL, "activo", "Cortar alerón o flap (bisagra arriba, V abierta por abajo)", "bool"); r += 1
        ttk.Label(f, foreground="gray", justify="left", wraplength=360,
                  text="En el mismo corte el hilo sube desde el intradós hasta la bisagra y vuelve a bajar, "
                       "quitando una cuña en V. Sin puente el alerón sale suelto (luego se une con cinta "
                       "por arriba); con puente queda sujeto por una tira fina de corcho.").grid(
            row=r, column=0, columnspan=3, sticky="w", padx=4); r += 1
        self._seccion(f, r, "Bisagra"); r += 1
        fi(f, r, AL, "cuerda_raiz", "Cuerda del alerón en la raíz (BS → bisagra)", unidad="mm"); r += 1
        fi(f, r, AL, "cuerda_punta", "Cuerda del alerón en la punta (BS → bisagra)", unidad="mm"); r += 1
        fi(f, r, AL, "angulo", "Ángulo de la V", unidad="°"); r += 1
        fi(f, r, AL, "puente", "Puente bajo el extradós (0 = sin puente)", unidad="mm"); r += 1
        self._seccion(f, r, "Tramos  (si el alerón ocupa solo una parte del panel)"); r += 1
        fi(f, r, AL, "dividir", "Partir el panel en tramos", "bool"); r += 1
        fi(f, r, AL, "desde", "El alerón empieza a (desde la raíz)", unidad="mm"); r += 1
        fi(f, r, AL, "hasta", "El alerón acaba a (0 = en la punta)", unidad="mm"); r += 1
        ttk.Label(f, text="Tramo que se ve y se exporta").grid(row=r, column=0, sticky="w", padx=4, pady=(8, 2))
        self.tramo_var = tk.StringVar()
        self.combo_tramo = ttk.Combobox(f, textvariable=self.tramo_var, state="readonly", width=30)
        self.combo_tramo.grid(row=r, column=1, columnspan=2, sticky="we", padx=4, pady=(8, 2))
        self.combo_tramo.bind("<<ComboboxSelected>>", lambda e: self._elegir_tramo())
        r += 1
        ttk.Button(f, text="Exportar todos los tramos...", command=self.exportar_tramos).grid(
            row=r, column=0, columnspan=3, pady=6)
        r += 1
        ttk.Label(f, foreground="gray", justify="left", wraplength=360,
                  text="Cada tramo es un trozo de ala que se corta por separado, con sus cuerdas, perfil, "
                       "calado y varillas en ese punto. Solo el tramo del alerón lleva la V.").grid(
            row=r, column=0, columnspan=3, sticky="w", padx=4)

    def _elegir_tramo(self):
        self._tramo_idx = max(0, self.combo_tramo.current())
        for v in self.vistas:
            v.vista = None
        self.recalcular()

    def _pestana_fuselaje(self, nb):
        f = self._marco(nb, "Fuselaje")
        F = lambda: self.p.fuselaje
        fi = self.form.fila
        r = 0
        fi(f, r, F, "metodo", "Método", opciones=METODOS_FUS); r += 1
        self._seccion(f, r, "Siluetas"); r += 1
        fi(f, r, F, "fuente", "Forma desde", opciones=FUENTES_FUS); r += 1
        fi(f, r, F, "vista", "Vista que se corta", opciones=VISTAS_FUS); r += 1
        c = fi(f, r, F, "dxf", "Fichero DXF", "str", ancho=22)
        ttk.Button(f, text="...", width=3, command=lambda c=c: self._elegir_fichero(
            c, "DXF", "*.dxf")).grid(row=r, column=2); r += 1
        fi(f, r, F, "escala_dxf", "Escala del DXF"); r += 1
        self._seccion(f, r, "Forma por medidas"); r += 1
        for attr, et, ud in (("largo", "Largo", "mm"), ("alto", "Alto máximo", "mm"), ("ancho", "Ancho máximo", "mm"),
                             ("pos_max", "Parte más gruesa a", "% largo"),
                             ("morro", "Morro (1 punta, 2 redondo, 3 romo)", ""),
                             ("alto_cola", "Alto en la cola", "mm"), ("ancho_cola", "Ancho en la cola", "mm"),
                             ("subida_cola", "Subida de la cola", "mm"),
                             ("seccion", "Cuadernas (2 elipse, 4 rectang.)", "")):
            fi(f, r, F, attr, et, unidad=ud); r += 1
        self._seccion(f, r, "STL"); r += 1
        c = fi(f, r, F, "stl", "Fichero STL", "str", ancho=22)
        ttk.Button(f, text="...", width=3, command=lambda c=c: self._elegir_fichero(
            c, "STL", "*.stl")).grid(row=r, column=2); r += 1
        fi(f, r, F, "eje_stl", "Eje a lo largo del fuselaje", opciones=EJES_STL); r += 1
        fi(f, r, F, "arriba_stl", "Eje hacia arriba", opciones=EJES_STL); r += 1
        fi(f, r, F, "escala_stl", "Escala del STL"); r += 1
        self._seccion(f, r, "Tramos"); r += 1
        fi(f, r, F, "n_tramos", "Número de tramos iguales", "int"); r += 1
        fi(f, r, F, "cortes", "o cortes en (mm, separados por espacios)", "str", ancho=22); r += 1
        fi(f, r, F, "pared", "Pared para vaciar (0 = macizo)", unidad="mm"); r += 1
        fi(f, r, F, "colocar_auto", "Buscar la mejor posición del bloque en el hilo", "bool"); r += 1
        fi(f, r, F, "puntos", "Puntos por contorno", "int"); r += 1
        ttk.Label(f, text="Pieza que se ve y se exporta").grid(row=r, column=0, sticky="w", padx=4, pady=(8, 2))
        self.pieza_var = tk.StringVar()
        self.combo_pieza = ttk.Combobox(f, textvariable=self.pieza_var, state="readonly", width=30)
        self.combo_pieza.grid(row=r, column=1, columnspan=2, sticky="we", padx=4, pady=(8, 2))
        self.combo_pieza.bind("<<ComboboxSelected>>", lambda e: self._elegir_pieza())
        r += 1
        ttk.Button(f, text="Exportar todas las piezas...", command=self.exportar_piezas).grid(
            row=r, column=0, columnspan=3, pady=6)

    def _pestana_avion(self, nb):
        f = self._marco(nb, "Avión")
        AV = lambda: self.p.avion
        fi = self.form.fila
        r = 0
        fi(f, r, AV, "tipo_cola", "Tipo", opciones=TIPOS_COLA); r += 1
        fi(f, r, AV, "con_fuselaje", "Con fuselaje (el de la pieza Fuselaje)", "bool"); r += 1
        self._seccion(f, r, "Posición de las piezas  (x desde el morro, z hacia arriba)"); r += 1
        for attr, et, ud in (("x_ala", "Ala: BA de la raíz a", "mm"), ("z_ala", "Ala: altura", "mm"),
                             ("diedro_ala", "Ala: diedro de cada mitad", "°"),
                             ("separacion_raices", "Ala: separación entre raíces", "mm"),
                             ("x_estab", "Cola: BA de la raíz a", "mm"), ("z_estab", "Cola: altura", "mm"),
                             ("calado_estab", "Cola: calado respecto al ala", "°"),
                             ("angulo_v", "Cola en V: ángulo de cada mitad", "°"),
                             ("x_deriva", "Deriva: BA de la raíz a", "mm"), ("z_deriva", "Deriva: altura", "mm")):
            fi(f, r, AV, attr, et, unidad=ud); r += 1
        self._seccion(f, r, "Pesos"); r += 1
        fi(f, r, AV, "densidad", "Densidad del porexpán", unidad="kg/m³"); r += 1
        cols = ("masa", "x")
        self.arbol_comp = ttk.Treeview(f, columns=cols, show="tree headings", height=6, selectmode="browse")
        self.arbol_comp.heading("#0", text="Componente")
        self.arbol_comp.column("#0", width=140)
        for c, et, w in zip(cols, ("Masa (g)", "x (mm)"), (70, 70)):
            self.arbol_comp.heading(c, text=et)
            self.arbol_comp.column(c, width=w, anchor="center")
        self.arbol_comp.grid(row=r, column=0, columnspan=3, sticky="we", padx=4, pady=4); r += 1
        self.arbol_comp.bind("<Double-1>", lambda e: self.editar_componente())
        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        for et, cmd in (("Añadir", self.anadir_componente), ("Editar", self.editar_componente),
                        ("Eliminar", self.eliminar_componente)):
            ttk.Button(b, text=et, command=cmd).pack(side="left", padx=2)
        self.estimacion = tk.StringVar()
        ttk.Label(f, textvariable=self.estimacion, foreground="#1a7a3a", wraplength=360).grid(
            row=r, column=0, columnspan=3, sticky="w", padx=4, pady=(6, 2)); r += 1
        fi(f, r, AV, "peso", "Peso del avión (el tuyo)", unidad="g"); r += 1
        fi(f, r, AV, "cg", "CG (el tuyo) desde el morro", unidad="mm"); r += 1
        ttk.Button(f, text="Usar la estimación", command=self.usar_estimacion).grid(
            row=r, column=0, columnspan=3, pady=4); r += 1
        self._seccion(f, r, "Vuelo"); r += 1
        fi(f, r, AV, "velocidad", "Velocidad de vuelo", unidad="m/s"); r += 1
        fi(f, r, AV, "cl_max", "CL máximo del perfil del ala"); r += 1
        fi(f, r, AV, "acabado", "Acabado de las superficies", opciones=ACABADOS); r += 1
        fi(f, r, AV, "margen", "Margen estático objetivo", unidad="% CMA"); r += 1
        self._seccion(f, r, "Mandos  (superficies de los cortes de alerón y timones)"); r += 1
        for attr, et, ud in (("recorrido_aleron", "Recorrido de alerones / elevones", "°"),
                             ("recorrido_profundidad", "Recorrido de profundidad", "°"),
                             ("recorrido_direccion", "Recorrido de dirección", "°"),
                             ("servo_aleron", "Par del servo de alerón", "kg·cm"),
                             ("servo_profundidad", "Par del servo de profundidad", "kg·cm"),
                             ("servo_direccion", "Par del servo de dirección", "kg·cm"),
                             ("v_mandos", "Velocidad para las fuerzas (0 = máxima)", "m/s")):
            fi(f, r, AV, attr, et, unidad=ud); r += 1
        MO = lambda: self.p.avion.motor
        self._seccion(f, r, "Motor, batería y hélice"); r += 1
        fi(f, r, MO, "activa", "Calcular motor, batería y hélice", "bool"); r += 1
        for attr, et, tipo, ud in (("celdas", "Batería: celdas (S)", "int", "S"), ("capacidad", "Batería: capacidad", "float", "mAh"),
                                   ("c", "Batería: descarga máxima", "float", "C"),
                                   ("r_celda", "Batería: resistencia por celda", "float", "mΩ"),
                                   ("kv", "Motor: Kv", "float", "rpm/V"), ("rm", "Motor: resistencia", "float", "mΩ"),
                                   ("i0", "Motor: corriente en vacío", "float", "A"),
                                   ("i_max", "Motor: corriente máxima", "float", "A"),
                                   ("diametro", "Hélice: diámetro", "float", "pulg."), ("paso", "Hélice: paso", "float", "pulg."),
                                   ("palas", "Hélice: palas", "int", "")):
            fi(f, r, MO, attr, et, tipo, unidad=ud); r += 1
        fi(f, r, MO, "despegue", "Despegue", opciones=DESPEGUES); r += 1
        fi(f, r, MO, "v_lanzamiento", "Velocidad al lanzarlo", unidad="m/s"); r += 1
        fi(f, r, MO, "rozamiento", "Rodadura (asfalto 0,04, hierba 0,1)"); r += 1
        ttk.Label(f, foreground="gray", wraplength=360, justify="left",
                  text="Los resultados del cálculo salen en la columna de la derecha.").grid(
            row=r, column=0, columnspan=3, sticky="w", padx=4, pady=(8, 4))

    # ---------- componentes ----------
    def refrescar_componentes(self):
        self.arbol_comp.delete(*self.arbol_comp.get_children())
        for i, c in enumerate(self.p.avion.componentes):
            self.arbol_comp.insert("", "end", iid=str(i), text=c.nombre, values=(f"{c.masa:g}", f"{c.x:g}"))

    def _dialogo_componente(self, c):
        w = tk.Toplevel(self)
        w.title("Componente")
        w.transient(self)
        w.resizable(False, False)
        c = copy.deepcopy(c)
        res = {}
        fr = ttk.Frame(w, padding=10)
        fr.pack()
        form = Formulario(lambda: None)
        for i, (attr, et, tipo, ud) in enumerate((("nombre", "Nombre", "str", ""), ("masa", "Masa", "float", "g"),
                                                  ("x", "Posición desde el morro", "float", "mm"))):
            form.fila(fr, i, lambda: c, attr, et, tipo, unidad=ud, ancho=20)
        form.refrescar()

        def ok():
            res["c"] = c
            w.destroy()
        bb = ttk.Frame(fr)
        bb.grid(row=4, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(bb, text="Aceptar", command=ok).pack(side="left", padx=4)
        ttk.Button(bb, text="Cancelar", command=w.destroy).pack(side="left")
        w.bind("<Return>", lambda e: ok())
        w.grab_set()
        w.wait_window()
        return res.get("c")

    def anadir_componente(self):
        c = self._dialogo_componente(Componente(nombre=f"Componente {len(self.p.avion.componentes) + 1}"))
        if c:
            self.p.avion.componentes.append(c)
            self.recalcular()

    def editar_componente(self):
        s = self.arbol_comp.selection()
        if s:
            i = int(s[0])
            c = self._dialogo_componente(self.p.avion.componentes[i])
            if c:
                self.p.avion.componentes[i] = c
                self.recalcular()

    def eliminar_componente(self):
        s = self.arbol_comp.selection()
        if s:
            del self.p.avion.componentes[int(s[0])]
            self.recalcular()

    def usar_estimacion(self):
        r = getattr(self, "avion_res", None)
        if r is not None:
            self.p.avion.peso = round(r.peso_est)
            self.p.avion.cg = round(r.cg_est)
            self.form.refrescar({"peso", "cg"})
            self.recalcular()

    # ---------- cálculo del avión ----------
    def _recalcular_avion(self):
        self.res = self.info = None
        self.piezas, self.tramos = [], []
        self.bloque = self.planta = None
        self.pc = self.p
        self.refrescar_componentes()
        self.texto_avion.delete("1.0", "end")
        try:
            self.avion_res = r = calcular_avion(self.p)
        except (ErrorGeometria, ValueError, OSError, ZeroDivisionError) as e:
            self.avion_res = None
            self.estado.insert("end", f"Error: {e}\n", "error")
            self.dibujar()
            return
        av = self.p.avion
        self.estimacion.set(f"Estimado: {r.peso_est:.0f} g, CG a {r.cg_est:.0f} mm del morro "
                            f"({r.cg_est - av.x_ala:.0f} mm del BA de la raíz del ala)")
        for l in r.lineas:
            titulo = l.isupper() or l.split("  (")[0].isupper()
            self.texto_avion.insert("end", l + "\n", "titulo" if titulo else "")
        for a in r.avisos:
            self.texto_avion.insert("end", "⚠ " + a + "\n", "aviso")
        cg = av.cg if av.cg > 0 else r.cg_est
        margen = (r.x_np - cg) / r.ala.cma * 100
        self.estado.insert("end", f"Avión · punto neutro a {r.x_np - av.x_ala:.0f} mm del BA de la raíz   ·   "
                                  f"CG recomendado a {r.x_cg_rec - av.x_ala:.0f} mm   ·   tu CG a {cg - av.x_ala:.0f} mm "
                                  f"(margen {margen:.0f}%)\n", "bien" if 3 <= margen <= 25 else "aviso")
        for a in r.avisos:
            self.estado.insert("end", f"Aviso: {a}\n", "aviso")
        self.dibujar()

    def _marcas_cg(self, ax, y):
        """Punto neutro, zona de CG recomendada, CG estimado y CG del usuario sobre la línea y."""
        r, av = self.avion_res, self.p.avion
        c = r.ala.cma
        ax.axvspan(r.x_np - 15 / 100 * c, r.x_np - 5 / 100 * c, color="#5cb85c", alpha=0.18,
                   label="CG recomendado (5–15%)")
        ax.plot(r.x_np, y, "^", color="#c00000", ms=9, label="Punto neutro", zorder=6)
        ax.plot(r.cg_est, y, "x", color="#666", ms=8, mew=2, label="CG estimado", zorder=6)
        if av.cg > 0:
            ax.plot(av.cg, y, "o", mfc="white", mec="k", ms=10, mew=2, label="Tu CG", zorder=7)
            ax.plot(av.cg, y, "+", color="k", ms=10, mew=1.5, zorder=8)

    def _dibujar_avion(self, vista):
        v = self.v1 if vista == "lateral" else self.v3
        ax = v.nuevo()
        r = getattr(self, "avion_res", None)
        if r is None:
            v.mostrar([np.array([[0.0, 0.0], [100.0, 100.0]])])
            return
        pols = (lateral_avion if vista == "lateral" else planta_avion)(self.p, r)
        puntos = []
        for P, color in pols:
            ax.add_patch(Polygon(P, closed=True, fc=color, ec="#444", lw=0.8, alpha=0.9))
            puntos.append(P)
        self._marcas_cg(ax, 0.0)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_xlabel("mm desde el morro")
        v.mostrar(puntos)

    # ---------- materiales ----------
    def _opciones_materiales(self):
        return {m.nombre: m.nombre for m in self.materiales}

    def _refrescar_materiales(self):
        ops = self._opciones_materiales()
        self.campo_material["opciones"] = ops
        self.campo_material["widget"].configure(values=list(ops.values()))
        self.form.refrescar({"material"})

    def _elegir_material(self):
        mat = mats.buscar(self.materiales, self.p.corte.material)
        if mat is not None:
            mats.aplicar(self.p, mat)
            self.form.refrescar()
            self.recalcular()

    def _elegir_fichero(self, campo, tipo, patron):
        ruta = filedialog.askopenfilename(title=f"Elegir {tipo}", initialdir=DOCUMENTOS,
                                          filetypes=[(tipo, patron), ("Todos", "*.*")])
        if ruta:
            campo["var"].set(str(Path(ruta)))

    def _elegir_pieza(self):
        self._pieza_idx = max(0, self.combo_pieza.current())
        for v in self.vistas:
            v.vista = None
        self.recalcular()

    def _actualizar_pestanas(self):
        modo = self.p.pieza
        if modo == self._modo:
            return
        cambia_ala = self._modo is not None
        self._modo = modo
        visibles = PESTANAS_MODO[modo]
        for titulo, marco in self.marcos_pestana.items():
            if titulo in visibles:
                self.pestanas.add(marco)
            else:
                self.pestanas.hide(marco)
        cola_v = self.p.avion.tipo_cola == "v"
        nombre = {"estabilizador": "Cola en V" if cola_v else "Estabilizador", "deriva": "Deriva"}.get(modo, "Ala")
        self.pestanas.tab(self.marcos_pestana["Ala"], text=nombre)
        self.pestanas.tab(self.marcos_pestana["Alerón"],
                          text="Timón" if modo in ("estabilizador", "deriva") else "Alerón")
        self.pestanas.select(self.marcos_pestana[visibles[0]])
        if modo == "avion":
            self.panel_resultados.pack(side="right", fill="y", before=self.zona_vistas)
        else:
            self.panel_resultados.pack_forget()
        for v in self.vistas:
            v.vista = None
        if cambia_ala:  # los campos del ala pasan a mostrar el ala activa
            self.form.refrescar()
            self.refrescar_varillas()

    def _recalcular_fuselaje(self):
        self.bloque = None
        self.planta = None
        self.pc = self.p
        self.tramos = []
        try:
            self.piezas = piezas_fuselaje(self.p, self.m)
            etiquetas = [x[0] for x in self.piezas]
            self.combo_pieza.configure(values=etiquetas)
            self._pieza_idx = min(self._pieza_idx, len(etiquetas) - 1)
            self.pieza_var.set(etiquetas[self._pieza_idx])
            etiqueta, self.res, self.descripcion = self.piezas[self._pieza_idx]
            _, info = generar(self.res, self.p, self.m, self._nombre_pieza(), self.descripcion)
            self.info = info
        except (ErrorGeometria, ValueError, OSError) as e:
            self.res = self.info = None
            self.piezas = []
            self.estado.insert("end", f"Error: {e}\n", "error")
            self.dibujar()
            return
        t = info["tiempo_min"]
        self.estado.insert("end", f"Fuselaje · {etiqueta} · tiempo estimado {int(t)}:{int(t % 1 * 60):02d} min   ·   "
                                  f"velocidad máx. de torre {info['vmax_torre']:.0f} mm/min   ·   "
                                  f"{info['lineas']} líneas\n")
        if len(self.piezas) > 1:
            self.estado.insert("end", f"{len(self.piezas)} piezas; se elige cuál ver en la pestaña Fuselaje.\n", "aviso")
        if info["limitados"]:
            self.estado.insert("end", f"Aviso: {info['limitados']} movimientos limitados por la velocidad "
                                      f"máxima de la máquina.\n", "aviso")
        for a in self.res.avisos:
            self.estado.insert("end", f"{'' if a.startswith('Coloca') else 'Aviso: '}{a}\n",
                               "bien" if a.startswith("Coloca") else "aviso")
        self.dibujar()

    def _nombre_pieza(self, i=None):
        base = Path(self.ruta).stem if self.ruta else "fuselaje"
        f = self.p.fuselaje
        if f.metodo == "silueta":
            return f"{base}_silueta_{f.vista}"
        return f"{base}_tramo{(self._pieza_idx if i is None else i) + 1}"

    def exportar_piezas(self):
        if not self.piezas:
            messagebox.showerror("AeroFoam", "Corrige los errores antes de generar el G-code.")
            return
        textos = [(self._nombre_pieza(i), generar(res, self.p, self.m, self._nombre_pieza(i), desc)[0], et)
                  for i, (et, res, desc) in enumerate(self.piezas)]
        carpeta = filedialog.askdirectory(title="Carpeta donde guardar las piezas", initialdir=DOCUMENTOS)
        if not carpeta:
            return
        hechos = []
        for nombre, g, et in textos:
            destino = Path(carpeta) / f"{nombre}.gcode"
            destino.write_text(g, encoding="ascii", newline="\n")
            hechos.append(f"{destino.name}   ({et})")
        self.guardar_maquina(silencioso=True)
        messagebox.showinfo("AeroFoam", f"G-code guardado en {carpeta}:\n\n" + "\n".join(hechos))

    def _dibujar_fuselaje(self):
        ax = self.v3.nuevo()
        f = self.p.fuselaje
        try:
            if f.metodo == "stl" or (f.metodo == "silueta" and f.fuente == "stl"):
                L = float(_stl(f)[:, :, 0].max())
                vistas = {"lateral": silueta_cache(f, "lateral", 120), "planta": silueta_cache(f, "planta", 120)}
            elif f.metodo == "silueta" and f.fuente == "dxf":
                cara = self.res.raiz[2:-2] if self.res is not None else np.zeros((1, 2))
                L = float(np.ptp(cara[:, 0]))
                vistas = {f.vista: cara - cara.min(axis=0)}
            else:
                L = f.largo
                x = np.linspace(0, L, 300)
                hh, hw, zc = forma(f, x)
                vistas = {"lateral": np.vstack([np.column_stack([x, zc - hh]), np.column_stack([x, zc + hh])[::-1]]),
                          "planta": np.vstack([np.column_stack([x, -hw]), np.column_stack([x, hw])[::-1]])}
        except (ErrorGeometria, ValueError, OSError):
            self.v3.mostrar([np.array([[0.0, 0.0], [100.0, 100.0]])])
            return
        puntos = []
        y0 = 0.0
        for nombre in ("lateral", "planta"):
            if nombre not in vistas:
                continue
            P = vistas[nombre]
            P = P - (0, (P[:, 1].min() + P[:, 1].max()) / 2) + (0, y0)
            ax.add_patch(Polygon(P, closed=True, fc="#cfe0f5", ec=COLORES[1][0], lw=1.3, zorder=2))
            ax.annotate("Vista lateral" if nombre == "lateral" else "Vista en planta", (0, P[:, 1].max()),
                        textcoords="offset points", xytext=(0, 4), fontsize=9, color="#333")
            puntos.append(P)
            y0 = P[:, 1].min() - 0.8 * np.ptp(P[:, 1]) - 30
        todos = np.vstack(puntos)
        if f.metodo in ("tramos", "stl"):
            est = _estaciones(f, L)
            for k, (x1, x2) in enumerate(est):
                if k == self._pieza_idx:
                    ax.axvspan(x1, x2, color="#ffb347", alpha=0.25, zorder=1, label="Pieza elegida")
                ax.axvline(x1, color="#888", ls="--", lw=0.8, zorder=3)
            ax.axvline(est[-1][1], color="#888", ls="--", lw=0.8, zorder=3)
            texto = [f"Largo {L:.0f} mm  ·  {len(est)} tramos"] + [
                f"Tramo {k + 1}: {x1:.0f}–{x2:.0f} mm ({x2 - x1:.0f} mm)" for k, (x1, x2) in enumerate(est)]
            ax.legend(loc="upper right", fontsize=8)
        else:
            texto = [f"Largo {L:.0f} mm", "Corta una vista, gira el bloque 90° y corta la otra; luego lija."]
        ax.text(0.01, 0.01, "\n".join(texto), transform=ax.transAxes, va="bottom", fontsize=8,
                bbox=dict(fc="white", ec="#bbb", alpha=0.9))
        ax.set_xlabel("mm desde el morro")
        self.v3.mostrar([todos])

    def _pestana_corte(self, nb):
        f = self._marco(nb, "Corte")
        C = lambda: self.p.corte
        fi = self.form.fila
        r = 0
        self._seccion(f, r, "Bloque  (cero = esquina inferior del lado del BS)"); r += 1
        fi(f, r, C, "bloque_largo", "Largo del bloque (0 = no dibujar)", unidad="mm"); r += 1
        fi(f, r, C, "bloque_alto", "Alto del bloque", unidad="mm"); r += 1
        fi(f, r, C, "dist_torre_bloque", "Torre 1 → cara del bloque", unidad="mm"); r += 1
        self._seccion(f, r, "Posición y orientación del ala 1"); r += 1
        r = self._campos_colocacion(f, r, C)
        self._seccion(f, r, "Hilo"); r += 1
        self.campo_material = fi(f, r, C, "material", "Material", opciones=self._opciones_materiales()); r += 1
        self.campo_material["widget"].bind("<<ComboboxSelected>>", lambda e: self._elegir_material())
        fi(f, r, C, "kerf_raiz", "Kerf raíz (ancho quemado)", unidad="mm"); r += 1
        fi(f, r, C, "kerf_punta", "Kerf punta (ancho quemado)", unidad="mm"); r += 1
        fi(f, r, C, "potencia", "Potencia (S)"); r += 1
        fi(f, r, C, "precalentamiento", "Precalentamiento", unidad="s"); r += 1
        self._seccion(f, r, "Velocidades (F)"); r += 1
        fi(f, r, C, "vel_corte", "Corte del perfil", unidad="mm/min"); r += 1
        fi(f, r, C, "vel_entrada", "Entrada / salida", unidad="mm/min"); r += 1
        fi(f, r, C, "vel_varillas", "Varillas y ranuras", unidad="mm/min"); r += 1
        fi(f, r, C, "pausa_varillas", "Pausa en giros de varillas (0 = no)", unidad="s"); r += 1
        fi(f, r, C, "vel_desplazamiento", "Desplazamiento fuera del bloque", unidad="mm/min"); r += 1
        fi(f, r, C, "modo_velocidad", "Cálculo de la F", opciones=MODOS); r += 1
        ttk.Label(f, foreground="gray", justify="left", wraplength=330,
                  text="'F sin corregir': se escribe la F tal cual (F300 = F300 en el G-code). "
                       "'F corregida': calcula la F de cada línea para que el hilo corte de verdad "
                       "a esa velocidad en la cara rápida del bloque.").grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _pestana_maquina(self, nb):
        f = self._marco(nb, "Máquina")
        M = lambda: self.m
        fi = self.form.fila
        r = 0
        self._seccion(f, r, "Dimensiones"); r += 1
        fi(f, r, M, "distancia_torres", "Distancia entre torres (hilo)", unidad="mm"); r += 1
        fi(f, r, M, "recorrido_x", "Recorrido horizontal", unidad="mm"); r += 1
        fi(f, r, M, "recorrido_y", "Recorrido vertical", unidad="mm"); r += 1
        fi(f, r, M, "vel_max", "Velocidad máxima de las torres", unidad="mm/min"); r += 1
        self._seccion(f, r, "Ejes GRBL"); r += 1
        for i, et in enumerate(("Torre 1 horizontal", "Torre 1 vertical", "Torre 2 horizontal",
                                "Torre 2 vertical"), 1):
            fi(f, r, M, f"eje{i}", et, "str", ancho=6); r += 1
        fi(f, r, M, "decimales", "Decimales", "int", ancho=6); r += 1
        self._seccion(f, r, "Código de inicio / fin  ({potencia}, {precalentamiento})"); r += 1
        self.textos = {}
        for attr, et, alto in (("cabecera", "Cabecera", 3), ("encender", "Encender hilo", 1),
                               ("apagar", "Apagar hilo", 1), ("pie", "Pie", 2)):
            ttk.Label(f, text=et).grid(row=r, column=0, sticky="nw", padx=4, pady=2)
            t = tk.Text(f, height=alto, width=26, font=("Consolas", 9))
            t.grid(row=r, column=1, columnspan=2, sticky="we", padx=4, pady=2)
            t.bind("<KeyRelease>", lambda e, a=attr, t=t: self._texto_cambiado(a, t))
            self.textos[attr] = t
            r += 1
        ttk.Button(f, text="Guardar configuración de máquina", command=self.guardar_maquina).grid(
            row=r, column=0, columnspan=3, pady=10)

    def _texto_cambiado(self, attr, t):
        setattr(self.m, attr, t.get("1.0", "end-1c"))
        self.programar()

    def _refrescar_textos(self):
        for attr, t in self.textos.items():
            t.delete("1.0", "end")
            t.insert("1.0", getattr(self.m, attr))

    # ---------- ala recta y segunda ala ----------
    def _ala_de(self, campo):
        """Ala a la que pertenece un campo (el kerf de la punta va con el ala 1)."""
        o = campo["obj"]()
        return o if isinstance(o, Ala) else self.ala

    def _es_punta_recta(self, campo):
        return campo["attr"] in self.ATTRS_PUNTA and self._ala_de(campo).recta

    def _estado_recta(self):
        for c in self.form.campos:
            if c["attr"] in self.ATTRS_PUNTA:
                c["widget"].configure(state="disabled" if self._ala_de(c).recta else "normal")
        for A, boton in self.botones_punta.values():
            boton.configure(state="disabled" if A().recta else "normal")

    def copiar_ala1(self):
        self.p.ala2 = copy.deepcopy(self.p.ala)
        for c in ("x_inicio", "altura", "referencia_altura", "orientacion", "angulo_manual",
                  "tramo_desde", "tramo_hasta", "invertir"):
            setattr(self.p.corte2, c, getattr(self.p.corte, c))
        self.p.doble = True
        self.form.refrescar()
        self.recalcular()

    # ---------- varillas ----------
    def refrescar_varillas(self, seleccion=None):
        self.arbol.delete(*self.arbol.get_children())
        for i, v in enumerate(self.ala.varillas):
            medida = {"redondo": f"Ø{v.diametro:g}", "marca": f"{v.prof_marca:g}",
                      "rectangular": f"{v.ancho:g}x{v.alto:g}"}[v.tipo]
            self.arbol.insert("", "end", iid=str(i), text=v.nombre,
                              values=(v.tipo, "arriba" if v.superficie == "extrados" else "abajo",
                                      f"{v.pos_raiz:g}", f"{v.pos_punta:g}", medida))
        if seleccion is not None and 0 <= seleccion < len(self.ala.varillas):
            self.arbol.selection_set(str(seleccion))

    def _sel(self):
        s = self.arbol.selection()
        return int(s[0]) if s else None

    def anadir_varilla(self):
        d = DialogoVarilla(self, Varilla(nombre=f"Varilla {len(self.ala.varillas) + 1}"), self.ala.recta)
        if d.resultado:
            self.ala.varillas.append(d.resultado)
            self.refrescar_varillas(len(self.ala.varillas) - 1)
            self.programar()

    def editar_varilla(self):
        i = self._sel()
        if i is None:
            return
        d = DialogoVarilla(self, self.ala.varillas[i], self.ala.recta)
        if d.resultado:
            self.ala.varillas[i] = d.resultado
            self.refrescar_varillas(i)
            self.programar()

    def duplicar_varilla(self):
        i = self._sel()
        if i is None:
            return
        v = copy.deepcopy(self.ala.varillas[i])
        v.nombre += " (copia)"
        self.ala.varillas.insert(i + 1, v)
        self.refrescar_varillas(i + 1)
        self.programar()

    def eliminar_varilla(self):
        i = self._sel()
        if i is None:
            return
        del self.ala.varillas[i]
        self.refrescar_varillas()
        self.programar()

    # ---------- cálculo y dibujo ----------
    def programar(self):
        if self._tarea:
            self.after_cancel(self._tarea)
        self._tarea = self.after(300, self.recalcular)

    def recalcular(self):
        self._tarea = None
        self.sim_parar()
        sincronizar_recta(self.ala, self.p.corte)
        sincronizar_recta(self.p.ala2)
        if self.p != self._estado_ok:  # cambio confirmado: se guarda el estado anterior para deshacer
            self._historial.append(self._estado_ok)
            del self._historial[:-100]
            self._rehacer.clear()
            self._estado_ok = copy.deepcopy(self.p)
        if self.ala.recta or self.p.ala2.recta:
            self.form.refrescar(self._es_punta_recta)
            if self.ala.recta:
                self.refrescar_varillas(self._sel())
        self._estado_recta()
        self._info_perfiles()
        self.estado.delete("1.0", "end")
        self._actualizar_pestanas()
        if self.p.pieza == "avion":
            self._recalcular_avion()
            return
        if self.p.pieza == "fuselaje":
            self._recalcular_fuselaje()
            return
        self.piezas = []
        self.descripcion = None
        self.bloque = None
        self.planta = None
        try:
            self.tramos = dividir(self._p_activo())
            etiquetas = [t[0] for t in self.tramos]
            self.combo_tramo.configure(values=etiquetas)
            self._tramo_idx = min(self._tramo_idx, len(etiquetas) - 1)  # se mantiene al cambiar los datos
            self.tramo_var.set(etiquetas[self._tramo_idx])
            self.pc = self.tramos[self._tramo_idx][1]
            self.res = calcular(self.pc, self.m)
            _, info = generar(self.res, self.pc, self.m)
            self.info = info
            self.planta = calcular_planta(self.pc, self.m, self.res)
        except (ErrorGeometria, ValueError) as e:
            self.res = None
            self.info = None
            self.pc = self._p_activo()
            self.estado.insert("end", f"Error: {e}\n", "error")
            self.dibujar()
            return
        t = info["tiempo_min"]
        self.estado.insert("end", f"{PIEZAS[self.p.pieza].split(' /')[0]} · tiempo estimado {int(t)}:{int(t % 1 * 60):02d} min   ·   "
                                  f"velocidad máx. de torre {info['vmax_torre']:.0f} mm/min   ·   "
                                  f"{info['lineas']} líneas"
                                  + (f"   ·   perfil girado {self.res.giro:+.2f}°"
                                     if abs(self.res.giro) > 1e-6 else "") + "\n")
        if len(self.tramos) > 1:
            self.estado.insert("end", f"Mostrando {self.tramo_var.get()}  ({len(self.tramos)} tramos; "
                                      f"se cambia en la pestaña Alerón)\n", "aviso")
        if info["limitados"]:
            self.estado.insert("end", f"Aviso: {info['limitados']} movimientos limitados por la velocidad "
                                      f"máxima de la máquina.\n", "aviso")
        for a in self.res.avisos:
            self.estado.insert("end", f"Aviso: {a}\n", "aviso")
        try:
            self.bloque = calcular_bloque(self.pc, self.m, self.res, con_ala2=self.en_ala2())
        except (ErrorGeometria, ValueError) as e:
            self.estado.insert("end", f"Ala 2: {e}\n", "error")
        if self.bloque and self.bloque.material:
            caras = {"A": "cara torre 1", "B": "cara torre 2"}
            textos = [f"{caras[k]} {v:.1f} mm" for k, v in self.bloque.material.items()]
            peor = min(self.bloque.material.values())
            if peor <= 0:
                self.estado.insert("end", "Bloque: ¡las dos alas se solapan! (" + ", ".join(textos) + ")\n",
                                   "error")
            else:
                self.estado.insert("end", "Bloque: corcho entre las dos alas: " + ", ".join(textos) + "\n",
                                   "bien" if peor >= 3 else "aviso")
            for a in self.bloque.avisos:
                self.estado.insert("end", f"Aviso: {a}\n", "aviso")
        self.dibujar()

    def _rect_bloque(self, ax, puntos):
        c = self.p.corte
        if c.bloque_largo > 0 and c.bloque_alto > 0:
            ax.add_patch(Rectangle((0, 0), c.bloque_largo, c.bloque_alto, fill=True, fc="#f3ecd0",
                                   ec="#b8a060", lw=0.8, zorder=0, label="Bloque"))
            puntos.append(np.array([[c.bloque_largo, c.bloque_alto]]))

    def dibujar(self):
        self._dibujar_ala1()
        self._dibujar_bloque()
        self._dibujar_planta()
        if self.marcos[3].winfo_ismapped():
            self._dibujar_3d()

    def _partes_3d(self):
        if self.p.pieza == "avion":
            r = getattr(self, "avion_res", None)
            return (partes_avion(self.p, r), "Avión montado") if r is not None else ([], "")
        if self.res is None:
            return [], ""
        if self.p.pieza == "fuselaje":
            if not self.piezas:
                return [], ""
            titulo = ("Pieza que sale de este corte" if self.p.fuselaje.metodo == "silueta"
                      else "Fuselaje completo (en naranja, el tramo elegido)")
            return partes_fuselaje(self.piezas, self._pieza_idx), titulo
        titulo = "Panel que sale de este corte" + (f"  ·  {self.tramo_var.get()}" if len(self.tramos) > 1 else "")
        return partes_ala(self.pc, self.res), titulo

    def _dibujar_3d(self):
        partes, titulo = self._partes_3d()
        self.v4.dibujar(partes, titulo)

    def exportar_stl(self):
        partes, _ = self._partes_3d()
        if not partes:
            messagebox.showerror("AeroFoam", "Corrige los errores antes de exportar el modelo.")
            return
        base = Path(self.ruta).stem if self.ruta else self.p.pieza
        ruta = filedialog.asksaveasfilename(title="Exportar modelo 3D", initialfile=base + ".stl",
                                            initialdir=DOCUMENTOS, defaultextension=".stl",
                                            filetypes=[("STL", "*.stl")])
        if ruta:
            a_stl(partes, ruta)
            messagebox.showinfo("AeroFoam", f"Modelo 3D guardado en:\n{ruta}")

    def _dibujar_ala1(self):
        if self.p.pieza == "avion":
            self.sim_art = None
            return self._dibujar_avion("lateral")
        ax = self.v1.nuevo()
        ax.add_patch(Rectangle(
            (0, 0), self.m.recorrido_x, self.m.recorrido_y, fill=False, ls="--", lw=0.8, ec="gray"))
        puntos = [np.array([[0.0, 0.0]])]
        self._rect_bloque(ax, puntos)
        r = self.res
        if r is not None:
            if self.ver_torres.get():
                ax.plot(*r.xy.T, ":", color="#4a7fd0", lw=0.9, label=f"Torre {self.m.eje1}{self.m.eje2}")
                ax.plot(*r.za.T, ":", color="#d05050", lw=0.9, label=f"Torre {self.m.eje3}{self.m.eje4}")
                puntos += [r.xy, r.za]
            if self.p.pieza == "fuselaje":
                etq = {"raiz": f"Cara torre 1 ({r.nombres['raiz']})", "punta": f"Cara torre 2 ({r.nombres['punta']})"}
            else:
                nombre = {s: Path(getattr(self.ala, f"perfil_{s}")).stem for s in ("raiz", "punta")}
                etq = {"raiz": f"Raíz ({nombre['raiz']})", "punta": f"Punta ({nombre['punta']})"}
            ax.plot(*r.raiz.T, "-", color=COLORES[1][0], lw=1.2, label=etq["raiz"])
            ax.plot(*r.punta.T, "-", color=COLORES[1][1], lw=1.2, label=etq["punta"])
            puntos += [r.raiz, r.punta]
            ax.plot(0, 0, "ko", ms=4)
            ax.annotate("cero", (0, 0), textcoords="offset points", xytext=(4, -12), fontsize=8)
            ax.legend(loc="upper right", fontsize=8)
            # elementos de la simulación (ocultos hasta que se reproduce)
            hecho = dict(color="#ff7f0e", lw=2.4, alpha=0.8, visible=False, zorder=4)
            hilo = dict(marker="o", ms=7, ls="none", visible=False, zorder=5)
            self.sim_art = {
                "hecho_r": ax.plot([], [], **hecho)[0],
                "hecho_t": ax.plot([], [], **hecho)[0],
                "raiz": ax.plot([], [], color=COLORES[1][0], mec="k", **hilo)[0],
                "punta": ax.plot([], [], color=COLORES[1][1], mec="k", **hilo)[0],
                "xy": ax.plot([], [], marker="s", ms=5, color="#4a7fd0", ls="none", visible=False)[0],
                "za": ax.plot([], [], marker="s", ms=5, color="#d05050", ls="none", visible=False)[0],
                "texto": ax.text(0.01, 0.98, "", transform=ax.transAxes, va="top", fontsize=10,
                                 family="monospace", visible=False,
                                 bbox=dict(fc="white", ec="#999", alpha=0.85)),
            }
        else:
            self.sim_art = None
            puntos.append(np.array([[self.m.recorrido_x, self.m.recorrido_y]]))
        self.v1.mostrar(puntos)

    def _dibujar_planta(self):
        if self.p.pieza == "avion":
            return self._dibujar_avion("planta")
        if self.p.pieza == "fuselaje":
            return self._dibujar_fuselaje()
        ax = self.v3.nuevo()
        pl = self.planta
        if pl is None:
            self.v3.mostrar([np.array([[0.0, 0.0], [100.0, 100.0]])])
            return
        c = self.p.corte
        sr, st, W = pl.s_raiz, pl.s_punta, pl.W
        d, Lb = c.dist_torre_bloque, self.pc.ala.envergadura
        x_max = max(pl.raiz[1], pl.punta[1], c.bloque_largo) + 20
        puntos = [np.array([[0.0, 0.0], [W, x_max]])]
        # torres
        for s, nombre in ((0, f"Torre {self.m.eje1}{self.m.eje2}"), (W, f"Torre {self.m.eje3}{self.m.eje4}")):
            ax.plot([s, s], [0, x_max], "-", color="#777", lw=5, alpha=0.5, solid_capstyle="butt")
            ax.annotate(nombre, (s, x_max), textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8)
        # bloque
        if c.bloque_largo > 0:
            ax.add_patch(Rectangle((d, 0), Lb, c.bloque_largo, fc="#f3ecd0", ec="#b8a060", lw=0.8,
                                   zorder=0, label="Bloque"))
        # prolongación del hilo hasta las torres (por dónde van BA y BS)
        for k in (0, 1):
            xr, xt = pl.raiz[k], pl.punta[k]
            x0 = xr + (xt - xr) * (0 - sr) / (st - sr)
            x1 = xr + (xt - xr) * (W - sr) / (st - sr)
            ax.plot([0, W], [x0, x1], ":", color="#999", lw=0.8)
        # panel
        panel = [(sr, pl.raiz[0]), (sr, pl.raiz[1]), (st, pl.punta[1]), (st, pl.punta[0])]
        ax.add_patch(Polygon(panel, closed=True, fc="#cfe0f5", ec=COLORES[1][0], lw=1.4, zorder=2,
                             label="Panel"))
        ax.plot([sr, st], [pl.raiz[1], pl.punta[1]], "-", color=COLORES[1][0], lw=2.5, zorder=3)
        q = [(sr, pl.raiz[1] - 0.25 * (pl.raiz[1] - pl.raiz[0])), (st, pl.punta[1] - 0.25 * (pl.punta[1] - pl.punta[0]))]
        ax.plot(*zip(*q), "-.", color="#5577aa", lw=0.8, zorder=3, label="25% de la cuerda")
        for s, (bs, ba), et in ((sr, pl.raiz, "Raíz"), (st, pl.punta, "Punta")):
            ax.annotate(f"{et}\n{ba - bs:.0f}", (s, (ba + bs) / 2), textcoords="offset points",
                        xytext=(-6 if s == min(sr, st) else 6, 0), ha="right" if s == min(sr, st) else "left",
                        va="center", fontsize=8, color=COLORES[1][0])
        ax.annotate("BA", ((sr + st) / 2, (pl.raiz[1] + pl.punta[1]) / 2), textcoords="offset points",
                    xytext=(0, 5), ha="center", fontsize=8)
        ax.annotate("BS", ((sr + st) / 2, (pl.raiz[0] + pl.punta[0]) / 2), textcoords="offset points",
                    xytext=(0, -12), ha="center", fontsize=8)
        # alerón
        if pl.bisagra:
            xr, xt = pl.bisagra
            ax.add_patch(Polygon([(sr, pl.raiz[0]), (sr, xr), (st, xt), (st, pl.punta[0])], closed=True,
                                 fc="none", ec="#c07000", hatch="///", lw=0, zorder=3, label="Alerón"))
            ax.plot([sr, st], [xr, xt], "--", color="#c07000", lw=1.6, zorder=4)
            ax.annotate("bisagra", ((sr + st) / 2, (xr + xt) / 2), textcoords="offset points",
                        xytext=(0, -11), ha="center", fontsize=8, color="#c07000", zorder=5)
        # varillas
        for nombre, xr, xt in pl.varillas:
            ax.plot([sr, st], [xr, xt], "-", color="#2a2a2a", lw=1.6, zorder=4)
            if nombre:
                ax.annotate(nombre, ((sr + st) / 2, (xr + xt) / 2), textcoords="offset points", xytext=(0, 3),
                            ha="center", fontsize=8, zorder=5)
        ax.text(0.01, 0.01, "\n".join(pl.datos), transform=ax.transAxes, va="bottom", fontsize=8,
                bbox=dict(fc="white", ec="#bbb", alpha=0.9))
        ax.set_xlabel("mm a lo largo del hilo (desde la torre 1)")
        ax.set_ylabel(f"{self.m.eje1} (mm)")
        ax.legend(loc="upper right", fontsize=8)
        self.v3.mostrar(puntos)

    # ---------- simulación ----------
    def _sim_posicion(self, t):
        """Índice del último punto alcanzado y posiciones (raíz, punta, xy, za) en el instante t."""
        r, info = self.res, self.info
        L, S = np.asarray(info["llegada"]), np.asarray(info["salida"])
        n = len(L)
        i = int(np.clip(np.searchsorted(S, t, side="right") - 1, 0, n - 2))
        if t <= L[i + 1]:
            den = L[i + 1] - S[i]
            f = min(1.0, max(0.0, (t - S[i]) / den)) if den > 0 else 1.0
        else:
            i, f = i + 1, 0.0
        j = min(i + 1, n - 1)
        pos = [arr[i] + f * (arr[j] - arr[i]) for arr in (r.raiz, r.punta, r.xy, r.za)]
        return i, pos

    def _sim_dibujar(self):
        if self.sim_art is None or self.info is None:
            return
        total = self.info["tiempo_min"]
        t = min(self.sim_t, total)
        i, (pr, pt, pxy, pza) = self._sim_posicion(t)
        a = self.sim_art
        a["hecho_r"].set_data(*np.vstack([self.res.raiz[:i + 1], pr]).T)
        a["hecho_t"].set_data(*np.vstack([self.res.punta[:i + 1], pt]).T)
        a["raiz"].set_data([pr[0]], [pr[1]])
        a["punta"].set_data([pt[0]], [pt[1]])
        a["xy"].set_data([pxy[0]], [pxy[1]])
        a["za"].set_data([pza[0]], [pza[1]])
        torres = self.ver_torres.get()
        for k, art in a.items():
            art.set_visible(torres if k in ("xy", "za") else True)
        tipo = self.res.tipos[min(i + 1, len(self.res.tipos) - 1)]
        a["texto"].set_text(f"{int(t)}:{int(t % 1 * 60):02d} / {int(total)}:{int(total % 1 * 60):02d}  {tipo}")
        self.sim_texto.set(f"{100 * t / total:5.1f} %" if total > 0 else "")
        self.v1.canvas.draw_idle()

    def sim_play(self):
        if self.res is None or self.info is None:
            return
        if self._sim:  # está reproduciendo: pausa
            self.after_cancel(self._sim)
            self._sim = None
            self.boton_play.configure(text="▶ Reproducir")
            return
        if self.en_ala2():
            self.pestanas.select(0)
        self.modo_vista.set("corte")
        self._mostrar_vista()
        if self.sim_t >= self.info["tiempo_min"]:
            self.sim_t = 0.0
        self.boton_play.configure(text="⏸ Pausa")
        self._sim_paso()

    def _sim_paso(self):
        total = self.info["tiempo_min"]
        vel = float(self.sim_vel.get().lstrip("x"))
        self.sim_t = min(total, self.sim_t + 0.04 / 60 * vel)
        self.sim_barra.set(self.sim_t / total if total > 0 else 0)
        self._sim_dibujar()
        if self.sim_t >= total:
            self._sim = None
            self.boton_play.configure(text="▶ Reproducir")
        else:
            self._sim = self.after(40, self._sim_paso)

    def _sim_mover_barra(self, f):
        if self.info is None or self._sim:
            return
        self.sim_t = f * self.info["tiempo_min"]
        self._sim_dibujar()

    def sim_parar(self):
        if self._sim:
            self.after_cancel(self._sim)
            self._sim = None
        self.sim_t = 0.0
        if hasattr(self, "boton_play"):
            self.boton_play.configure(text="▶ Reproducir")
            self.sim_barra.set(0.0)
            self.sim_texto.set("")
        if self.sim_art:
            for art in self.sim_art.values():
                art.set_visible(False)
            self.v1.canvas.draw_idle()

    # ---------- deshacer / rehacer ----------
    def _confirmar_pendiente(self):
        if self._tarea:  # hay un cambio escrito que aún no se ha calculado
            self.after_cancel(self._tarea)
            self.recalcular()

    def _restaurar(self, p):
        self.p = p
        self._estado_ok = copy.deepcopy(p)
        self.form.refrescar()
        self.refrescar_varillas()
        self.recalcular()

    def deshacer(self):
        self._confirmar_pendiente()
        if not self._historial:
            self.bell()
            return
        self._rehacer.append(copy.deepcopy(self.p))
        self._restaurar(self._historial.pop())

    def rehacer(self):
        self._confirmar_pendiente()
        if not self._rehacer:
            self.bell()
            return
        self._historial.append(copy.deepcopy(self.p))
        self._restaurar(self._rehacer.pop())

    # ---------- proyectos recientes ----------
    def _leer_recientes(self):
        try:
            return [r for r in json.loads(RECIENTES_JSON.read_text(encoding="utf-8")) if isinstance(r, str)]
        except (OSError, ValueError):
            return []

    def _anadir_reciente(self, ruta):
        ruta = str(Path(ruta).resolve())
        lista = [ruta] + [r for r in self._leer_recientes() if r != ruta]
        try:
            RECIENTES_JSON.write_text(json.dumps(lista[:10], indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        self._menu_recientes()

    def _menu_recientes(self):
        self.menu_recientes.delete(0, "end")
        lista = self._leer_recientes()
        if not lista:
            self.menu_recientes.add_command(label="(ninguno)", state="disabled")
        for i, ruta in enumerate(lista, 1):
            self.menu_recientes.add_command(label=f"{i}. {Path(ruta).name}   ({Path(ruta).parent})",
                                            command=lambda r=ruta: self.abrir(r))

    def _dibujar_bloque(self):
        ax = self.v2.nuevo()
        puntos = [np.array([[0.0, 0.0]])]
        self._rect_bloque(ax, puntos)
        b = self.bloque
        if b is not None:
            t1 = f"{self.m.eje1}{self.m.eje2}"
            t2 = f"{self.m.eje3}{self.m.eje4}"
            for n, caras in b.caras.items():
                col = COLORES[n]
                ax.plot(*caras["A"].T, "-", color=col[0], lw=1.2, label=f"Ala {n} · cara torre {t1}")
                ax.plot(*caras["B"].T, "--", color=col[1], lw=1.0, label=f"Ala {n} · cara torre {t2}")
                puntos += [caras["A"], caras["B"]]
            ax.plot(0, 0, "ko", ms=4)
            ax.annotate("cero ala 1", (0, 0), textcoords="offset points", xytext=(4, -12), fontsize=8)
            if 2 in b.caras:
                L = self.p.corte.bloque_largo
                H = self.p.corte.bloque_alto
                ax.plot(L, H, "ko", ms=4)
                ax.annotate("cero ala 2 (bloque girado)", (L, H), textcoords="offset points",
                            xytext=(-130, 6), fontsize=8)
            ax.legend(loc="upper right", fontsize=8)
        self.v2.mostrar(puntos)

    # ---------- G-code ----------
    def _gcode(self):
        if self.p.pieza == "avion":
            messagebox.showinfo("AeroFoam", "En 'Avión' no hay nada que cortar: elige la pieza en 'Pieza'.")
            return None
        if self.res is None:
            messagebox.showerror("AeroFoam", "Corrige los errores antes de generar el G-code.")
            return None
        if self.p.pieza == "fuselaje":
            return generar(self.res, self.p, self.m, self._nombre_pieza(), self.descripcion)[0]
        return generar(self.res, self.pc, self.m, self._nombre_tramo())[0]

    def _nombre_tramo(self, i=None):
        base = Path(self.ruta).stem if self.ruta else "ala"
        if self.p.pieza in ("estabilizador", "deriva"):
            base += "" if base == "ala" else "_"
            base = (base if base != "ala" else "") + self.p.pieza
        if len(self.tramos) <= 1:
            return base
        if i is None:
            i = self._tramo_idx
        return f"{base}_tramo{i + 1}"

    def exportar_tramos(self):
        if len(self.tramos) <= 1:
            return self.exportar()
        try:
            textos = [generar(calcular(q, self.m), q, self.m, self._nombre_tramo(i))[0]
                      for i, (_, q) in enumerate(self.tramos)]
        except (ErrorGeometria, ValueError) as e:
            messagebox.showerror("AeroFoam", f"No se pudo generar algún tramo:\n{e}")
            return
        base = Path(self.ruta).stem if self.ruta else "ala"
        ruta = filedialog.asksaveasfilename(
            title="Exportar todos los tramos (se añade _tramo1, _tramo2...)", initialfile=base + ".gcode",
            defaultextension=".gcode", filetypes=[("G-code", "*.gcode *.nc *.gc *.tap"), ("Todos", "*.*")])
        if not ruta:
            return
        ruta = Path(ruta)
        hechos = []
        for i, g in enumerate(textos):
            destino = ruta.with_name(f"{ruta.stem}_tramo{i + 1}{ruta.suffix or '.gcode'}")
            destino.write_text(g, encoding="ascii", newline="\n")
            hechos.append(f"{destino.name}   ({self.tramos[i][0]})")
        self.guardar_maquina(silencioso=True)
        messagebox.showinfo("AeroFoam", "G-code guardado en " + str(ruta.parent) + ":\n\n" + "\n".join(hechos))

    def ver_gcode(self):
        g = self._gcode()
        if g is None:
            return
        w = tk.Toplevel(self)
        w.title("G-code")
        w.geometry("600x700")
        t = tk.Text(w, font=("Consolas", 9), wrap="none")
        sb = ttk.Scrollbar(w, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(fill="both", expand=True)
        t.insert("1.0", g)
        t.configure(state="disabled")

    def exportar(self):
        g = self._gcode()
        if g is None:
            return
        nombre = (self._nombre_pieza() if self.p.pieza == "fuselaje" else self._nombre_tramo()) + ".gcode"
        ruta = filedialog.asksaveasfilename(
            title="Exportar G-code", initialfile=nombre, defaultextension=".gcode",
            filetypes=[("G-code", "*.gcode *.nc *.gc *.tap"), ("Todos", "*.*")])
        if ruta:
            Path(ruta).write_text(g, encoding="ascii", newline="\n")
            self.guardar_maquina(silencioso=True)
            messagebox.showinfo("AeroFoam", f"G-code guardado en:\n{ruta}")

    # ---------- perfiles ----------
    SEP = "   —   "

    def _filtrar_perfiles(self, solo=None):
        cat = self.categoria.get()
        for c in ([solo] if solo else self.combos_perfil):
            texto = c["var"].get().lower() if solo else ""
            valores = [f"{n}{self.SEP}{d.get('nombre', n)} · {d.get('descripcion', '')}".rstrip(" ·")
                       for n, d in self.catalogo.items()
                       if (cat == "Todas" or d.get("categoria", "Mis perfiles") == cat)
                       and (texto in n.lower() or texto in d.get("nombre", "").lower()
                            or texto in d.get("descripcion", "").lower())]
            c["widget"].configure(values=valores)

    def _perfil_elegido(self, campo):
        campo["var"].set(campo["var"].get().split(self.SEP)[0])
        campo["widget"].icursor("end")
        campo["widget"].selection_clear()

    def _info_perfiles(self):
        for campo, var in self.info_perfil:
            try:
                nombre, (sup, inf) = obtener_perfil(getattr(campo["obj"](), campo["attr"]))
            except (ValueError, OSError):
                var.set("")
                continue
            d = self.catalogo.get(Path(str(getattr(campo["obj"](), campo["attr"]))).stem, {})
            if "espesor" in d:  # datos del catálogo
                texto = (f"{d['nombre']}  ·  {d['descripcion']}  ·  espesor {d['espesor']:.1f}% al "
                         f"{d['pos_espesor']}%, curvatura {d['curvatura']:.1f}%")
            else:
                x = np.linspace(0, 1, 501)
                e = interpolar(sup, x) - interpolar(inf, x)
                k = int(np.argmax(e))
                texto = f"{nombre}  ·  espesor {e[k] * 100:.1f}% al {x[k] * 100:.0f}%"
            var.set(texto)

    # ---------- ficheros ----------
    def _elegir_perfil(self, campo):
        ruta = filedialog.askopenfilename(title="Elegir perfil", initialdir=DIR_MIS_PERFILES,
                                          filetypes=[("Perfiles", "*.dat *.txt"), ("Todos", "*.*")])
        if ruta:
            ruta = Path(ruta)
            if (ruta.parent.resolve() in (DIR_MIS_PERFILES.resolve(), DIR_CATALOGO.resolve())
                    and ruta.suffix.lower() == ".dat"):
                campo["var"].set(ruta.stem)
                return
            try:
                ruta = ruta.relative_to(DOCUMENTOS)
            except ValueError:
                pass
            campo["var"].set(ruta.as_posix())

    def _titulo(self):
        nombre = Path(self.ruta).name if self.ruta else "sin nombre"
        self.title(f"AeroFoam {__version__} - {nombre}")

    def _cargar(self, p, ruta):
        self.p = p
        self.ruta = ruta
        self.form.refrescar()
        self.refrescar_varillas()
        self._titulo()
        for v in self.vistas:
            v.vista = None
        self._historial.clear()
        self._rehacer.clear()
        self._estado_ok = copy.deepcopy(p)
        self.recalcular()

    def nuevo(self):
        self._cargar(Proyecto(), None)

    def abrir(self, ruta=None):
        if ruta is None:
            ruta = filedialog.askopenfilename(title="Abrir proyecto", initialdir=DIR_PROYECTOS,
                                              filetypes=[("Proyecto AeroFoam", "*.json")])
        if ruta:
            if not Path(ruta).exists():
                messagebox.showerror("AeroFoam", f"Ya no existe:\n{ruta}")
                lista = [r for r in self._leer_recientes() if r != ruta]
                RECIENTES_JSON.write_text(json.dumps(lista, indent=1, ensure_ascii=False), encoding="utf-8")
                self._menu_recientes()
                return
            try:
                self._cargar(cargar_proyecto(ruta), ruta)
                self._anadir_reciente(ruta)
            except Exception as e:
                messagebox.showerror("AeroFoam", f"No se pudo abrir el proyecto:\n{e}")

    def guardar(self):
        if not self.ruta:
            return self.guardar_como()
        guardar_proyecto(self.p, self.ruta)
        self._anadir_reciente(self.ruta)
        self._titulo()

    def guardar_como(self):
        ruta = filedialog.asksaveasfilename(title="Guardar proyecto", initialdir=DIR_PROYECTOS,
                                            defaultextension=".json",
                                            filetypes=[("Proyecto AeroFoam", "*.json")])
        if ruta:
            self.ruta = ruta
            self.guardar()

    def guardar_maquina(self, silencioso=False):
        guardar_maquina(self.m, MAQUINA_JSON)
        if not silencioso:
            messagebox.showinfo("AeroFoam", "Configuración de máquina guardada.")

    def salir(self):
        self.guardar_maquina(silencioso=True)
        self.destroy()


def main():
    preparar()
    App().mainloop()
