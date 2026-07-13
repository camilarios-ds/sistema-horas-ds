from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "configuracion"
EMPLEADOS_PATH = CONFIG_DIR / "empleados.csv"
FERIADOS_PATH = CONFIG_DIR / "feriados.csv"


def cargar_empleados() -> pd.DataFrame:
    if not EMPLEADOS_PATH.exists():
        return pd.DataFrame(columns=["ID de usuario", "Nombre", "Horario oficial"])
    df = pd.read_csv(EMPLEADOS_PATH, dtype={"Horario oficial": str})
    for col in ["ID de usuario", "Nombre", "Horario oficial"]:
        if col not in df.columns:
            df[col] = ""
    df["Horario oficial"] = df["Horario oficial"].fillna("")
    return df[["ID de usuario", "Nombre", "Horario oficial"]]


def guardar_empleados(df: pd.DataFrame) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    limpio = df[["ID de usuario", "Nombre", "Horario oficial"]].copy()
    limpio["ID de usuario"] = pd.to_numeric(limpio["ID de usuario"], errors="coerce")
    limpio = limpio.dropna(subset=["ID de usuario"])
    limpio["ID de usuario"] = limpio["ID de usuario"].astype(int)
    limpio.to_csv(EMPLEADOS_PATH, index=False)


def cargar_feriados() -> pd.DataFrame:
    if not FERIADOS_PATH.exists():
        return pd.DataFrame(columns=["Fecha", "Descripción"])
    df = pd.read_csv(FERIADOS_PATH)
    if "Fecha" not in df.columns:
        df["Fecha"] = ""
    if "Descripción" not in df.columns:
        df["Descripción"] = ""
    return df[["Fecha", "Descripción"]]


def guardar_feriados(df: pd.DataFrame) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    df[["Fecha", "Descripción"]].to_csv(FERIADOS_PATH, index=False)
