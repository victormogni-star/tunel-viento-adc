"""
kyaserv_cz100_mapper.py
========================
Mapeo físico (datasheet-based) para:
    Celda de carga : KYASERV CZ-100  (100 kg, 3.00 mV/V)
    ADC            : ADS1256 24-bit  (PGA=64, Vref=2.5V, Vexc=5V)
    Aplicación     : Túnel de viento

Fuente de la fórmula (datasheet):
    Peso = (V_leído / (V_exc × Sensibilidad)) × Capacidad_máx

No requiere pesas de referencia: la escala viene de los parámetros físicos.
La tara (offset de cero) sí se mide en campo para compensar flexión
estructural, temperatura, etc.

Cableado CZ-100:
    Rojo   → Exc+  (5V)
    Negro  → Exc-  (GND)
    Verde  → Sig+  (AIN0)
    Blanco → Sig-  (AIN1)
"""


class KyaservCZ100Mapper:
    """
    Convierte lecturas crudas del ADS1256 a kilogramos.

    Modo de uso típico
    ------------------
    mapper = KyaservCZ100Mapper()
    mapper.set_tara(ads.read())   # con estructura vacía
    loop:
        kg = mapper.read_kg(ads.read())
    """

    # ------------------------------------------------------------------
    # Parámetros físicos fijos (del datasheet KYASERV CZ-100)
    # ------------------------------------------------------------------
    SENSIBILIDAD_MV_V   = 3.00      # mV/V
    V_EXC               = 5.0       # V  (tensión de excitación)
    CAPACIDAD_KG        = 100.0     # kg (fondo de escala de la celda)

    # ------------------------------------------------------------------
    # Parámetros del ADS1256
    # ------------------------------------------------------------------
    PGA                 = 64        # ganancia del amplificador interno
    V_REF               = 2.5       # V  (tensión de referencia del ADC)
    BITS                = 24        # resolución

    def __init__(
        self,
        max_kg: float = 100.0,
        min_kg: float = 0.0,
        overrange_pct: float = 0.05,
    ):
        """
        Parámetros
        ----------
        max_kg : float
            Límite superior aceptable (default = capacidad de la celda).
        min_kg : float
            Límite inferior (0 kg normalmente; negativo si hay compresión).
        overrange_pct : float
            Porcentaje de tolerancia extra antes de marcar como inválido.
        """
        self.max_kg      = max_kg
        self.min_kg      = min_kg
        self.overrange_pct = overrange_pct

        self._raw_tara: float = 0.0   # offset de cero medido en campo

        # --- Derivados calculados una sola vez ---

        # Señal máxima que entrega la celda a plena carga
        #   V_señal_max = V_exc × Sensibilidad = 5.0 × 3.00mV/V = 15.00 mV
        self.v_señal_max_mv = self.V_EXC * self.SENSIBILIDAD_MV_V

        # Voltaje máximo en la entrada diferencial del ADS1256 con PGA=64
        #   V_in_max = Vref / PGA = 2.5 / 64 ≈ 39.0625 mV  (por rama)
        #   Diferencial: ±Vref/PGA → rango efectivo = 2×Vref/PGA = 78.125 mV
        self.v_in_max_mv = (2 * self.V_REF / self.PGA) * 1000  # en mV

        # Counts totales del ADC en modo unipolar positivo
        #   ADS1256 en diferencial: 0 a 2²⁴-1 = 16,777,215
        self.counts_max = (2 ** self.BITS) - 1

        # Escala: mV por count
        #   = V_in_max_mv / counts_max
        self.mv_por_count = self.v_in_max_mv / self.counts_max

        # Escala directa: kg por count  (sin pasar por voltios en runtime)
        #   kg/count = (mv_por_count / v_señal_max_mv) × CAPACIDAD_KG
        self.kg_por_count = (
            self.mv_por_count / self.v_señal_max_mv
        ) * self.CAPACIDAD_KG

        # Resolución teórica (coincide con el datasheet: ≈ 0.000012 kg)
        self.resolucion_kg = self.kg_por_count

        self._print_parametros()

    # ------------------------------------------------------------------
    # Tara / cero
    # ------------------------------------------------------------------

    def set_tara(self, raw_reading: int) -> None:
        """
        Registra la lectura actual como punto de cero (tara).

        Llamar con la estructura vacía, sin carga, en condiciones normales
        de operación (temperatura de trabajo, flujo de aire apagado, etc.).

        Parámetros
        ----------
        raw_reading : int
            Valor crudo del ADS1256 en el punto de tara.
        """
        self._raw_tara = float(raw_reading)
        v_tara = self._raw_a_mv(raw_reading)
        print(
            f"[CZ100] Tara registrada:\n"
            f"  raw   = {raw_reading}\n"
            f"  voltaje equivalente = {v_tara:.4f} mV"
        )

    def get_tara_raw(self) -> float:
        """Devuelve el raw de tara guardado (útil para guardar en archivo)."""
        return self._raw_tara

    def load_tara_raw(self, raw_tara: float) -> None:
        """Restaura una tara guardada previamente (sin volver a medir)."""
        self._raw_tara = float(raw_tara)
        print(f"[CZ100] Tara restaurada: raw = {raw_tara}")

    # ------------------------------------------------------------------
    # Conversión principal
    # ------------------------------------------------------------------

    def raw_to_kg(self, raw_reading: int) -> float:
        """
        Convierte un valor crudo del ADC a kilogramos.

        Fórmula (datasheet):
            V = raw × mv_por_count
            Peso = (V / (V_exc × Sensibilidad)) × Capacidad
                 = (raw - raw_tara) × kg_por_count

        Parámetros
        ----------
        raw_reading : int
            Lectura directa del ADS1256 (entero sin signo 0…16,777,215).

        Retorna
        -------
        float  – peso en kg (puede ser negativo si hay tensión de signo opuesto).
        """
        return (float(raw_reading) - self._raw_tara) * self.kg_por_count

    def read_kg(
        self,
        raw_reading: int,
        clamp: bool = True,
        raise_on_overrange: bool = False,
    ) -> dict:
        """
        Convierte raw → kg con metadatos de validación.

        Retorna
        -------
        dict:
            kg          : float | None  – peso calculado (None si buffer incompleto)
            raw         : int           – lectura cruda
            voltaje_mv  : float         – voltaje diferencial equivalente en mV
            clamped     : bool          – True si se aplicó límite
            overrange   : bool          – True si supera rango + tolerancia
            valid       : bool          – False si la lectura es sospechosa
        """
        kg_calc = self.raw_to_kg(raw_reading)
        v_mv    = self._raw_a_mv(raw_reading)

        tolerancia = (self.max_kg - self.min_kg) * self.overrange_pct
        over_max = kg_calc > self.max_kg + tolerancia
        under_min = kg_calc < self.min_kg - tolerancia
        overrange = over_max or under_min

        if overrange and raise_on_overrange:
            raise ValueError(
                f"Lectura fuera de rango: {kg_calc:.4f} kg "
                f"(límites: {self.min_kg} – {self.max_kg} kg)"
            )

        kg_out = kg_calc
        clamped = False
        if clamp:
            kg_clamped = max(self.min_kg, min(self.max_kg, kg_calc))
            clamped = kg_clamped != kg_calc
            kg_out = kg_clamped

        return {
            "kg":         round(kg_out,  4),
            "raw":        raw_reading,
            "voltaje_mv": round(v_mv,    4),
            "clamped":    clamped,
            "overrange":  overrange,
            "valid":      not overrange,
        }

    # ------------------------------------------------------------------
    # Promediado por ventana deslizante
    # ------------------------------------------------------------------

    def __init_buffer(self, n: int):
        if not hasattr(self, "_buf") or self._buf_size != n:
            self._buf: list[float] = []
            self._buf_size = n

    def read_kg_averaged(
        self,
        raw_reading: int,
        n_samples: int = 8,
        **kwargs,
    ) -> dict:
        """
        Promedio de ventana deslizante sobre n_samples lecturas.

        Retorna kg=None mientras el buffer no esté lleno.
        """
        self.__init_buffer(n_samples)
        result = self.read_kg(raw_reading, **kwargs)

        self._buf.append(result["kg"] if not result["overrange"] else None)
        self._buf = [v for v in self._buf if v is not None][-n_samples:]

        if len(self._buf) < n_samples:
            result["kg"] = None
            result["valid"] = False
        else:
            result["kg"] = round(sum(self._buf) / len(self._buf), 4)

        return result

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _raw_a_mv(self, raw: int) -> float:
        """Convierte raw a voltaje diferencial en mV."""
        return float(raw) * self.mv_por_count

    def _print_parametros(self) -> None:
        print(
            f"\n{'='*52}\n"
            f"  KYASERV CZ-100  ×  ADS1256\n"
            f"{'='*52}\n"
            f"  Sensibilidad     : {self.SENSIBILIDAD_MV_V} mV/V\n"
            f"  V excitación     : {self.V_EXC} V\n"
            f"  Señal máx celda  : {self.v_señal_max_mv:.2f} mV\n"
            f"  PGA              : {self.PGA}\n"
            f"  Vref             : {self.V_REF} V\n"
            f"  Rango ADC        : ±{self.v_in_max_mv/2:.4f} mV  "
            f"(diferencial con PGA={self.PGA})\n"
            f"  Counts máx       : {self.counts_max:,}\n"
            f"  mV / count       : {self.mv_por_count:.8f}\n"
            f"  kg / count       : {self.kg_por_count:.8f}\n"
            f"  Resolución       : {self.resolucion_kg*1000:.4f} g/bit\n"
            f"{'='*52}\n"
        )

    def __repr__(self) -> str:
        return (
            f"KyaservCZ100Mapper("
            f"tara_raw={self._raw_tara:.0f}, "
            f"escala={self.kg_por_count:.8f} kg/count, "
            f"rango={self.min_kg}–{self.max_kg} kg)"
        )


# ----------------------------------------------------------------------
# Verificación contra la tabla del datasheet
# ----------------------------------------------------------------------

def verificar_contra_datasheet():
    """
    Compara los valores calculados por el mapper contra la tabla del PDF.
    Diferencias deben ser < 0.01 kg (error de redondeo del documento).
    """
    tabla_datasheet = [
        # (raw_decimal,  kg_esperado)
        (        0,   0.000),
        (  349_525,  10.851),
        (  699_050,  21.701),
        (1_048_575,  32.552),
        (1_398_101,  43.403),
        (1_747_626,  54.253),
        (2_097_151,  65.104),
        (2_446_677,  75.955),
        (2_796_202,  86.806),
        (3_145_727,  97.656),
    ]

    mapper = KyaservCZ100Mapper()
    mapper.set_tara(0)   # tabla del datasheet asume tara en raw=0

    print(f"\n{'Raw':>12}  {'Datasheet':>10}  {'Calculado':>10}  {'Error':>8}")
    print("-" * 48)
    max_error = 0.0
    for raw, kg_ref in tabla_datasheet:
        kg_calc = mapper.raw_to_kg(raw)
        error   = abs(kg_calc - kg_ref)
        max_error = max(max_error, error)
        ok = "✓" if error < 0.01 else "✗"
        print(f"{raw:>12,}  {kg_ref:>10.3f}  {kg_calc:>10.4f}  {error:>7.4f} {ok}")

    print(f"\nError máximo: {max_error:.4f} kg  "
          f"({'OK — coincide con tabla' if max_error < 0.01 else 'REVISAR'})")


# ----------------------------------------------------------------------
# Demo de loop de lectura (sin hardware)
# ----------------------------------------------------------------------

def demo_loop():
    import random

    mapper = KyaservCZ100Mapper()

    # Tara simulada: estructura genera ~500 counts de offset
    RAW_TARA = 500
    mapper.set_tara(RAW_TARA)

    # Simulamos una carga de ~50 kg con algo de ruido
    RAW_50KG_IDEAL = RAW_TARA + round(50.0 / mapper.kg_por_count)

    print("\nLoop de lectura simulado (n_samples=4):")
    print(f"{'#':>4}  {'raw':>12}  {'kg':>8}  {'mV':>8}  {'estado'}")
    print("-" * 52)
    for i in range(12):
        ruido = random.randint(-500, 500)
        raw = RAW_50KG_IDEAL + ruido
        r = mapper.read_kg_averaged(raw, n_samples=4)
        kg_str = f"{r['kg']:.3f}" if r["kg"] is not None else "..."
        estado = "válido" if r["valid"] else "acumulando" if r["kg"] is None else "OVERRANGE"
        print(f"{i+1:>4}  {raw:>12,}  {kg_str:>8}  {r['voltaje_mv']:>7.2f}  {estado}")


if __name__ == "__main__":
    verificar_contra_datasheet()
    print()
    demo_loop()
