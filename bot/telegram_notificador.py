"""
telegram_notificador.py — Avisos al coordinador por Telegram (preparado).

El reto pide avisar los casos con semáforo rojo o naranja, con plaga, parcela
y técnico. Los botones inline (Aprobar / Cambiar técnico / Falsa alarma) ya
están armados para cuando exista el bot del equipo.

Configuración (.env, nunca en el repositorio):
    TELEGRAM_BOT_TOKEN=123456:ABC...
    TELEGRAM_CHAT_ID=-1001234567890      # chat del coordinador
    TELEGRAM_COORDINADOR=@usuario        # opcional, solo informativo

Sin token, el módulo funciona en seco: imprime el mensaje y devuelve False.
Así el resto del sistema puede llamarlo sin romperse.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

API_TELEGRAM = "https://api.telegram.org/bot{token}/{metodo}"
SEMAFORO_EMOJI = {"rojo": "🔴", "naranja": "🟠", "amarillo": "🟡", "verde": "🟢"}
SEMAFORO_TEXTO = {"rojo": "ROJO", "naranja": "NARANJA", "amarillo": "AMARILLO", "verde": "VERDE"}


def configurado() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def _llamar(metodo: str, datos: dict) -> dict | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    try:
        resp = requests.post(API_TELEGRAM.format(token=token, metodo=metodo), json=datos, timeout=20)
        if resp.status_code != 200:
            print(f"[telegram] error {resp.status_code}: {resp.text[:160]}")
            return None
        return resp.json()
    except requests.RequestException as exc:
        print(f"[telegram] sin conexión: {exc}")
        return None


def enviar(texto: str, botones: list[list[dict]] | None = None) -> bool:
    """Envía un mensaje al coordinador. Sin configuración, solo lo imprime."""
    if not configurado():
        print("[telegram seco] " + texto.replace("\n", " | ")[:220])
        return False
    datos = {
        "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if botones:
        datos["reply_markup"] = {"inline_keyboard": botones}
    return _llamar("sendMessage", datos) is not None


def alerta_caso(caso: dict, plaga: dict | None, parcela: dict | None,
                productor: dict | None = None) -> bool:
    """Mensaje enriquecido de un caso rojo/naranja."""
    semaforo = (caso.get("semaforo") or "verde").lower()
    emoji = SEMAFORO_EMOJI.get(semaforo, "⚪")
    plaga_nombre = (plaga or {}).get("nombre") or caso.get("plaga") or "sin identificar"
    parcela_txt = "sin parcela"
    if parcela:
        parcela_txt = (f"{parcela.get('nombre')} ({parcela.get('id')}) · "
                       f"{parcela.get('cultivo')} {parcela.get('etapa')} · "
                       f"{parcela.get('superficie_ha')} ha")

    lineas = [
        f"{emoji} <b>Caso {caso['reporte_id']} — {SEMAFORO_TEXTO.get(semaforo, semaforo.upper())}</b>",
        f"<b>Plaga:</b> {plaga_nombre}",
        f"<b>Parcela:</b> {parcela_txt}",
        f"<b>Prioridad:</b> {caso.get('prioridad', '—')}/100",
        f"<b>Técnico:</b> {caso.get('tecnico_id') or 'sin disponible'}",
    ]
    if productor:
        lineas.append(f"<b>Productor:</b> {productor.get('nombre')} ({productor.get('id')})")
    if caso.get("_pct"):
        lineas.append(f"<b>Afectación:</b> {caso['_pct']}%")

    botones = [[
        {"text": "✅ Aprobar", "callback_data": f"aprobar:{caso['reporte_id']}"},
        {"text": "🔁 Cambiar técnico", "callback_data": f"tecnico:{caso['reporte_id']}"},
        {"text": "🚫 Falsa alarma", "callback_data": f"falsa:{caso['reporte_id']}"},
    ]]
    return enviar("\n".join(lineas), botones)


def resumen_diario(casos: list[dict], titulo: str = "Resumen de casos") -> bool:
    rojos = sum(1 for c in casos if c.get("semaforo") == "rojo")
    naranjas = sum(1 for c in casos if c.get("semaforo") == "naranja")
    return enviar(
        f"<b>{titulo}</b>\nCasos: {len(casos)}\n🔴 Rojos: {rojos}\n🟠 Naranjas: {naranjas}"
    )


def probar() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Telegram configurado:", "sí" if configurado() else "NO (modo seco)")
    caso = {"reporte_id": "R-9999", "semaforo": "naranja", "prioridad": 79,
            "tecnico_id": "T-03", "plaga": "gusano_cogollero", "_pct": 50}
    plaga = {"nombre": "Gusano cogollero", "id": "gusano_cogollero"}
    parcela = {"nombre": "La Tinaja", "id": "P-074", "cultivo": "maíz", "etapa": "V8",
               "superficie_ha": 4.5}
    alerta_caso(caso, plaga, parcela)


if __name__ == "__main__":
    probar()
