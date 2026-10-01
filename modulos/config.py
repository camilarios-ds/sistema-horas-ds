from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

try:
    import streamlit as st
except Exception:  # Permite usar este módulo fuera de Streamlit.
    st = None

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "configuracion"
EMPLEADOS_PATH = CONFIG_DIR / "empleados.csv"
FERIADOS_PATH = CONFIG_DIR / "feriados.csv"


def _secret(name: str, default: str = "") -> str:
    """Lee una configuración desde Streamlit Secrets o variables de entorno."""
    if st is not None:
        try:
            value = st.secrets.get(name, "")
            if value:
                return str(value).strip()
        except Exception:
            pass
    return os.getenv(name, default).strip()


def _github_config() -> tuple[str, str, str]:
    """Devuelve token, repositorio owner/repo y rama para persistencia."""
    token = _secret("GITHUB_TOKEN")
    repo = _secret("GITHUB_REPO")
    branch = _secret("GITHUB_BRANCH", "main") or "main"
    return token, repo, branch


def github_persistencia_activa() -> bool:
    token, repo, _ = _github_config()
    return bool(token and repo)


def _github_request(method: str, path: str, payload: dict | None = None):
    token, repo, branch = _github_config()
    if not token or not repo:
        return None

    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    if method == "GET":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}ref={branch}"

    data = None
    if payload is not None:
        import json
        data = json.dumps(payload).encode("utf-8")

    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Sistema-Horas-DS",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            import json
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub devolvió HTTP {exc.code}: {body[:300]}") from exc
    except URLError as exc:
        raise RuntimeError(f"No se pudo conectar con GitHub: {exc.reason}") from exc


def _guardar_archivo_github(path: str, contenido: bytes, mensaje: str) -> None:
    """Actualiza un archivo del repositorio usando la API de GitHub."""
    token, repo, branch = _github_config()
    if not token or not repo:
        return

    actual = _github_request("GET", path)
    payload = {
        "message": mensaje,
        "content": base64.b64encode(contenido).decode("ascii"),
        "branch": branch,
    }
    if actual and actual.get("sha"):
        payload["sha"] = actual["sha"]

    _github_request("PUT", path, payload)


def _persistir_archivo(path: Path, mensaje: str) -> None:
    """Guarda localmente y, si está configurado, persiste también en GitHub."""
    if github_persistencia_activa():
        relativo = path.relative_to(BASE_DIR).as_posix()
        _guardar_archivo_github(relativo, path.read_bytes(), mensaje)


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
    limpio["Horario oficial"] = limpio["Horario oficial"].fillna("").astype(str)
    limpio.to_csv(EMPLEADOS_PATH, index=False)
    _persistir_archivo(EMPLEADOS_PATH, "Actualizar empleados y horarios desde Sistema Horas DS")


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
    _persistir_archivo(FERIADOS_PATH, "Actualizar feriados desde Sistema Horas DS")
