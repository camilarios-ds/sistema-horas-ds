from __future__ import annotations

from datetime import date, datetime, time, timedelta
from io import BytesIO
from typing import Iterable

import pandas as pd

REQUIRED_COLUMNS = {"ID de usuario", "Fecha/Hora"}


def leer_fichadas(archivo) -> pd.DataFrame:
    """Lee XLS/XLSX y normaliza las columnas del reloj."""
    nombre = getattr(archivo, "name", "").lower()
    # Algunos relojes generan archivos XLS que internamente son XLSX.
    # Probamos primero detección automática y luego ambos motores.
    ultimo_error = None
    df = None
    for engine in (None, "openpyxl", "xlrd"):
        try:
            if hasattr(archivo, "seek"):
                archivo.seek(0)
            df = pd.read_excel(archivo, engine=engine)
            break
        except Exception as exc:
            ultimo_error = exc
    if df is None:
        raise ValueError(f"No se pudo leer el archivo Excel: {ultimo_error}")
    df.columns = [str(c).strip() for c in df.columns]

    faltantes = REQUIRED_COLUMNS.difference(df.columns)
    if faltantes:
        raise ValueError(
            "Faltan columnas obligatorias: " + ", ".join(sorted(faltantes))
        )

    df = df.copy()
    df["Fecha/Hora"] = pd.to_datetime(df["Fecha/Hora"], errors="coerce")
    df["ID de usuario"] = pd.to_numeric(df["ID de usuario"], errors="coerce")
    df = df.dropna(subset=["ID de usuario", "Fecha/Hora"])
    df["ID de usuario"] = df["ID de usuario"].astype(int)
    return df.sort_values(["ID de usuario", "Fecha/Hora"]).reset_index(drop=True)


def crear_jornadas(df: pd.DataFrame) -> pd.DataFrame:
    """Agrupa primera y última fichada del día por empleado."""
    base = df.copy()
    base["Fecha"] = base["Fecha/Hora"].dt.date

    jornadas = (
        base.groupby(["ID de usuario", "Fecha"], as_index=False)
        .agg(
            Entrada=("Fecha/Hora", "min"),
            Salida=("Fecha/Hora", "max"),
            Fichadas=("Fecha/Hora", "count"),
        )
        .sort_values(["ID de usuario", "Fecha"])
        .reset_index(drop=True)
    )

    jornadas["Observaciones"] = ""
    jornadas.loc[jornadas["Fichadas"] < 2, "Observaciones"] = "Falta entrada o salida"
    jornadas.loc[jornadas["Fichadas"] > 2, "Observaciones"] = "Más de 2 fichadas"
    jornadas.loc[jornadas["Entrada"] == jornadas["Salida"], "Observaciones"] = "Falta entrada o salida"
    return jornadas


def _parse_hora(valor) -> time | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    for formato in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(texto, formato).time()
        except ValueError:
            continue
    raise ValueError(f"Horario inválido: {valor}. Usá HH:MM.")


def _interval_minutes(inicio: datetime, fin: datetime) -> int:
    return max(0, int((fin - inicio).total_seconds() // 60))


def _overlap_minutes(a1: datetime, a2: datetime, b1: datetime, b2: datetime) -> int:
    inicio = max(a1, b1)
    fin = min(a2, b2)
    return _interval_minutes(inicio, fin)


def _nocturnos(inicio: datetime, fin: datetime, desde: time, hasta: time) -> int:
    total = 0
    dia = inicio.date() - timedelta(days=1)
    ultimo = fin.date() + timedelta(days=1)
    while dia <= ultimo:
        if desde > hasta:
            tramo1_i = datetime.combine(dia, desde)
            tramo1_f = datetime.combine(dia + timedelta(days=1), time.min)
            tramo2_i = datetime.combine(dia + timedelta(days=1), time.min)
            tramo2_f = datetime.combine(dia + timedelta(days=1), hasta)
            total += _overlap_minutes(inicio, fin, tramo1_i, tramo1_f)
            total += _overlap_minutes(inicio, fin, tramo2_i, tramo2_f)
        else:
            tramo_i = datetime.combine(dia, desde)
            tramo_f = datetime.combine(dia, hasta)
            total += _overlap_minutes(inicio, fin, tramo_i, tramo_f)
        dia += timedelta(days=1)
    return total


def _minutos_100(inicio: datetime, fin: datetime, feriados: set[date], sabado_desde: time) -> int:
    fecha = inicio.date()
    if fecha in feriados or fecha.weekday() == 6:  # domingo
        return _interval_minutes(inicio, fin)
    if fecha.weekday() == 5:  # sábado
        corte = datetime.combine(fecha, sabado_desde)
        return _overlap_minutes(inicio, fin, corte, datetime.combine(fecha + timedelta(days=1), time.min))
    return 0


def redondear_abajo(minutos: int, bloque: int = 15) -> int:
    if minutos <= 0:
        return 0
    return (minutos // bloque) * bloque


def minutos_a_hhmm(minutos: int | float) -> str:
    if pd.isna(minutos):
        return "00:00"
    minutos = max(0, int(round(float(minutos))))
    return f"{minutos // 60}:{minutos % 60:02d}"


def calcular_jornadas(
    jornadas: pd.DataFrame,
    empleados: pd.DataFrame,
    feriados: Iterable[date],
    jornada_normal_horas: float = 8,
    nocturna_desde: str = "21:00",
    nocturna_hasta: str = "06:00",
    sabado_100_desde: str = "12:00",
    bloque_extra_min: int = 15,
) -> pd.DataFrame:
    """Calcula normales, extras, nocturnas y horas al 100%."""
    resultado = jornadas.copy()
    empleados = empleados.copy()
    empleados.columns = [str(c).strip() for c in empleados.columns]

    if "ID de usuario" not in empleados.columns:
        empleados["ID de usuario"] = pd.Series(dtype="int64")
    if "Nombre" not in empleados.columns:
        empleados["Nombre"] = ""
    if "Horario oficial" not in empleados.columns:
        empleados["Horario oficial"] = ""

    mapa_nombres = empleados.set_index("ID de usuario")["Nombre"].to_dict()
    mapa_horarios = empleados.set_index("ID de usuario")["Horario oficial"].to_dict()

    feriados_set = {pd.Timestamp(f).date() for f in feriados}
    noct_desde = _parse_hora(nocturna_desde) or time(21, 0)
    noct_hasta = _parse_hora(nocturna_hasta) or time(6, 0)
    sabado_desde_t = _parse_hora(sabado_100_desde) or time(12, 0)
    jornada_normal_min = int(round(jornada_normal_horas * 60))

    filas = []
    for _, fila in resultado.iterrows():
        empleado_id = int(fila["ID de usuario"])
        entrada = pd.Timestamp(fila["Entrada"]).to_pydatetime()
        salida = pd.Timestamp(fila["Salida"]).to_pydatetime()
        observacion = str(fila.get("Observaciones", "") or "")

        if salida <= entrada or int(fila.get("Fichadas", 0)) < 2:
            filas.append({
                **fila.to_dict(),
                "Nombre": mapa_nombres.get(empleado_id, f"ID {empleado_id}"),
                "Entrada computable": entrada,
                "Total minutos": 0,
                "Normales min": 0,
                "Extras 50% min": 0,
                "Nocturnas min": 0,
                "100% min": 0,
                "Extra nocturna min": 0,
                "Es feriado": fila["Fecha"] in feriados_set,
            })
            continue

        horario_texto = str(mapa_horarios.get(empleado_id, "") or "").strip()
        horarios_oficiales = []
        if horario_texto:
            for parte in horario_texto.replace(",", "/").split("/"):
                parte = parte.strip()
                if parte:
                    horarios_oficiales.append(_parse_hora(parte))

        entrada_computable = entrada
        horario_oficial = None
        if horarios_oficiales:
            candidatos = [datetime.combine(entrada.date(), h) for h in horarios_oficiales]
            # Elegimos el turno más cercano a la fichada. Permite varios turnos: 05:30/07:30.
            inicio_oficial = min(candidatos, key=lambda d: abs((d - entrada).total_seconds()))
            horario_oficial = inicio_oficial.time()
            # La fichada anticipada no genera tiempo pagable.
            entrada_computable = max(entrada, inicio_oficial)

        total_min = _interval_minutes(entrada_computable, salida)
        min_100 = _minutos_100(entrada_computable, salida, feriados_set, sabado_desde_t)
        min_no_100 = max(0, total_min - min_100)
        normales = min(min_no_100, jornada_normal_min)
        extras_50 = redondear_abajo(max(0, min_no_100 - jornada_normal_min), bloque_extra_min)
        nocturnas = _nocturnos(entrada_computable, salida, noct_desde, noct_hasta)
        min_100 = redondear_abajo(min_100, bloque_extra_min)

        # Extra nocturna: nocturnidad que ocurre después de completar la jornada normal.
        inicio_extra = entrada_computable + timedelta(minutes=jornada_normal_min)
        extra_nocturna = 0
        if salida > inicio_extra:
            extra_nocturna = redondear_abajo(
                _nocturnos(inicio_extra, salida, noct_desde, noct_hasta), bloque_extra_min
            )

        if horario_oficial is not None and entrada < entrada_computable:
            texto = f"Entrada anticipada ignorada hasta {horario_oficial.strftime('%H:%M')}"
            observacion = f"{observacion} | {texto}".strip(" |")

        filas.append({
            **fila.to_dict(),
            "Nombre": mapa_nombres.get(empleado_id, f"ID {empleado_id}"),
            "Entrada computable": entrada_computable,
            "Total minutos": total_min,
            "Normales min": normales,
            "Extras 50% min": extras_50,
            "Nocturnas min": nocturnas,
            "100% min": min_100,
            "Extra nocturna min": extra_nocturna,
            "Es feriado": fila["Fecha"] in feriados_set,
            "Observaciones": observacion,
        })

    calculado = pd.DataFrame(filas)
    for origen, destino in [
        ("Total minutos", "Total hs"),
        ("Normales min", "Normales"),
        ("Extras 50% min", "Extras 50%"),
        ("Nocturnas min", "Nocturnas"),
        ("100% min", "100%"),
        ("Extra nocturna min", "Extra nocturna"),
    ]:
        calculado[destino] = calculado[origen].apply(minutos_a_hhmm)

    columnas = [
        "ID de usuario", "Nombre", "Fecha", "Entrada", "Entrada computable", "Salida",
        "Fichadas", "Total hs", "Normales", "Extras 50%", "Nocturnas", "100%",
        "Extra nocturna", "Es feriado", "Observaciones",
        "Total minutos", "Normales min", "Extras 50% min", "Nocturnas min", "100% min",
        "Extra nocturna min",
    ]
    return calculado[columnas].sort_values(["Nombre", "Fecha"]).reset_index(drop=True)


def crear_resumen(detalle: pd.DataFrame) -> pd.DataFrame:
    resumen = (
        detalle.groupby(["ID de usuario", "Nombre"], as_index=False)
        .agg(
            Días=("Fecha", "count"),
            Normales_min=("Normales min", "sum"),
            Extras_50_min=("Extras 50% min", "sum"),
            Nocturnas_min=("Nocturnas min", "sum"),
            Horas_100_min=("100% min", "sum"),
            Extra_nocturna_min=("Extra nocturna min", "sum"),
            Incidencias=("Observaciones", lambda s: sum(bool(str(v).strip()) for v in s)),
        )
        .sort_values("Nombre")
        .reset_index(drop=True)
    )
    resumen["Normales"] = resumen["Normales_min"].apply(minutos_a_hhmm)
    resumen["Extras 50%"] = resumen["Extras_50_min"].apply(minutos_a_hhmm)
    resumen["Nocturnas"] = resumen["Nocturnas_min"].apply(minutos_a_hhmm)
    resumen["100%"] = resumen["Horas_100_min"].apply(minutos_a_hhmm)
    resumen["Extra nocturna"] = resumen["Extra_nocturna_min"].apply(minutos_a_hhmm)
    return resumen[[
        "ID de usuario", "Nombre", "Días", "Normales", "Extras 50%", "Nocturnas",
        "100%", "Extra nocturna", "Incidencias",
    ]]
