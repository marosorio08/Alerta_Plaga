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

import html
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


def _chats_destino() -> list[str]:
    """Lista de chat_ids a los que se envía (coordinador + extra por comas)."""
    chats: list[str] = []
    principal = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if principal:
        chats.append(principal)
    extra = os.getenv("TELEGRAM_CHATS_EXTRA") or ""
    for c in extra.replace(";", ",").split(","):
        c = c.strip()
        if c:
            chats.append(c)
    # dedupe preservando orden
    vistos: set[str] = set()
    unicos = [c for c in chats if not (c in vistos or vistos.add(c))]
    return unicos


def configurado() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and _chats_destino())


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
    """Envía un mensaje a todos los chats configurados. Sin configuración, imprime."""
    destinos = _chats_destino()
    if not configurado():
        print("[telegram seco] " + texto.replace("\n", " | ")[:220])
        return False
    ok = True
    for chat_id in destinos:
        datos = {
            "chat_id": chat_id,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if botones:
            datos["reply_markup"] = {"inline_keyboard": botones}
        if _llamar("sendMessage", datos) is None:
            ok = False
    return ok


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


def _esc(valor) -> str:
    """Escapa texto para el HTML de Telegram (evita errores 400)."""
    return html.escape(str(valor if valor is not None else "—"), quote=False)


def alerta_dudoso(caso: dict, motivo: str, detalle: dict | None = None,
                  refs: list[dict] | None = None) -> bool:
    """Avisa al coordinador cuando el motor no está seguro de un caso.

    Incluye el conteo de brote y las referencias cercanas para que la revisión
    conjunta se haga con datos, no a ciegas. Los botones permiten registrar el
    payload propuesto, forzar ``brote=false`` o retirarlo de la cola.
    """
    rid = str(caso.get("reporte_id", "?"))
    n = caso.get("_brote_n")
    brote = caso.get("brote")
    if brote is True:
        titulo = f"🦠 <b>BROTE {rid} — requiere visto bueno</b>"
    elif caso.get("_brote_dudoso"):
        titulo = f"⚠️ <b>BROTE EN EL LÍMITE {rid} — n=2</b>"
    else:
        titulo = f"⚠️ <b>CASO DUDOSO {rid}</b>"

    lineas = [
        titulo,
        f"<b>Motivo:</b> {_esc(motivo)}",
        f"<b>Es plaga:</b> {'sí' if caso.get('es_plaga') else 'no'}",
        f"<b>Plaga:</b> {_esc(caso.get('plaga'))}",
        f"<b>Semáforo:</b> {_esc(caso.get('semaforo'))}  "
        f"<b>Prioridad:</b> {_esc(caso.get('prioridad'))}",
        f"<b>Técnico:</b> {_esc(caso.get('tecnico_id'))}  "
        f"<b>Brote:</b> {_esc(brote) if brote is not None else 'sin enviar'}",
    ]
    if n is not None:
        lineas.append(f"<b>Casos cercanos (n):</b> {n}")
    if refs:
        lineas.append("<b>Referencias:</b>")
        for ref in refs[:3]:
            actual = " · actual" if ref.get("es_actual") else ""
            lineas.append(
                f"  • {_esc(ref.get('reporte_id'))} · {_esc(ref.get('plaga'))} · "
                f"{_esc(ref.get('distancia_km'))} km · "
                f"{_esc(str(ref.get('recibido') or '')[:16])} "
                f"({_esc(ref.get('fuente') or '?')}, {_esc(ref.get('horas'))} h){actual}"
            )
    if detalle:
        conf = detalle.get("confianza")
        if conf is not None:
            lineas.append(f"<b>Confianza:</b> {round(float(conf), 2)}")
        motor = detalle.get("motor")
        if motor:
            lineas.append(f"<b>Motor:</b> {_esc(motor)}")
        razon = detalle.get("razon")
        if razon:
            lineas.append(f"<b>Razón:</b> {_esc(str(razon)[:160])}")

    if brote is True:
        botones = [[
            {"text": "✅ Registrar brote", "callback_data": f"aprobar:{rid}"},
            {"text": "🚫 Registrar sin brote", "callback_data": f"sin_brote:{rid}"},
        ], [
            {"text": "🚫 Descartar", "callback_data": f"falsa:{rid}"},
        ]]
    elif caso.get("_brote_dudoso"):
        botones = [[
            {"text": "🦠 Marcar brote", "callback_data": f"marcar_brote:{rid}"},
            {"text": "🚫 Registrar sin brote", "callback_data": f"sin_brote:{rid}"},
        ], [
            {"text": "🚫 Descartar", "callback_data": f"falsa:{rid}"},
        ]]
    else:
        botones = [[
            {"text": "✅ Registrarlo", "callback_data": f"aprobar:{rid}"},
            {"text": "🚫 Revisar", "callback_data": f"falsa:{rid}"},
        ]]
    return enviar("\n".join(lineas), botones)


def probar() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print("Telegram configurado:", "sí" if configurado() else "NO (modo seco)")
    caso = {"reporte_id": "R-9999", "semaforo": "naranja", "prioridad": 79,
            "tecnico_id": "T-03", "plaga": "gusano_cogollero", "_pct": 50}
    plaga = {"nombre": "Gusano cogollero", "id": "gusano_cogollero"}
    parcela = {"nombre": "La Tinaja", "id": "P-074", "cultivo": "maíz", "etapa": "V8",
               "superficie_ha": 4.5}
    alerta_caso(caso, plaga, parcela)
    # Prueba del mensaje de brote/dudoso con referencias auditables.
    caso_brote = {"reporte_id": "R-9998", "es_plaga": True, "plaga": "chapulin",
                  "semaforo": "amarillo", "prioridad": 68, "tecnico_id": "T-04",
                  "brote": True, "_brote_n": 3,
                  "_brote_refs": [
                      {"reporte_id": "R-9998", "plaga": "chapulin",
                       "recibido": "2026-10-21T10:00:00-06:00",
                       "distancia_km": 0.0, "es_actual": True},
                      {"reporte_id": "R-9001", "plaga": "chapulin",
                       "recibido": "2026-10-20T09:00:00-06:00",
                       "distancia_km": 1.25, "es_actual": False},
                      {"reporte_id": "R-9002", "plaga": "chapulin",
                       "recibido": "2026-10-19T08:00:00-06:00",
                       "distancia_km": 3.4, "es_actual": False},
                  ]}
    alerta_dudoso(caso_brote, "brote activo (evaluar juntos antes de registrar)",
                  {"confianza": 0.9, "motor": "stt consenso", "razon": "prueba"},
                  refs=caso_brote["_brote_refs"])


if __name__ == "__main__":
    probar()
