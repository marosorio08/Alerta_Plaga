"""
interpretar.py — Paso 2 (INTERPRETAR con IA) del Hackathon IT GREEN.

Llama a OpenRouter pidiendo JSON estricto ({"es_plaga", "plaga", "pct"}),
con:
  * response_format json_object cuando el modelo lo soporta,
  * reintentos con backoff (429/5xx/red),
  * validación contra catálogo/cultivo (prompts.normalizar_interpretacion),
  * respaldo determinista: si no hay API, timeout o JSON inválido -> la
    decisión la toman las reglas (clasificador), nunca se arriesga un -1.

El paso DECIDIR (semáforo/técnico/brote) NO se delega a la IA: lo hace el
código (nivel2.py), como exige el reglamento.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

from prompts import construir_prompt, normalizar_interpretacion, parsear_json  # noqa: E402

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELO_POR_DEFECTO = "gpt-4o-mini"
REINTENTOS = 3
ESPERA_BASE = 1.5


class InterpretadorIA:
    """Paso 2: interpreta el mensaje con IA y JSON estricto (con respaldo)."""

    def __init__(self, api_key: str | None = None, modelo: str | None = None,
                 timeout: int = 40) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or ""
        self.modelo = modelo or os.getenv("OPENROUTER_MODELO_IA") or MODELO_POR_DEFECTO
        self.timeout = timeout

    def disponible(self) -> bool:
        return bool(self.api_key)

    def _pedir(self, mensaje: str, cultivo: str | None, candidatas: list[str] | None) -> dict | None:
        prompt = construir_prompt(mensaje, cultivo, candidatas)
        ultimo_error: Exception | None = None
        for intento in range(1, REINTENTOS + 1):
            try:
                resp = requests.post(
                    OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.modelo,
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": (
                                "Eres el agente de interpretación fitosanitaria de "
                                "una junta de sanidad vegetal. Reconoces plagas por "
                                "sus nombres locales y síntomas. Devuelves solo JSON.")},
                            {"role": "user", "content": prompt},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    contenido = resp.json()["choices"][0]["message"]["content"]
                    crudo = parsear_json(contenido)
                    if crudo is None:
                        print("[ia] JSON inválido del modelo, reintento.")
                        time.sleep(ESPERA_BASE * intento)
                        continue
                    return crudo
                if resp.status_code in (429, 500, 502, 503, 504):
                    ultimo_error = RuntimeError(f"HTTP {resp.status_code}")
                    time.sleep(ESPERA_BASE * intento * 2)
                    continue
                print(f"[ia] error {resp.status_code}: {resp.text[:160]}")
                return None
            except requests.RequestException as exc:
                ultimo_error = exc
                time.sleep(ESPERA_BASE * intento)
        print(f"[ia] agotados los reintentos: {ultimo_error}")
        return None

    def interpretar(self, texto: str, cultivo: str | None = None,
                    candidatas: list[str] | None = None) -> dict | None:
        """Devuelve {'es_plaga', 'plaga', 'pct', 'confianza'} o None."""
        if not self.disponible() or not texto:
            return None
        crudo = self._pedir(texto, cultivo, candidatas)
        if crudo is None:
            return None
        normal = normalizar_interpretacion(crudo, candidatas, cultivo)
        if normal is None:
            return None
        normal["confianza"] = 0.85 if normal.get("plaga") != "desconocida" else 0.5
        normal["motor"] = "ia_texto"
        return normal

    def interpretar_con_fallback(self, texto: str, cultivo: str | None,
                                 candidatas: list[str] | None, reglas_fn):
        """IA primero; si no hay IA, error o JSON inválido -> reglas deterministas
        (el respaldo nunca devuelve None: es la decisión segura del reto)."""
        resultado = self.interpretar(texto, cultivo, candidatas)
        if resultado is None:
            return reglas_fn()
        return resultado