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
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente  # noqa: E402
from clasificador import Clasificador  # noqa: E402
from nivel2 import elegir_tecnico, extraer_pct  # noqa: E402
from motor_audio_foto import describir_foto_consenso, transcribir_con_consenso  # noqa: E402
from supabase_repositorio import RepositorioSupabase  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
API_TELEGRAM = "https://api.telegram.org/bot{token}/{metodo}"
SESSION_FILE = CACHE / "telegram_offset.txt"
REPORTES_BOT = CACHE / "reportes_bot.json"

# Cultivos que reconoce el filtro de preguntas (con sinónimos del habla del campo)
CULTIVOS_POR_MENCION = {
    "maíz": ["maíz", "maiz", "milpa", "elote", "olote"],
    "frijol": ["frijol", "frijolar", "frijolera"],
    "avena": ["avena", "avenita"],
    "haba": ["haba", "habitas", "habita"],
    "papa": ["papa", "papita", "papa blanca"],
    "jitomate": ["jitomate", "jitomatera", "tomate"],
    "limón": ["limón", "limon", "limonero", "cítricos", "citricos"],
    "chile": ["chile"],
    "calabacita": ["calabacita", "calabaza"],
    "trigo": ["trigo"],
    "grano almacenado": ["grano almacenado", "bodega", "almacén", "almacen", "troje"],
}

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
        # Motor del equipo: clasificación por reglas + multimedia (STT/visión)
        self._clf = Clasificador(con_ia=True)
        self._repo = RepositorioSupabase()  # no-ops si no hay llaves de Supabase
        self.sesiones: dict[str, dict] = {}  # chat_id -> estado del flujo de reporte
        self._reportes_bot = self._leer_reportes_bot()
        self._cache_equipo: dict | None = None
        self._cache_equipo_ts: float = 0.0

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

    # ------------------------------------------- "Añadir reporte" (flujo)
    def _leer_reportes_bot(self) -> list[dict]:
        return _leer_json("reportes_bot", [])

    def _guardar_reportes_bot(self) -> None:
        try:
            tmp = REPORTES_BOT.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._reportes_bot, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(REPORTES_BOT)
        except OSError as exc:
            print(f"[telegram] no pude guardar reportes_bot.json: {exc}")

    def _nuevo_rid(self) -> str:
        numeros = []
        for r in self._reportes_bot:
            rid = str(r.get("id") or "")
            if rid.startswith("BOT-") and rid[4:].isdigit():
                numeros.append(int(rid[4:]))
        return f"BOT-{(max(numeros) if numeros else 0) + 1:04d}"

    def _descargar_media(self, file_id: str, sufijo: str) -> Path | None:
        if not self.token:
            return None
        r = self._llamar("getFile", {"file_id": file_id})
        if not r or not r.get("ok"):
            return None
        file_path = (r.get("result") or {}).get("file_path")
        if not file_path:
            return None
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        try:
            bytes_data = requests.get(url, timeout=60).content
        except requests.RequestException as exc:
            print(f"[telegram] falló la descarga del archivo: {exc}")
            return None
        ext = Path(file_path).suffix or sufijo
        destino = Path(tempfile.gettempdir()) / f"alerta_{file_id}{ext}"
        destino.write_bytes(bytes_data)
        return destino

    def _extraer_media(self, msg: dict) -> dict | None:
        """Devuelve {tipo, file_id, caption} si el mensaje trae foto/voz/audio/documento."""
        if foto := (msg.get("photo") or []):
            mayor = max(foto, key=lambda f: f.get("file_size") or 0)
            return {"tipo": "foto", "file_id": mayor.get("file_id"),
                    "caption": msg.get("caption") or ""}
        if voz := msg.get("voice"):
            return {"tipo": "voz", "file_id": voz.get("file_id"), "caption": ""}
        if audio := msg.get("audio"):
            return {"tipo": "audio", "file_id": audio.get("file_id"), "caption": ""}
        if doc := msg.get("document"):
            return {"tipo": "documento", "file_id": doc.get("file_id"),
                    "caption": msg.get("caption") or ""}
        return None

    def _cultivo_de_texto(self, texto: str) -> str | None:
        tn = self._clf.normalizar(texto)
        for cultivo, menciones in CULTIVOS_POR_MENCION.items():
            if any(m in tn for m in menciones):
                return cultivo
        return None

    @staticmethod
    def _parcela_de_texto(texto: str) -> str | None:
        m = re.search(r"\bP-\d+\b", texto.upper())
        return m.group(0) if m else None

    def iniciar_reporte(self, chat_id: str) -> None:
        self.sesiones[chat_id] = {"estado": "contenido", "datos": {}}
        self.enviar(chat_id,
                    "📝 <b>Nuevo reporte</b>\n"
                    "Mándame lo que tienes: un <b>mensaje de texto</b>, una <b>foto 📷</b>, "
                    "una <b>nota de voz 🎙️</b> o un <b>archivo 📎</b> (jpg/png/ogg).\n"
                    "Escribe /cancelar para salir.")

    def _pregunta_cultivo(self, chat_id: str, sesion: dict) -> None:
        sesion["estado"] = "q_cultivo"
        self.enviar(chat_id,
                    "📍 <b>Pregunta 1/3 — cultivo.</b>\n"
                    "¿De qué cultivo o parcela es? (ej. maíz, frijol, limón, papa… "
                    "o el código P-000 de tu parcela).\n"
                    "Si no sabes, escribe «no sé».")

    def _pregunta_pct(self, chat_id: str, sesion: dict) -> None:
        sesion["estado"] = "q_pct"
        self.enviar(chat_id,
                    "📏 <b>Pregunta 2/3 — qué tanto.</b>\n"
                    "¿Qué parte de la parcela está afectada? (ej. «la mitad», «30 %», "
                    "«una cuarta parte», «casi todo»)")

    def _pregunta_confirmar(self, chat_id: str, sesion: dict) -> None:
        sesion["estado"] = "q_confirmar"
        self.enviar(chat_id,
                    "🔍 <b>Pregunta 3/3 — confirmación.</b>\n"
                    "Para confirmar que es plaga: ¿ves <b>insectos, manchas, hojas "
                    "comidas o la planta marchita</b>? ¿Desde cuándo lo notas?")

    def _recibir_contenido(self, chat_id: str, msg: dict) -> None:
        """Guarda el contenido (texto/media) del reporte y arranca las preguntas."""
        sesion = self.sesiones.get(chat_id)
        if not sesion:
            self.enviar(chat_id, "Usa /añadir para empezar un reporte.")
            return
        datos = sesion["datos"]
        media = self._extraer_media(msg)

        if media:
            sufijo = ".ogg" if media["tipo"] in ("voz", "audio") else ".jpg"
            archivo = self._descargar_media(media["file_id"], sufijo)
            ext = (Path(archivo.name).suffix.lower() if archivo else "." + sufijo.lstrip("."))
            datos["archivo"] = str(archivo) if archivo else None

            if ext in (".ogg", ".oga", ".mp3", ".wav", ".m4a"):
                datos["tipo"] = "voz"
                self.enviar(chat_id, "🎧 Recibido. Estoy transcribiendo tu audio…")
                try:
                    trans = transcribir_con_consenso(archivo)
                    datos["contenido"] = (trans.get("principal") or trans.get("respaldo") or "").strip()
                except Exception as exc:
                    print(f"[telegram] STT falló: {exc}")
                    datos["contenido"] = (media.get("caption") or "").strip()
                    datos["stt_error"] = str(exc)[:120]
            elif ext in (".jpg", ".jpeg", ".png", ".webp", ""):
                datos["tipo"] = "foto"
                datos["contenido"] = (media.get("caption") or "").strip()
                self.enviar(chat_id, "📷 Recibido. Estoy analizando la foto…")
                try:
                    datos["vision"] = describir_foto_consenso(archivo, "cultivo", "")
                except Exception as exc:
                    print(f"[telegram] visión falló: {exc}")
                    datos["vision"] = None
            else:
                self.enviar(chat_id, "⚠️ Formato no soportado. Envíame jpg/png, ogg o un mensaje de texto.")
                return
        else:
            datos["tipo"] = "texto"
            datos["contenido"] = (msg.get("text") or "").strip()

        if not datos.get("contenido") and not datos.get("vision"):
            self.enviar(chat_id, "⚠️ No entendí el contenido. Mándame texto, foto o nota de voz, o /cancelar.")
            return
        self._pregunta_cultivo(chat_id, sesion)

    def _procesar_respuesta(self, chat_id: str, texto: str) -> None:
        sesion = self.sesiones.get(chat_id)
        if not sesion:
            return
        datos = sesion["datos"]
        estado = sesion["estado"]
        t = texto.strip().lower()

        if estado == "q_cultivo":
            if t in ("no se", "no sé", "no", "no lo se", "no lo sé"):
                datos["cultivo"], datos["parcela_id"] = None, None
            else:
                datos["parcela_id"] = self._parcela_de_texto(texto)
                datos["cultivo"] = (None if datos.get("parcela_id")
                                   else self._cultivo_de_texto(texto))
            self._pregunta_pct(chat_id, sesion)

        elif estado == "q_pct":
            datos["pct"] = extraer_pct(texto)
            self._pregunta_confirmar(chat_id, sesion)

        elif estado == "q_confirmar":
            datos["confirmacion"] = texto.strip()
            self._clasificar_y_guardar(chat_id, sesion)

    def _clasificar_y_guardar(self, chat_id: str, sesion: dict) -> None:
        """Clasifica con el motor del equipo, determina el estado y lo guarda."""
        datos = sesion["datos"]
        try:
            self.enviar(chat_id, "⚖️ Clasificando con el reglamento del reto…")
            parcela_id = datos.get("parcela_id")
            cultivo = (datos.get("cultivo")
                       or self._clf.cultivo_de_parcela(parcela_id)
                       or self._clf.inferir_cultivo(self._clf.normalizar(datos.get("contenido") or "")))
            texto_final = " ".join(x for x in [datos.get("contenido"), datos.get("confirmacion")] if x)

            # decisión de plaga: visión (foto) o texto (reglas)
            es_plaga, plaga, motor = False, None, "texto"
            vision = datos.get("vision") or {}
            res_texto = self._clf.clasificar_texto(texto_final, cultivo)
            if vision.get("plaga") and vision.get("plaga") != "desconocida":
                compat = (not cultivo) or vision["plaga"] in self._clf.cultivares_compatibles(cultivo)
                if compat:
                    es_plaga, plaga, motor = True, vision["plaga"], "vision"
                    if res_texto.get("es_plaga") and res_texto.get("plaga") == vision["plaga"]:
                        motor = "vision+texto"
            if not plaga:
                es_plaga = bool(res_texto.get("es_plaga"))
                plaga = res_texto.get("plaga")
                motor = res_texto.get("motor") or "texto"
            if es_plaga and plaga == "desconocida":
                plaga = "desconocida"

            rid = self._nuevo_rid()
            ahora = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            caso = {"reporte_id": rid, "es_plaga": True if es_plaga else False,
                    "plaga": plaga if es_plaga else None,
                    "seguimiento_de": None,
                    "urgente": False, "_motor": motor}
            pct = datos.get("pct") or 10

            # Nivel 2 (prioridad, semáforo, técnico) si hay parcela y plaga
            respuesta = None
            if es_plaga and plaga and plaga != "desconocida" and parcela_id:
                reporte = {"id": rid, "parcela_id": parcela_id, "recibido": ahora,
                           "texto": texto_final, "tipo": datos.get("tipo")}
                n2 = self._clf.resolver_nivel2(reporte, plaga, {**res_texto, "texto": texto_final, "es_plaga": es_plaga, "plaga": plaga})
                if n2:
                    caso.update({"semaforo": n2["semaforo"], "tecnico_id": n2["tecnico_id"],
                                 "prioridad": n2["prioridad"], "_pct": n2["pct"] if n2.get("pct") else pct})
                # brote con previos + casos propios
                try:
                    brotes = self._clf.brotes_de_casos([caso], {rid: reporte})
                    if rid in brotes:
                        caso["brote"] = brotes[rid]
                except Exception as exc:
                    print(f"[telegram] brote no calculado: {exc}")
            caso["pct"] = int(pct)

            # respaldo: consulta de prioridad/semáforo contra la API (no registra).
            # Solo aplica a reportes del hackathon (R-*); los BOT-* son nuestros.
            if rid.startswith("R-"):
                try:
                    api = ApiCliente()
                    respuesta = api.validar_caso({k: v for k, v in caso.items()
                                                  if k in ("reporte_id", "es_plaga", "plaga",
                                                           "semaforo", "tecnico_id", "prioridad", "brote")})
                except Exception as exc:
                    print(f"[telegram] validación API: {exc}")

            # guardar en la tabla local y en la BD (Supabase si hay llaves)
            registro = {
                "id": rid, "tipo": datos.get("tipo", "texto"), "prod_telegram": chat_id,
                "parcela_id": parcela_id, "cultivo": cultivo, "texto": texto_final,
                "archivo": datos.get("archivo"), "pct": int(pct),
                "recibido": ahora, "es_plaga": es_plaga, "plaga": plaga,
                "semaforo": caso.get("semaforo"), "tecnico_id": caso.get("tecnico_id"),
                "prioridad": caso.get("prioridad"), "brote": caso.get("brote"),
                "motor": motor, "confirmacion": datos.get("confirmacion"),
                "validacion_api": respuesta,
            }
            self._reportes_bot.append(registro)
            self._guardar_reportes_bot()
            try:
                self._repo.guardar_reporte({**registro, "respuesta_a": None})
                self._repo.guardar_caso({"reporte_id": rid, "caso": caso,
                                         "confianza": res_texto.get("confianza"),
                                         "motor": motor, "razon": res_texto.get("razon"),
                                         "injection": False,
                                         "seguimiento_de": None})
            except Exception as exc:
                print(f"[telegram] Supabase no disponible: {exc}")

            linea = (f"📋 <b>Estado del reporte {rid}</b>\n"
                     f"¿Es plaga? <b>{'SÍ 🐛' if es_plaga else 'NO ✓'}</b>\n"
                     f"Plaga: {_html(plaga or '—')}\n"
                     f"Afectación: {int(pct)}% · Cultivo: {_html(cultivo or 'sin dato')}\n")
            if caso.get("semaforo"):
                emoji = {"rojo": "🔴", "naranja": "🟠", "amarillo": "🟡", "verde": "🟢"}.get(caso["semaforo"], "⚪")
                linea += (f"Prioridad: {caso.get('prioridad')}/100 · Semáforo: {emoji} {caso['semaforo']}\n"
                          f"Técnico: {caso.get('tecnico_id') or 'sin disponible'}\n")
            if caso.get("brote") is True:
                linea += "🦠 <b>¡Hay brote activo en la zona!</b>\n"
            linea += "\nGuardado en la tabla local ✓" + (" y en la base de datos (Supabase) ✓" if self._repo.activo else " · (Supabase sin llave: queda local) ")
            self.enviar(chat_id, linea)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.enviar(chat_id, f"⚠️ Fallé al clasificar: {exc}")
        finally:
            self.sesiones.pop(chat_id, None)

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
        """GET /equipo con caché de 20 s (el bot lo consulta mucho)."""
        ahora = time.time()
        if self._cache_equipo is not None and ahora - self._cache_equipo_ts < 20:
            return self._cache_equipo
        try:
            equipo = self.api.get_equipo() or {}
        except Exception:
            equipo = {}
        avance = equipo.get("avance") or {}
        datos = {
            "nombre": equipo.get("nombre") or "7_7",
            "puntos": avance.get("puntos", 0),
            "lugar": avance.get("lugar", "—"),
            "publicados": avance.get("publicados", 0),
            "maximo": avance.get("maximo_posible", 0),
            "errores": avance.get("errores", 0),
        }
        self._cache_equipo = datos
        self._cache_equipo_ts = ahora
        return datos

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
            totales = self._totales()
            return (f"👋 ¡Hola! Soy <b>Agente Sanidad IT GREEN</b>, tu coordinador "
                    f"fitosanitario digital.\n\n"
                    f"📌 Llevamos <b>{totales['reportes']} reportes</b> publicados y "
                    f"<b>{totales['casos']} casos</b> procesados por el equipo "
                    f"(puntos en tabla: {totales['puntos']}).\n\n"
                    f"Puedo ayudarte así:\n"
                    f"  /añadir — registrar un reporte (texto, foto 📷, voz 🎙️, archivo)\n"
                    f"  /estado — puntos, lugar y reportes\n"
                    f"  /urgentes— casos rojo o naranja\n"
                    f"  /brotes  — zonas con brote activo\n"
                    f"  /plagas  — qué plagas nos están reportando\n"
                    f"  /ayuda   — esta lista")
        if t.startswith("/estado"):
            e = self.datos_equipo()
            totales = self._totales()
            return (f"📊 <b>Estado del equipo {_html(e['nombre'])}</b>\n"
                    f"Puntos: <b>{e['puntos']}</b> · Lugar: {e['lugar']}\n"
                    f"Reportes publicados por la API: <b>{e['publicados']}</b>\n"
                    f"Casos procesados por nuestro sistema: <b>{totales['casos']}</b>\n"
                    f"(incluye {totales['via_bot']} registrados desde este bot)\n"
                    f"Máximo posible: {e['maximo']}")
        if t.startswith("/reportes") or t.startswith("/totales"):
            totales = self._totales()
            return (f"🗂️ <b>Reportes</b>\n"
                    f"En la API: {self.datos_equipo()['publicados']}\n"
                    f"Casos procesados: {totales['casos']}\n"
                    f"Vía bot (BT-*): {totales['via_bot']}\n"
                    f"Con plaga: {totales['con_plaga']} · No plaga: {totales['no_plaga']} · "
                    f"Desconocida: {totales['desconocida']}")
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
            return ("🤖 Comandos: /añadir · /estado · /urgentes · /brotes · /plagas · /reportes · /ayuda.\n"
                    "Con /añadir registras un reporte (texto, foto, voz o archivo) y "
                    "te hago 3 preguntas para confirmar plaga y calcular su estado.\n"
                    "También puedes escribirme en lenguaje natural y te respondo "
                    "con los datos del programa.")
        return ""

    def _totales(self) -> dict:
        """Cuenta los reportes de la API + los que ya corrieron por este bot."""
        casos = self.casos_cacheados()
        via_bot = len(self._reportes_bot)
        con_plaga = sum(1 for c in casos if c.get("es_plaga") and c.get("plaga") not in (None, "desconocida"))
        desconocida = sum(1 for c in casos if c.get("es_plaga") and c.get("plaga") == "desconocida")
        no_plaga = sum(1 for c in casos if not c.get("es_plaga"))
        return {"reportes": self.datos_equipo()["publicados"], "casos": len(casos),
                "via_bot": via_bot, "con_plaga": con_plaga, "no_plaga": no_plaga,
                "desconocida": desconocida, "puntos": self.datos_equipo()["puntos"]}

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
            f"Totales del programa: reportes publicados={self.datos_equipo()['publicados']}, "
            f"casos procesados={len(self.casos_cacheados())}\n"
            f"Urgentes: {[(c['reporte_id'], c.get('plaga')) for c in self.urgentes()[:8]]}\n"
            f"Brotes: {[c['reporte_id'] for c in self.con_brote()[:8]]}\n"
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
        if not chat_id or not (texto or msg.get("photo") or msg.get("voice")
                               or msg.get("audio") or msg.get("document")):
            return
        if str(chat_id) != self.chat_id and not os.getenv("TELEGRAM_MODO_DEMO"):
            # Solo responde al coordinador (salvo demostración explícita)
            self.enviar(str(chat_id), "🚫 Solo el coordinador del equipo puede hablar conmigo.")
            return

        cid = str(chat_id)
        sesion = self.sesiones.get(cid)

        # flujo "Añadir reporte": primero el contenido (texto o media)
        if sesion and sesion.get("estado") == "contenido":
            self._recibir_contenido(cid, msg)
            return
        # flujo "Añadir reporte": respuestas a las preguntas filtro
        if sesion and sesion.get("estado") in ("q_cultivo", "q_pct", "q_confirmar"):
            if texto.strip().lower() == "/cancelar":
                self.sesiones.pop(cid, None)
                self.enviar(cid, "Reporte cancelado.")
                return
            self._procesar_respuesta(cid, texto)
            return

        # comandos y chat normal
        if texto:
            if texto.strip().lower() in ("/añadir", "/reporte", "/nuevo reporte"):
                self.iniciar_reporte(cid)
                return
            if texto.strip().lower() == "/cancelar":
                self.sesiones.pop(cid, None)
                self.enviar(cid, "Listo, nada en curso.")
                return
            respuesta = self._comando(cid, texto) or self._responder_ia(texto)
            if respuesta:
                self.enviar(cid, respuesta)
        else:
            # media sin sesión activa
            self.enviar(cid, "¿Es un reporte de plaga? Usa /añadir para empezar el flujo.")
        return

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