"""
api_cliente.py — Cliente HTTP de la API Central del Hackathon IT GREEN.

Encapsula todas las llamadas a https://itg.tailf75570.ts.net con el
encabezado obligatorio `X-Equipo-Token`, reintentos automáticos y
manejo de errores centralizado.

Uso básico:
    from api_cliente import ApiCliente
    api = ApiCliente()
    plagas = api.get_plagas()          # catálogo con 10 plagas
    reportes = api.get_reportes()      # reportes publicados
    val = api.validar_caso(caso_json)  # POST /casos/validar (no puntúa)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass


class ApiCliente:
    """Cliente con reintentos (3) y timeout configurable."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: int = 25,
        reintentos: int = 3,
    ) -> None:
        self.base_url = (base_url or os.getenv("API_BASE_URL")).rstrip("/")
        self.token = token or os.getenv("EQUIPO_TOKEN")
        self.timeout = timeout
        self.reintentos = reintentos
        if not self.token:
            raise ValueError("Falta EQUIPO_TOKEN (en .env o en el constructor).")
        self.sesion = requests.Session()
        self.sesion.headers.update(
            {
                "X-Equipo-Token": self.token,
                "Content-Type": "application/json",
            }
        )

    # ---------- núcleo HTTP ----------

    def _pedir(self, metodo: str, ruta: str, **kwargs) -> dict | list | None:
        """Ejecuta la petición con reintentos y backoff."""
        url = f"{self.base_url}/{ruta.lstrip('/')}"
        ultimo_error: Exception | None = None
        for intento in range(1, self.reintentos + 1):
            try:
                resp = self.sesion.request(metodo, url, timeout=self.timeout, **kwargs)
                if resp.status_code == 204:
                    return None
                datos = resp.json()
                # La API responde con {"error": ...} en errores; lo propagamos
                if resp.status_code >= 400:
                    raise ApiError(resp.status_code, ruta, datos)
                return datos
            except (requests.RequestException, json.JSONDecodeError) as exc:
                ultimo_error = exc
                espera = 1.5 * intento
                time.sleep(espera)
        raise ApiError(0, ruta, f"fallo de red tras {self.reintentos} intentos: {ultimo_error}")

    def get(self, ruta: str, parametros: dict | None = None) -> dict | list | None:
        return self._pedir("GET", ruta, params=parametros)

    def post(self, ruta: str, cuerpo: dict) -> dict | list:
        return self._pedir("POST", ruta, json=cuerpo)

    def patch(self, ruta: str, cuerpo: dict) -> dict | list:
        return self._pedir("PATCH", ruta, json=cuerpo)

    # ---------- catálogos ----------

    def get_plagas(self) -> list:
        return self.get("plagas") or []

    def get_parcelas(self) -> list:
        return self.get("parcelas") or []

    def get_productores(self) -> list:
        return self.get("productores") or []

    def get_tecnicos(self) -> list:
        return self.get("tecnicos") or []

    def get_reportes(self) -> list:
        return self.get("reportes") or []

    def get_casos_previos(self) -> list:
        """Casos de la semana anterior con su respuesta correcta."""
        return self.get("casos-previos") or []

    def get_visitas(self) -> list:
        """Visitas registradas por los técnicos (para seguimientos y plazos)."""
        return self.get("visitas") or []

    def get_equipo(self) -> dict:
        return self.get("equipo") or {}

    def get_estado(self) -> dict:
        """Estado en vivo de la competencia (puntos, avance, lugar)."""
        return self.get_equipo().get("avance") or {}

    # ---------- casos ----------

    def validar_caso(self, caso: dict) -> dict:
        """POST /casos/validar — NO puntúa, para probar antes de enviar."""
        return self.post("casos/validar", caso)

    def registrar_caso(self, caso: dict) -> dict:
        """POST /casos — el envío REAL, una sola oportunidad por reporte_id."""
        return self.post("casos", caso)


class ApiError(Exception):
    """Error de la API o de red."""

    def __init__(self, status: int, ruta: str, detalle) -> None:
        self.status = status
        self.ruta = ruta
        self.detalle = detalle
        super().__init__(f"API {status} en {ruta}: {detalle}")
