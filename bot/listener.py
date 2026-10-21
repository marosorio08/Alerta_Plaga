"""
listener.py — Vigila la API y clasifica los reportes nuevos en cuanto llegan.

Diseño pensado para el "reporte en vivo" del viernes y para que nada se rompa
si los organizadores cambian el catálogo o agregan objetivos:

  * Consulta GET /reportes?desde=... cada N segundos y deduplica por id.
  * Clasifica con el motor completo (texto, STT con consenso, visión con
    consenso, cruce por cultivo, seguimientos y urgencia por catálogo).
  * Valida el formato con POST /casos/validar (no registra ni puntúa).
  * Mantiene cache/casos_propuestos.json al día para el dashboard.
  * Refresca los catálogos cada X minutos: si agregan plagas, cultivos o
    severidades, el motor los toma sin tocar código.
  * Por defecto NO registra nada (POST /casos). Para eso hace falta --enviar
    de forma explícita.

Uso:
    python bot/listener.py                    # vigila para siempre (no registra)
    python bot/listener.py --una-vez          # una pasada y sale
    python bot/listener.py --intervalo 20     # cada 20 s (por defecto 20)
    python bot/listener.py --enviar           # registra los nuevos (irreversible)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente, ApiError  # noqa: E402
from clasificador import Clasificador, caso_para_api, resultados_a_casos  # noqa: E402
from extras import Extras  # noqa: E402
from supabase_repositorio import RepositorioSupabase  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
ESTADO = CACHE / "listener_estado.json"
# El dashboard lee este archivo. En el servidor se apunta a ~/app/cache para que
# el agente y la web compartan los mismos casos (variable CASOS_SALIDA en .env).
CASOS_TODOS = Path(os.getenv("CASOS_SALIDA") or (CACHE / "casos_propuestos.json"))
BITACORA = CACHE / "listener_bitacora.jsonl"    # historial de decisiones
# Casos dudosos: se revisan con el coordinador antes de registrarlos.
PENDIENTES_REVISION = CACHE / "revision_pendiente.json"
CONFIANZA_DUDOSA = float(os.getenv("CONFIANZA_DUDOSA", "0.55"))


def ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cargar_json(archivo: Path, defecto):
    if not archivo.exists():
        return defecto
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[{ahora()}] aviso: {archivo.name} corrupto, se reinicia")
        return defecto


def guardar_json(archivo: Path, datos) -> None:
    temporal = archivo.with_suffix(archivo.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(archivo)  # escritura atómica: el dashboard nunca lee a medias


class Listener:
    def __init__(self, intervalo: int = 20, refresco_min: int = 10, enviar: bool = False,
                 extras: bool = False, preguntas: bool = False, avisos_reales: bool = False,
                 telegram: bool = False, vigilante: bool = False) -> None:
        self.api = ApiCliente()
        self.clf = Clasificador(self.api, con_ia=True)
        self.intervalo = intervalo
        self.refresco = refresco_min * 60
        self.enviar = enviar
        self.preguntas = preguntas
        self.telegram = telegram
        self.vigilante = vigilante
        self.repo = RepositorioSupabase()
        self.extras = Extras(self.api, seco=not avisos_reales, repo=self.repo) if extras else None
        self.productores = {p["id"]: p for p in self.clf.api.get_productores()} if extras else {}
        self.estado = cargar_json(ESTADO, {"procesados": [], "enviados": [], "iniciado": ahora()})
        self.estado.setdefault("brotes_avisados", [])
        # Respuestas ya fusionadas con su reporte original. Permite migrar
        # estados viejos en los que la respuesta se procesó con id equivocado.
        self.estado.setdefault("respuestas_aplicadas", [])
        self.casos = {c["reporte_id"]: c for c in cargar_json(CASOS_TODOS, [])}
        self._parkeados: set[str] = {
            str(p.get("reporte_id"))
            for p in cargar_json(PENDIENTES_REVISION, [])
            if p.get("reporte_id")
        }
        self.reportes_actuales: dict[str, dict] = {
            r["id"]: r for r in cargar_json(RAIZ / "cache" / "reportes.json", [])
        }
        # El clasificador usa estas referencias para la ventana de 24 h y el
        # brote; se actualizan en cada ciclo con los reportes frescos.
        self.clf.reportes_actuales = self.reportes_actuales
        self.clf.casos_actuales = self.casos
        self._reportes_ids_cache: list[str] = []
        self.ultimo_refresco = time.time()
        self.nuevos_total = 0
        print(f"[{ahora()}] Supabase: {'conectado' if self.repo.activo else 'no configurado (solo caché local)'}")

    # ---------- clasificación ----------

    def _marcar_procesado(self, rid: str | None) -> None:
        if rid and rid not in self.estado["procesados"]:
            self.estado["procesados"].append(rid)

    def _marcar_respuesta_aplicada(self, rid: str | None) -> None:
        if rid and rid not in self.estado["respuestas_aplicadas"]:
            self.estado["respuestas_aplicadas"].append(rid)

    def _reporte_por_id(self, rid: str | None) -> dict | None:
        if not rid:
            return None
        if rid in self.reportes_actuales:
            return self.reportes_actuales[rid]
        for reporte in cargar_json(RAIZ / "cache" / "reportes.json", []):
            if reporte.get("id") == rid:
                return reporte
        return None

    def _cachear_reportes(self, reportes: list[dict]) -> None:
        """Mantiene cache/reportes.json al día para las herramientas externas."""
        ids = [r["id"] for r in reportes]
        if ids == self._reportes_ids_cache:
            return
        try:
            guardar_json(RAIZ / "cache" / "reportes.json", reportes)
            self._reportes_ids_cache = ids
        except Exception as exc:
            print(f"[{ahora()}] no se pudo actualizar cache/reportes.json: {exc}")

    def _reconstruir_enviados(self, reportes: list[dict]) -> None:
        """Recrea en memoria los casos ya enviados que falten en la caché.

        Sin esto, si `casos_propuestos.json` se pierde o el listener arranca
        tarde, los casos enviados no cuentan como referencia para los brotes
        de los mensajes siguientes. No reenvía nada: solo reconstruye el
        historial local.
        """
        enviados = set(self.estado["enviados"])
        if not enviados:
            return
        faltan = [
            r for r in reportes
            if r.get("id") in enviados
            and not r.get("respuesta_a")
            and r["id"] not in self.casos
        ]
        if not faltan:
            return
        faltan.sort(key=lambda r: (str(r.get("recibido") or ""), str(r.get("id") or "")))
        for reporte in faltan:
            detalle = self.procesar(reporte)
            caso = detalle.get("caso", {k: detalle.get(k) for k in ("reporte_id", "es_plaga", "plaga", "urgente")})
            if caso and caso.get("reporte_id"):
                self.casos[caso["reporte_id"]] = caso
                self._marcar_procesado(caso["reporte_id"])
        print(f"[{ahora()}] reconstruidos {len(faltan)} caso(s) ya enviados para el historial de brote")

    @staticmethod
    def _fusionar_respuesta(padre: dict, respuesta: dict) -> dict:
        """Combina el mensaje original con la respuesta del productor.

        El resultado se clasifica con el ``id`` del padre: la API exige que
        una respuesta a una pregunta se registre con el folio original, no
        con el id del mensaje de respuesta.
        """
        fusionado = dict(padre)
        texto = " ".join(
            x for x in (padre.get("texto"), respuesta.get("texto")) if x
        ).strip()
        if texto:
            fusionado["texto"] = texto
            if padre.get("foto_url"):
                # Mantener la foto permite la fusión visión + texto del padre.
                fusionado["tipo"] = "foto"
                fusionado["audio_url"] = None
            elif respuesta.get("foto_url"):
                fusionado["tipo"] = "foto"
                fusionado["foto_url"] = respuesta["foto_url"]
                fusionado["audio_url"] = None
            else:
                # Para voz o texto, la respuesta escrita manda y evita volver
                # a transcribir un audio que ya se había procesado.
                fusionado["tipo"] = "texto"
                fusionado["audio_url"] = None
                fusionado["foto_url"] = None
        else:
            for clave in ("audio_url", "foto_url"):
                if respuesta.get(clave):
                    fusionado[clave] = respuesta[clave]
            if respuesta.get("tipo"):
                fusionado["tipo"] = respuesta["tipo"]
        fusionado["respuesta_a"] = None
        fusionado["id"] = padre["id"]
        return fusionado

    def procesar(self, reporte: dict) -> dict:
        try:
            self.repo.guardar_reporte(reporte)
        except Exception as exc:
            print(f"[{ahora()}] aviso Supabase (reporte {reporte.get('id')}): {exc}")

        es_respuesta = bool(reporte.get("respuesta_a"))
        padre = self._reporte_por_id(reporte.get("respuesta_a")) if es_respuesta else None
        if es_respuesta and not padre:
            print(f"[{ahora()}] aviso: respuesta {reporte.get('id')} sin padre "
                  f"{reporte.get('respuesta_a')}; se procesa como reporte suelto")
        entrada = padre or reporte
        para_clasificar = self._fusionar_respuesta(padre, reporte) if padre else reporte
        if es_respuesta and padre:
            # La respuesta aporta datos nuevos: el padre sale de la cola de
            # dudosos para registrarse/complementarse con la información nueva.
            self._parkeados.discard(str(padre.get("id")))

        try:
            res = self.clf.clasificar_reporte(para_clasificar)
            caso = resultados_a_casos([para_clasificar], self.clf)[0]
        except Exception as exc:  # un reporte raro nunca tumba el listener
            print(f"[{ahora()}] error clasificando {reporte.get('id')}: {exc}")
            traceback.print_exc()
            return {"reporte_id": entrada.get("id"), "es_plaga": True,
                    "plaga": "desconocida", "urgente": False, "error": str(exc)}

        detalle = {
            "reporte_id": entrada.get("id"),
            "entrada_id": reporte.get("id"),
            "respuesta_id": reporte.get("id") if es_respuesta else None,
            "complemento": es_respuesta,
            "tipo": entrada.get("tipo"),
            "parcela_id": entrada.get("parcela_id"),
            "cultivo": self.clf.cultivo_de_parcela(entrada.get("parcela_id")),
            "recibido": entrada.get("recibido"),
            "procesado": ahora(),
            "caso": caso,
            "motor": res.get("motor"),
            "confianza": res.get("confianza"),
            "razon": res.get("razon"),
            "injection": res.get("injection"),
            "texto": (res.get("texto") or entrada.get("texto") or "")[:280],
            "seguimiento_de": res.get("seguimiento_de"),
        }
        with BITACORA.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(detalle, ensure_ascii=False) + "\n")
        try:
            self.repo.guardar_caso(detalle)
        except Exception as exc:
            print(f"[{ahora()}] aviso Supabase (caso {detalle.get('reporte_id')}): {exc}")
        self._marcar_procesado(reporte.get("id"))
        if es_respuesta:
            self._marcar_respuesta_aplicada(reporte.get("id"))
        return detalle

    # ---------- ciclo ----------

    def ciclo(self) -> int:
        try:
            reportes = self.api.get_reportes()
        except ApiError as exc:
            print(f"[{ahora()}] API no responde: {exc}")
            return 0

        self.reportes_actuales = {r["id"]: r for r in reportes}
        # Migración: si una respuesta se procesó con la versión vieja (y por
        # tanto no está en respuestas_aplicadas), se vuelve a procesar para
        # registrar/complementar a su padre con el id original.
        aplicadas = set(self.estado["respuestas_aplicadas"])
        for reporte in reportes:
            if reporte.get("respuesta_a"):
                # Un caso viejo pudo haberse creado con el id de la respuesta;
                # ese id nunca debe competir con el del reporte original.
                self.casos.pop(reporte["id"], None)
                if reporte["id"] not in aplicadas and reporte["id"] in self.estado["procesados"]:
                    self.estado["procesados"].remove(reporte["id"])

        # Contexto fresco para la regla de seguimiento de 24 h y el brote.
        self.clf.reportes_actuales = self.reportes_actuales
        self.clf.casos_actuales = self.casos
        self._cachear_reportes(reportes)
        # Reconstruir casos ya enviados que falten en la caché local, para que
        # cuenten en el historial de brote aunque no se reenvíen.
        self._reconstruir_enviados(reportes)

        procesados = set(self.estado["procesados"])
        pendientes = [r for r in reportes if r["id"] not in procesados]
        pendientes.sort(key=lambda r: (str(r.get("recibido") or ""), str(r.get("id") or "")))
        if not pendientes:
            # Sin reportes nuevos igual se refresca el brote en la caché
            # compartida y se registran los que hayan quedado pendientes.
            self._recalcular_brotes(self.reportes_actuales)
            self._reconciliar(reportes)
            self._guardar()
            return 0

        # FASE 1 — clasificar y guardar TODOS los pendientes (sin registrar).
        # El brote es una regla GLOBAL (previos + todos los casos propios):
        # si registráramos aquí con `resultados_a_casos([reporte], ...)` el
        # caso vería solo sus propios datos y daría brote=False aunque haya
        # 3 casos cercanos (regresión real R-2070). Por eso se registra al
        # final, cuando el conjunto completo ya está recalculado.
        #
        # Las respuestas (`respuesta_a`) no abren un caso propio: se fusionan
        # con el reporte original y se registran/complementan con su id.
        acumulados: dict[str, tuple[dict, dict, dict]] = {}  # rid -> (reporte, detalle, caso)
        for reporte in pendientes:
            if reporte["id"] in set(self.estado["procesados"]):
                continue
            detalle = self.procesar(reporte)
            caso = detalle.get("caso", {k: detalle.get(k) for k in ("reporte_id", "es_plaga", "plaga", "urgente")})
            if not caso or not caso.get("reporte_id"):
                continue
            self.casos[caso["reporte_id"]] = caso
            self._marcar_procesado(caso["reporte_id"])
            self.nuevos_total += 1
            destino = self.reportes_actuales.get(caso["reporte_id"], reporte)
            acumulados[caso["reporte_id"]] = (destino, detalle, caso)

            marca = "URGENTE" if caso.get("urgente") else ("plaga" if caso["es_plaga"] else "no-plaga")
            conf = detalle.get("confianza") or 0
            nivel2 = ""
            if caso.get("semaforo"):
                nivel2 = f" sem={caso['semaforo']} tec={caso.get('tecnico_id')} pri={caso.get('prioridad')}"
            print(f"[{ahora()}] {caso['reporte_id']} {destino.get('tipo', '?'):<5} "
                  f"{marca:<8} plaga={caso.get('plaga')} conf={round(float(conf), 2)}{nivel2} "
                  f"| {str(detalle.get('texto', ''))[:60]}")

        # FASE 2 — recalcular brotes con el conjunto COMPLETO (previos +
        # todos los casos propios). Corrige en memoria el valor de brote de
        # todos los casos antes de que nadie se registre.
        self._recalcular_brotes(self.reportes_actuales)

        # FASE 3 — registrar (ya con el brote corregido). Los casos dudosos
        # se aparcan para revisión conjunta antes de enviarlos.
        for rid, (destino, detalle, caso) in acumulados.items():
            caso = self.casos.get(rid, caso)  # toma el caso ya recalculado
            if rid in self._parkeados:
                continue
            motivo = self._es_dudoso(detalle, caso)
            if motivo:
                self._parkear_dudoso(destino, detalle, caso, motivo)
                continue
            ya_enviado = rid in self.estado["enviados"]
            enviado = self._registrar_caso(destino, caso, forzar=bool(detalle.get("complemento")))
            if enviado and not ya_enviado:
                self.acciones_extra(destino, detalle, caso)

        if self.extras:
            self.revisar_brotes()

        # FASE 4 — reconciliación: registra reportes publicados que se hayan
        # quedado sin envío (parkeados, reinicio, fallo de red) y completa los
        # campos de Nivel 2 que falten. Es idempotente: no reenvía los que ya
        # están en `enviados`.
        self._reconciliar(reportes)

        self._guardar()
        return len(pendientes)

    def _registrar_caso(self, reporte: dict, caso: dict, forzar: bool = False) -> bool:
        """Envía un caso a POST /casos. Con `forzar=True` reenvía un padre ya
        registrado para complementar semáforo/técnico/brote (la API solo cuenta
        la primera vez cada campo)."""
        if not self.enviar:
            return False
        rid = caso.get("reporte_id")
        if not rid:
            return False
        if rid in self.estado["enviados"] and not forzar:
            return True
        ya_estaba = rid in self.estado["enviados"]
        # validacion de formato (no puntua, no registra)
        try:
            self.api.validar_caso(caso_para_api(caso))
        except ApiError as exc:
            print(f"[{ahora()}] AVISO validación {rid}: {exc}")
        try:
            respuesta = self.api.registrar_caso(caso_para_api(caso))
            if rid not in self.estado["enviados"]:
                self.estado["enviados"].append(rid)
            etiqueta = "complemento" if (forzar and ya_estaba) else "registrado"
            print(f"[{ahora()}] {etiqueta} en POST /casos: {rid}")
            try:
                self.repo.guardar_envio(rid, caso, "enviado", respuesta=respuesta)
            except Exception as exc:
                print(f"[{ahora()}] aviso Supabase (envío {rid}): {exc}")
            # Persistir de inmediato: si el proceso muere, no se pierde el aviso
            # de que este reporte ya fue enviado.
            guardar_json(ESTADO, self.estado)
            return True
        except ApiError as exc:
            print(f"[{ahora()}] error registrando {rid}: {exc}")
            # Si falló un complemento, se quita de enviados para que la
            # reconciliación lo reintente. No se reintenta un 4xx de formato
            # ni un duplicado definitivo.
            if (forzar and rid in self.estado["enviados"]
                    and exc.status not in (409, 422)):
                self.estado["enviados"].remove(rid)
            try:
                self.repo.guardar_envio(rid, caso, "error", error=str(exc))
            except Exception as exc2:
                print(f"[{ahora()}] aviso Supabase (error {rid}): {exc2}")
            return False

    def _reconciliar(self, reportes: list[dict]) -> None:
        """Cierra huecos de registro sin reenviar casos ya enviados.

        - Crea el caso de cualquier reporte publicado que no esté en `casos`
          (por ejemplo, si el listener arrancó tarde o el estado se perdió).
        - Recalcula brotes con el conjunto completo.
        - Envía los casos que no estén en `enviados`.
        - Las respuestas (`respuesta_a`) no se envían como casos propios; su
          padre se envía/complementa desde el flujo normal.
        """
        if not self.enviar:
            return
        self.clf.reportes_actuales = self.reportes_actuales
        self.clf.casos_actuales = self.casos
        por_id = {r["id"]: r for r in reportes}
        reportes_ordenados = sorted(
            reportes, key=lambda r: (str(r.get("recibido") or ""), str(r.get("id") or ""))
        )

        for reporte in reportes_ordenados:
            if reporte.get("respuesta_a"):
                continue
            rid = reporte["id"]
            if rid in self.casos or rid in self._parkeados:
                continue
            detalle = self.procesar(reporte)
            caso = detalle.get("caso", {k: detalle.get(k) for k in ("reporte_id", "es_plaga", "plaga", "urgente")})
            if caso and caso.get("reporte_id"):
                self.casos[caso["reporte_id"]] = caso
                self._marcar_procesado(caso["reporte_id"])

        self._recalcular_brotes(por_id)

        for rid, caso in list(self.casos.items()):
            if rid in self.estado["enviados"] or rid in self._parkeados:
                continue
            reporte = por_id.get(rid) or self._reporte_por_id(rid)
            if not reporte:
                continue
            if reporte.get("respuesta_a"):
                continue
            # Igual que en el flujo normal (FASE 3): los casos que el motor no
            # identifica bien NO se registran a ciegas — se aparcan para
            # revisión conjunta. Sin esto, la reconciliación enviaba textos
            # vagos ("Algo le está pasando a mi siembra") con plaga
            # "desconocida" que la API no puntúa en algunos cultivos
            # (regresión real R-2097, frijol: plaga quedó null y perdió +1).
            detalle = {"texto": reporte.get("texto") or "", "confianza": caso.get("confianza") or 0}
            motivo = self._es_dudoso(detalle, caso)
            if motivo:
                self._parkear_dudoso(reporte, detalle, caso, motivo)
                continue
            if self._registrar_caso(reporte, caso):
                self.acciones_extra(reporte, detalle, caso)

    def _recalcular_brotes(self, reportes_por_id: dict) -> None:
        """Reaplica la regla de brote sobre el conjunto completo de casos."""
        try:
            brotes = self.clf.brotes_de_casos(list(self.casos.values()), reportes_por_id)
            for rid, valor_brote in brotes.items():
                if rid not in self.casos:
                    continue
                valor_brote = bool(valor_brote)
                if bool(self.casos[rid].get("brote")) == valor_brote:
                    continue
                self.casos[rid]["brote"] = valor_brote
                try:
                    self.repo.actualizar_brote(rid, valor_brote)
                except Exception as exc:
                    print(f"[{ahora()}] aviso Supabase (brote {rid}): {exc}")
        except Exception as exc:
            print(f"[{ahora()}] no se pudieron recalcular brotes: {exc}")

    def _guardar(self) -> None:
        guardar_json(CASOS_TODOS, list(self.casos.values()))
        guardar_json(ESTADO, self.estado)

    def _es_dudoso(self, detalle: dict, caso: dict) -> str | None:
        """Devuelve el motivo si el caso merece revisión conjunta, o None."""
        if not caso.get("es_plaga"):
            conf = detalle.get("confianza") or 0
            if float(conf) >= CONFIANZA_DUDOSA:
                return None
        conf = float(detalle.get("confianza") or 0)
        if caso.get("plaga") == "desconocida":
            return "plaga desconocida (el motor no identificó qué plaga es)"
        if conf < CONFIANZA_DUDOSA:
            return f"confianza baja ({conf:.2f})"
        if caso.get("brote") and conf < 0.75:
            return "brote marcado con confianza media (revisar antes de enviar)"
        return None

    def _parkear_dudoso(self, reporte: dict, detalle: dict, caso: dict, motivo: str) -> None:
        """Guarda el caso en pendientes y avisa al coordinador por Telegram."""
        pendientes = []
        if PENDIENTES_REVISION.exists():
            try:
                pendientes = json.loads(PENDIENTES_REVISION.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pendientes = []
        pendientes = [p for p in pendientes if p.get("reporte_id") != caso["reporte_id"]]
        pendientes.append({
            "reporte_id": caso["reporte_id"],
            "recibido": reporte.get("recibido"),
            "texto": (detalle.get("texto") or "")[:280],
            "motivo": motivo,
            "caso": caso_para_api(caso),
            "procesado": ahora(),
        })
        guardar_json(PENDIENTES_REVISION, pendientes)
        self._parkeados.add(str(caso["reporte_id"]))
        print(f"[{ahora()}] CASO DUDOSO {caso['reporte_id']}: {motivo} -> pendiente de revisión")
        if self.telegram:
            try:
                from telegram_notificador import alerta_dudoso

                alerta_dudoso(caso, motivo, detalle)
            except Exception as exc:
                print(f"[{ahora()}] aviso Telegram de dudoso falló: {exc}")

    def _arrancar_vigilante(self) -> None:
        """Avisa al coordinador por Telegram cuando hay reportes por verificar."""
        try:
            import threading

            from vigilante import Vigilante

            v = Vigilante(api=self.api, telegram=True)
            hilo = threading.Thread(target=v.correr, daemon=True, name="vigilante")
            hilo.start()
            print(f"[{ahora()}] vigilante de puntos activo (hilo {hilo.name})")
        except Exception as exc:
            print(f"[{ahora()}] no se pudo arrancar el vigilante: {exc}")

    def _arrancar_bot_telegram(self) -> None:
        """Levanta el agente del bot de Telegram en un hilo en segundo plano."""
        try:
            import threading

            from bot_telegram import BotTelegram

            bot = BotTelegram(self.api)
            hilo = threading.Thread(target=bot.correr, kwargs={"una_vez": False},
                                    daemon=True, name="bot-telegram")
            hilo.start()
            print(f"[{ahora()}] bot de Telegram activo (hilo {hilo.name})")
        except Exception as exc:
            print(f"[{ahora()}] no se pudo arrancar el bot de Telegram: {exc}")

    def acciones_extra(self, reporte: dict, detalle: dict, caso: dict) -> None:
        """Telegram, avisos y preguntas para un caso recién procesado."""
        plaga = next((p for p in self.clf.plagas if p["id"] == caso.get("plaga")), None)
        parcela = self.clf.parcelas.get(reporte.get("parcela_id") or "")
        productor = self.productores.get(reporte.get("productor_id") or "")

        # Telegram: solo rojo y naranja (lo que pide el reto)
        if caso.get("semaforo") in ("rojo", "naranja"):
            try:
                from telegram_notificador import alerta_caso

                alerta_caso(caso, plaga, parcela, productor)
            except Exception as exc:
                print(f"[{ahora()}] telegram falló: {exc}")

        if not self.extras:
            return

        if plaga and parcela:
            self.extras.avisar_cuarentenaria(caso, plaga, parcela)
            self.extras.avisar_asignacion(caso, plaga, parcela, reporte.get("productor_id"))

        if self.preguntas:
            texto = self.extras.sugerir_pregunta(reporte, detalle)
            if texto:
                self.extras.preguntar(caso["reporte_id"], texto)

    def revisar_brotes(self) -> None:
        """Detecta brotes nuevos y avisa a los vecinos una sola vez por brote."""
        try:
            previos = self.api.get("casos-previos") or []
        except ApiError:
            return
        reportes = self.reportes_actuales or {
            r["id"]: r for r in cargar_json(RAIZ / "cache" / "reportes.json", [])
        }
        enriquecidos = []
        for caso in self.casos.values():
            reporte = reportes.get(caso["reporte_id"], {})
            copia = dict(caso)
            copia["recibido"] = reporte.get("recibido")
            copia["parcela_id"] = reporte.get("parcela_id")
            enriquecidos.append(copia)

        for brote in self.extras.detectar_brotes(enriquecidos, self.clf.parcelas, previos):
            firma = f"{brote['plaga']}:" + ",".join(sorted(brote["casos"]))
            if firma in self.estado["brotes_avisados"]:
                continue
            self.extras.avisar_brote(brote, self.clf.parcelas, self.productores)
            self.estado["brotes_avisados"].append(firma)
            print(f"[{ahora()}] brote avisado: {brote['plaga']} ({len(brote['casos'])} casos)")

    # ---------- mantenimiento ----------

    def refrescar_catalogo(self) -> None:
        """Recarga /plagas, /parcelas y /tecnicos por si el reto cambió."""
        try:
            self.clf.recargar_catalogo()
            self.ultimo_refresco = time.time()
            print(f"[{ahora()}] catálogos refrescados ({len(self.clf.plagas)} plagas, "
                  f"{len(self.clf.parcelas)} parcelas)")
            try:
                self.repo.sincronizar_catalogos(
                    self.clf.plagas,
                    list(self.clf.parcelas.values()),
                    self.api.get_productores(),
                    self.api.get_tecnicos(),
                )
            except Exception as exc:
                print(f"[{ahora()}] aviso Supabase (catálogos): {exc}")
        except Exception as exc:
            print(f"[{ahora()}] no se pudo refrescar el catálogo: {exc}")

    def correr(self, una_vez: bool = False) -> None:
        print(f"[{ahora()}] listener iniciado | intervalo {self.intervalo}s | "
              f"registro automático: {'SÍ' if self.enviar else 'NO'}")
        if self.telegram:
            self._arrancar_bot_telegram()

        # Refresca catálogos, casos previos y visitas ANTES del primer ciclo.
        # También sincroniza Supabase para que existan las claves foráneas.
        self.refrescar_catalogo()
        if self.vigilante:
            self._arrancar_vigilante()

        while True:
            inicio = time.time()
            try:
                nuevos = self.ciclo()
                if nuevos:
                    print(f"[{ahora()}] {nuevos} reporte(s) nuevo(s) procesado(s) | "
                          f"total en esta sesión: {self.nuevos_total}")
                if time.time() - self.ultimo_refresco >= self.refresco:
                    self.refrescar_catalogo()
            except KeyboardInterrupt:
                print(f"\n[{ahora()}] listener detenido por el usuario")
                break
            except Exception:
                # nunca morir por un fallo inesperado
                print(f"[{ahora()}] error inesperado, el listener sigue:")
                traceback.print_exc()

            if una_vez:
                break
            espera = max(1.0, self.intervalo - (time.time() - inicio))
            try:
                time.sleep(espera)
            except KeyboardInterrupt:
                print(f"\n[{ahora()}] listener detenido por el usuario")
                break


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Listener continuo de reportes (Alerta Plaga)")
    parser.add_argument("--intervalo", type=int, default=20, help="Segundos entre consultas (por defecto 20)")
    parser.add_argument("--refresco", type=int, default=10, help="Minutos entre refrescos de catálogo")
    parser.add_argument("--una-vez", action="store_true", help="Una sola pasada y salir")
    parser.add_argument("--enviar", action="store_true", help="Registrar en POST /casos (irreversible)")
    parser.add_argument("--extras", action="store_true", help="Activar avisos (cuarentenarias, asignación, brotes)")
    parser.add_argument("--avisos-reales", action="store_true", help="Enviar avisos a la API (si no, modo seco)")
    parser.add_argument("--preguntas", action="store_true", help="Hacer preguntas a los productores")
    parser.add_argument("--telegram", action="store_true", help="Activar el agente del bot de Telegram")
    parser.add_argument("--vigilante", action="store_true",
                        help="Avisa por Telegram reportes por verificar / dudosos (no registra nada)")
    parser.add_argument("--reiniciar", action="store_true", help="Ignorar el estado y reprocesar todo")
    args = parser.parse_args()

    if args.reiniciar:
        for archivo in (ESTADO,):
            if archivo.exists():
                archivo.unlink()

    listener = Listener(intervalo=args.intervalo, refresco_min=args.refresco, enviar=args.enviar,
                        extras=args.extras, preguntas=args.preguntas,
                        avisos_reales=args.avisos_reales, telegram=args.telegram,
                        vigilante=args.vigilante)
    listener.correr(una_vez=args.una_vez)


if __name__ == "__main__":
    main()
