"""
bot_telegram.py — Agente del bot de Telegram del equipo 7_7 (Alerta Plaga).

Es el "coordinador digital" de la junta de sanidad vegetal. El coordinador real
(integrante del equipo) conversa con este bot y recibe los casos rojo/naranja y
los brotes con botones para aprobarlos, cambiar el técnico o marcarlos como
falsa alarma.

Cómo se enlaza con el programa:
  * Lee los casos que ya calculó el listener (cache/casos_propuestos.json,
    reportes.json, cache/visitas.json) y la API central (GET /equipo).
  * Usa las mismas funciones del programa para actuar: POST /avisos (folio,
    asignación, respuesta, brote, cuarentenaria, escalamiento).
  * Para el chat libre usa un LLM (OpenRouter) con el SYSTEM_PROMPT de abajo,
    que define la personalidad y las funciones a las que tiene acceso.

Uso:
    python bot/bot_telegram.py            # long-polling para siempre
    python bot/bot_telegram.py --una-vez  # una pasada (para probar)
    python bot/bot_telegram.py --seco     # no tocar la API de avisos
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente  # noqa: E402
from nivel2 import elegir_tecnico  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
API_TELEGRAM = "https://api.telegram.org/bot{token}/{metodo}"
SESSION_FILE = CACHE / "telegram_offset.txt"

# ---------------------------------------------------------------------------
# SYSTEM PROMPT / personalidad del agente
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "Eres «Agente Sanidad IT GREEN», el ayudante fitosanitario oficial de la "
    "Junta Local de Sanidad Vegetal de Texcoco (@alerta_plaga_eq02_bot). "
    "Hablas con el coordinador del equipo, con tono profesional, cercano y "
    "directo, en español de México. Conoces el reglamento del reto Alerta "
    "Plaga: prioridad (severidad + superficie + etapa), semáforo (rojo ≥85, "
    "naranja ≥70, amarillo ≥40, verde <40), técnico por especialidad y "
    "proximidad, y brote (3+ casos de la misma plaga a <5 km en 7 días).\n\n"
    "Funciones con datos reales de las que dispones en cada respuesta:\n"
    "  /estado   → equipo, puntos, lugar, reportes publicados, máx. posible\n"
    "  /urgentes → casos con semáforo rojo o naranja\n"
    "  /brotes   → casos marcados como brote\n"
    "  /plagas   → plagas del catálogo y cuántos casos tiene cada una\n"
    "Los números se calculan con el código del equipo, nunca inventes datos. "
    "Si no sabes algo, sugiere revisar el dashboard público. "
    "Responde breve (máx. 300 palabras) y usa emojis con moderación."
)


def _leer_json(nombre: str, defecto):
    archivo = CACHE / f"{nombre}.json"
    if not archivo.exists():
        return defecto
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return defecto


def _html(texto: str) -> str:
    """Escapa texto para parse_mode=HTML (evita romper el mensaje)."""
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class BotTelegram:
    def __init__(self, api: ApiCliente | None = None, seco: bool = False) -> None:
        self.api = api or ApiCliente()
        self.seco = seco
        self.token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
        self.chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        self.offset = self._cargar_offset()

    # ---------------------------------------------------------- Telegram API
    def _llamar(self, metodo: str, datos: dict, timeout: int = 25) -> dict | None:
        if not self.token:
            return None
        try:
            resp = requests.post(API_TELEGRAM.format(token=self.token, metodo=metodo),
                                 json=datos, timeout=timeout)
            if resp.status_code != 200:
                print(f"[telegram] {metodo} {resp.status_code}: {resp.text[:160]}")
                return None
            return resp.json()
        except requests.RequestException as exc:
            print(f"[telegram] sin conexión ({metodo}): {exc}")
            return None

    def enviar(self, chat_id: str, texto: str, botones: list | None = None) -> bool:
        datos = {"chat_id": chat_id, "text": texto[:4000],
                 "parse_mode": "HTML", "disable_web_page_preview": True}
        if botones:
            datos["reply_markup"] = {"inline_keyboard": botones}
        return self._llamar("sendMessage", datos) is not None

    def responder_callback(self, callback_id: str, texto: str) -> None:
        self._llamar("answerCallbackQuery", {"callback_query_id": callback_id,
                                             "text": texto[:200]})

    def _cargar_offset(self) -> int:
        try:
            return int(SESSION_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0

    def _guardar_offset(self, offset: int) -> None:
        try:
            SESSION_FILE.write_text(str(offset), encoding="utf-8")
        except OSError:
            pass

    # --------------------------------------------------- funciones del equipo
    def datos_equipo(self) -> dict:
        try:
            equipo = self.api.get_equipo() or {}
        except Exception:
            equipo = {}
        avance = equipo.get("avance") or {}
        return {
            "nombre": equipo.get("nombre") or "7_7",
            "puntos": avance.get("puntos", 0),
            "lugar": avance.get("lugar", "—"),
            "publicados": avance.get("publicados", 0),
            "maximo": avance.get("maximo_posible", 0),
            "errores": avance.get("errores", 0),
        }

    def casos_cacheados(self) -> list[dict]:
        return _leer_json("casos_propuestos", [])

    def urgentes(self) -> list[dict]:
        return [c for c in self.casos_cacheados()
                if c.get("semaforo") in ("rojo", "naranja")]

    def con_brote(self) -> list[dict]:
        return [c for c in self.casos_cacheados() if c.get("brote") is True]

    def conteo_plagas(self) -> dict[str, int]:
        conteo: dict[str, int] = {}
        for c in self.casos_cacheados():
            plaga = c.get("plaga")
            if c.get("es_plaga") and plaga and plaga != "desconocida":
                conteo[plaga] = conteo.get(plaga, 0) + 1
        return dict(sorted(conteo.items(), key=lambda kv: -kv[1]))

    # ------------------------------------------------------------ comandos
    def _comando(self, chat_id: str, texto: str) -> str:
        t = (texto or "").strip().lower()
        if t.startswith("/start") or t in ("hola", "buenas", "ayuda básica"):
            return ("👋 ¡Hola! Soy <b>Agente Sanidad IT GREEN</b>, tu coordinador "
                    "fitosanitario digital.\n\n"
                    "Puedo decirte cómo vamos en la campaña de sanidad vegetal:\n"
                    "  /estado  — puntos, lugar y reportes\n"
                    "  /urgentes— casos rojo o naranja\n"
                    "  /brotes  — zonas con brote activo\n"
                    "  /plagas  — qué plagas nos están reportando\n"
                    "  /ayuda   — esta lista")
        if t.startswith("/estado"):
            e = self.datos_equipo()
            return (f"📊 <b>Estado del equipo {_html(e['nombre'])}</b>\n"
                    f"Puntos: <b>{e['puntos']}</b> · Lugar: {e['lugar']}\n"
                    f"Reportes publicados: {e['publicados']} · Máximo posible: {e['maximo']}")
        if t.startswith("/urgentes"):
            urgs = self.urgentes()
            if not urgs:
                return "✅ No hay casos rojo/naranja pendientes."
            lineas = [f"🚨 <b>{len(urgs)} casos rojo/naranja</b>:"]
            for c in urgs[:10]:
                sem = {"rojo": "🔴", "naranja": "🟠"}.get(c.get("semaforo"), "🟠")
                lineas.append(f"  {sem} {c['reporte_id']} · {c.get('plaga')} · "
                              f"Téc: {c.get('tecnico_id') or '—'}")
            return "\n".join(lineas)
        if t.startswith("/brotes"):
            bs = self.con_brote()
            if not bs:
                return "🌱 No hay brotes activos en este momento."
            lineas = [f"🦠 <b>{len(bs)} casos con brote</b>:"]
            for c in bs[:10]:
                lineas.append(f"  • {c['reporte_id']} · {c.get('plaga')}")
            return "\n".join(lineas)
        if t.startswith("/plagas"):
            conteo = self.conteo_plagas()
            if not conteo:
                return "No hay plagas identificadas todavía."
            lineas = ["🐛 <b>Casos por plaga:</b>"]
            for plaga, n in conteo.items():
                lineas.append(f"  • {_html(plaga)}: {n}")
            return "\n".join(lineas)
        if t.startswith("/ayuda") or t in ("ayuda", "que haces", "qué haces", "que puedes hacer"):
            return ("🤖 Comandos: /estado · /urgentes · /brotes · /plagas · /ayuda.\n"
                    "También puedes escribirme en lenguaje natural y te respondo "
                    "con los datos del programa.")
        return ""

    # ------------------------------------------------------ chat libre (LLM)
    def _responder_ia(self, texto: str) -> str:
        """Respuesta en lenguaje natural usando la personalidad del bot."""
        clave = os.getenv("OPENROUTER_API_KEY")
        if not clave:
            return ("No tengo la IA conectada en este entorno, pero estos son "
                    "los comandos que sí funcionan: /estado · /urgentes · "
                    "/brotes · /plagas · /ayuda")
        contexto = (
            f"Equipo: {self.datos_equipo()}\n"
            f"Urgentes: {[(c['reporte_id'], c.get('plaga')) for c in self.urgentes()[:5]]}\n"
            f"Brotes: {[c['reporte_id'] for c in self.con_brote()[:5]]}\n"
            f"Plagas: {self.conteo_plagas()}"
        )
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {clave}"},
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0.3,
                    "max_tokens": 400,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "system", "content": f"Datos actuales:\n{contexto}"},
                        {"role": "user", "content": texto},
                    ],
                },
                timeout=40,
            )
            if resp.status_code != 200:
                return ("No pude consultar la IA ahora ("
                        f"{resp.status_code}). Usa /estado, /urgentes o /brotes.")
            contenido = resp.json()["choices"][0]["message"]["content"]
            return _html(contenido)[:3800]
        except Exception as exc:
            return f"Ups, error conversando: {exc}"

    # -------------------------------------------------------- botones (avisos)
    def aprobar(self, reporte_id: str) -> str:
        """✅ Aprobar: entrega el folio al productor (POST /avisos tipo folio)."""
        reporte = next((r for r in _leer_json("reportes", [])
                        if r.get("id") == reporte_id), None)
        para = [reporte.get("productor_id")] if reporte and reporte.get("productor_id") else []
        if self.seco:
            print(f"  [seco] aviso folio a {para} para {reporte_id}")
            return f"✅ {reporte_id} aprobado (folio listo)"
        if not para:
            return f"⚠️ No encontré al productor de {reporte_id}; no se envió folio."
        try:
            self.api.post("avisos", {
                "reporte_id": reporte_id, "tipo": "folio", "para": para,
                "mensaje": (f"Su reporte {reporte_id} fue revisado y aprobado por "
                            "la junta. Su folio es " + reporte_id + ". "
                            "El técnico asignado lo contactará.")})
            return f"✅ {reporte_id} aprobado · folio enviado al productor"
        except Exception as exc:
            return f"⚠️ No se pudo enviar el folio: {exc}"

    def cambiar_tecnico(self, reporte_id: str) -> str:
        """🔁 Cambiar técnico: elige al siguiente candidato válido y avisa."""
        caso = next((c for c in self.casos_cacheados()
                     if c.get("reporte_id") == reporte_id), None)
        if not caso:
            return f"⚠️ Caso {reporte_id} no encontrado en la caché."
        plaga_id = caso.get("plaga")
        plaga = next((p for p in _leer_json("plagas", [])
                      if p.get("id") == plaga_id), None)
        parcela = _leer_json("parcelas", {}).get(
            next((r.get("parcela_id") for r in _leer_json("reportes", [])
                  if r.get("id") == reporte_id), ""), None)
        if not plaga or not parcela:
            return f"⚠️ Faltan datos de plaga/parcela para {reporte_id}."
        candidatos = [
            t for t in self.api.get_tecnicos()
            if t.get("especialidad") == plaga.get("especialidad")
            and t.get("id") != caso.get("tecnico_id")
        ]
        nuevo = elegir_tecnico([{**t, "carga": 0} for t in candidatos], plaga, parcela)
        if not nuevo:
            return f"⚠️ No hay otro técnico disponible para {reporte_id}."
        if self.seco:
            print(f"  [seco] aviso asignacion a {nuevo} para {reporte_id}")
            return f"🔁 {reporte_id}: técnico recomendado {nuevo}"
        try:
            self.api.post("avisos", {
                "reporte_id": reporte_id, "tipo": "asignacion", "para": [nuevo],
                "mensaje": (f"Le reasignaron el caso {reporte_id} "
                            f"({plaga.get('nombre')}, parcela {parcela.get('id')})." )})
            return f"🔁 {reporte_id}: técnico cambiado a {nuevo}"
        except Exception as exc:
            return f"⚠️ No se pudo reasignar: {exc}"

    def falsa_alarma(self, reporte_id: str) -> str:
        """🚫 Falsa alarma: avisa al productor que no parece plaga."""
        reporte = next((r for r in _leer_json("reportes", [])
                        if r.get("id") == reporte_id), None)
        para = [reporte.get("productor_id")] if reporte and reporte.get("productor_id") else []
        if self.seco:
            print(f"  [seco] aviso respuesta a {para} para {reporte_id}")
            return f"🚫 {reporte_id} marcado como falsa alarma"
        try:
            self.api.post("avisos", {
                "reporte_id": reporte_id, "tipo": "respuesta", "para": para or ["coordinador"],
                "mensaje": ("Revisamos su reporte y, por ahora, no parece tratarse "
                            "de una plaga. Si cambia, mándenos otra foto o mensaje.")})
            return f"🚫 {reporte_id} marcado como falsa alarma"
        except Exception as exc:
            return f"⚠️ No se pudo registrar: {exc}"

    # ------------------------------------------------------------- updates
    def manejar(self, update: dict) -> None:
        if cb := update.get("callback_query"):
            data = cb.get("data") or ""
            accion, _, rid = data.partition(":")
            if accion == "aprobar":
                texto = self.aprobar(rid)
            elif accion == "tecnico":
                texto = self.cambiar_tecnico(rid)
            elif accion == "falsa":
                texto = self.falsa_alarma(rid)
            else:
                texto = "Acción no reconocida."
            chat = (cb.get("message") or {}).get("chat") or {}
            if chat and chat.get("id"):
                self.enviar(str(chat["id"]), texto)
            self.responder_callback(cb.get("id", ""), texto.replace("✅", "").replace("🚫", ""))
            return

        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        texto = msg.get("text") or ""
        if not chat_id or not texto:
            return
        if str(chat_id) != self.chat_id and not os.getenv("TELEGRAM_MODO_DEMO"):
            # Solo responde al coordinador (salvo demostración explícita)
            self.enviar(str(chat_id), "🚫 Solo el coordinador del equipo puede hablar conmigo.")
            return
        respuesta = self._comando(chat_id, texto) or self._responder_ia(texto)
        if respuesta:
            self.enviar(str(chat_id), respuesta)

    def ciclo(self) -> int:
        if not self.token:
            print("[telegram] sin TELEGRAM_BOT_TOKEN; nada que hacer.")
            return 0
        datos = {"timeout": 25, "offset": self.offset}
        resp = self._llamar("getUpdates", datos, timeout=35)
        if not resp or not resp.get("ok"):
            return 0
        updates = resp.get("result") or []
        for u in updates:
            self.offset = max(self.offset, (u.get("update_id") or 0) + 1)
            self.manejar(u)
        if updates:
            self._guardar_offset(self.offset)
        return len(updates)

    def correr(self, una_vez: bool = False) -> None:
        print(f"[telegram] bot activo | seco={self.seco} | coordinador={self.chat_id}")
        while True:
            try:
                n = self.ciclo()
                if n:
                    print(f"[telegram] {n} actualización(es) procesada(s)")
            except KeyboardInterrupt:
                print("\n[telegram] detenido por el usuario")
                break
            except Exception as exc:
                print(f"[telegram] error en ciclo: {exc}")
                time.sleep(5)
            if una_vez:
                break
            time.sleep(2)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Agente del bot de Telegram (Alerta Plaga)")
    parser.add_argument("--una-vez", action="store_true", help="Una sola pasada")
    parser.add_argument("--seco", action="store_true", help="No tocar la API (aviso seco)")
    args = parser.parse_args()
    bot = BotTelegram(seco=args.seco)
    bot.correr(una_vez=args.una_vez)


if __name__ == "__main__":
    main()