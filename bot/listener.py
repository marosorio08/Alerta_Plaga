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
from clasificador import Clasificador, caso_para_api, fusionar_respuesta, resultados_a_casos  # noqa: E402
from confirmados import (  # noqa: E402
    cargar_confirmados, cargar_descartados, confirmar, guardar_confirmados,
    sembrar_desde_enviados,
)
from nivel2 import decidir_brote  # noqa: E402
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
# Interruptor de seguridad: el agente NO envía nada a POST /casos ni avisos
# hasta que se defina PERMITIR_ENVIOS=1 en su .env. Así se pueden verificar
# los reportes nuevos sin arriesgar puntos.
ENVIOS_HABILITADOS = os.getenv("PERMITIR_ENVIOS", "0") == "1"


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
        self.enviar = bool(enviar and ENVIOS_HABILITADOS)
        self.preguntas = preguntas
        self.telegram = telegram
        self.vigilante = vigilante
        self.repo = RepositorioSupabase()
        self.extras = Extras(
            self.api,
            seco=(not avisos_reales or not self.enviar),
            seco_preguntas=not preguntas,
            repo=self.repo,
        ) if extras else None
        self.productores = {p["id"]: p for p in self.clf.api.get_productores()} if extras else {}
        self.estado = cargar_json(ESTADO, {"procesados": [], "enviados": [], "iniciado": ahora()})
        self.estado.setdefault("brotes_avisados", [])
        self.estado.setdefault("dudosos_avisados", [])
        # Reportes a los que ya se les preguntó (no repetir la pregunta).
        self.estado.setdefault("preguntadas", [])
        # Respuestas ya fusionadas con su reporte original. Permite migrar
        # estados viejos en los que la respuesta se procesó con id equivocado.
        self.estado.setdefault("respuestas_aplicadas", [])
        self.casos = {c["reporte_id"]: c for c in cargar_json(CASOS_TODOS, [])}
        # Ledger de casos que la API ya confirmó (201/409) y falsas alarmas.
        # El brote solo cuenta esos casos; las propuestas locales no inflan.
        self.confirmados = cargar_confirmados()
        self.descartados = cargar_descartados()
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
        if enviar and not self.enviar:
            print(f"[{ahora()}] PAUSA DE ENVÍOS: define PERMITIR_ENVIOS=1 en el .env "
                  "para registrar casos nuevos y avisos. Por ahora solo se clasifica y guarda en caché.")

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

    def _sembrar_confirmados(self, reportes: list[dict]) -> None:
        """Recupera el ledger si no existe o si faltan casos ya enviados.

        Nunca reescribe un caso ya congelado: si el ledger ya tiene la
        referencia, se conserva la plaga y coordenadas originales.
        """
        por_id = self.reportes_actuales or {r["id"]: r for r in reportes}
        nuevos = sembrar_desde_enviados(
            self.confirmados, self.casos, por_id, self.clf.parcelas,
            self.estado.get("enviados", []),
        )
        if nuevos:
            guardar_confirmados(self.confirmados)
            print(f"[{ahora()}] ledger de brotes: {nuevos} caso(s) confirmado(s) recuperado(s)")

    def _confirmar_caso(self, rid: str, caso: dict, reporte: dict | None = None) -> None:
        """Congela un caso aceptado por la API para el conteo de brotes."""
        reporte = (reporte or self.reportes_actuales.get(rid)
                   or self._reporte_por_id(rid) or {})
        ref = confirmar(self.confirmados, caso, reporte, self.clf.parcelas)
        if ref:
            guardar_confirmados(self.confirmados)

    @staticmethod
    def _fusionar_respuesta(padre: dict, respuesta: dict,
                            plaga_padre: str | None = None) -> dict:
        """Combina el mensaje original con la respuesta del productor."""
        return fusionar_respuesta(padre, respuesta, plaga_padre)

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
        plaga_padre = None
        if padre:
            caso_padre = self.casos.get(padre.get("id")) or {}
            if caso_padre.get("es_plaga"):
                plaga_padre = caso_padre.get("plaga")
        para_clasificar = (self._fusionar_respuesta(padre, reporte, plaga_padre)
                           if padre else reporte)
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
        # El bot de Telegram puede marcar falsas alarmas en otro proceso.
        self.descartados = cargar_descartados()
        self._sembrar_confirmados(reportes)

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

        # FASE 2 — recalcular brotes con el lote nuevo + los casos ya
        # confirmados por la API. Las propuestas viejas o aparcadas no cuentan:
        # la API no las conoce y no deben inflar el brote.
        self._recalcular_brotes(self.reportes_actuales, ids_batch=list(acumulados))

        # FASE 3 — registrar (ya con el brote corregido). Los casos dudosos
        # se aparcan para revisión conjunta antes de enviarlos.
        for rid, (destino, detalle, caso) in acumulados.items():
            caso = self.casos.get(rid, caso)  # toma el caso ya recalculado
            # Preguntar al productor si falta un dato (parcela o plaga). Se hace
            # ANTES de aparcar/registrar y NO depende del envío de casos.
            self._preguntar_si_falta(destino, detalle, caso)
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
            # Congelar la referencia ANTES de que una reclasificación futura
            # pueda cambiar la plaga o la parcela usadas para brotes.
            self._confirmar_caso(rid, caso, reporte)
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
            # 409 = la API ya lo tenía registrado. Aunque no acepte el cambio,
            # el caso SÍ cuenta para brotes: se confirma con los datos locales.
            if getattr(exc, "status", None) == 409:
                self._confirmar_caso(rid, caso, reporte)
            return False

    def _reconciliar(self, reportes: list[dict]) -> None:
        """Cierra huecos de registro sin reenviar casos ya enviados.

        - Crea el caso de cualquier reporte publicado que no esté en `casos`
          (por ejemplo, si el listener arrancó tarde o el estado se perdió).
        - Recalcula brotes con previos + confirmados + los pendientes de envío.
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

        ids_pendientes = [
            rid for rid in self.casos
            if rid not in self.estado["enviados"] and rid not in self._parkeados
        ]
        self._recalcular_brotes(por_id, ids_batch=ids_pendientes)

        for rid, caso in list(self.casos.items()):
            if rid in self.estado["enviados"] or rid in self._parkeados:
                continue
            reporte = por_id.get(rid) or self._reporte_por_id(rid)
            if not reporte:
                continue
            if reporte.get("respuesta_a"):
                continue
            # Si la API YA tiene este reporte registrado (por el flujo normal
            # o por sesiones anteriores), no hay nada que hacer: marcarlo
            # como enviado para que la reconcilación no lo re-procese y no lo
            # aparque como falso dudoso (ruido tipo R-2001..R-2090).
            try:
                st = self.api.validar_caso(caso_para_api(caso))
                if isinstance(st, dict) and st.get("ya_registrado_antes"):
                    self.estado["enviados"].append(rid)
                    self._confirmar_caso(rid, caso, reporte)
                    continue
            except Exception as exc:
                print(f"[{ahora()}] aviso validando {rid} en reconciliación: {exc}")
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

    def _recalcular_brotes(self, reportes_por_id: dict,
                           ids_batch: list[str] | None = None) -> None:
        """Reaplica la regla de brote con la fuente de verdad confirmada.

        - Con ``ids_batch``: evalúa el lote nuevo contra previos + confirmados
          + los demás casos del lote. Sirve para decidir qué aparcar.
        - Sin ``ids_batch``: audita cada caso contra previos + confirmados
          únicamente (no deja que propuestas viejas cuenten entre sí).

        Guarda ``_brote_n``, ``_brote_refs`` y ``_brote_modo`` para auditoría.
        A los casos nuevos les aplica la política conservadora: ``n == 2`` no
        envía ``brote`` y los manda a revisión.
        """
        try:
            detalles: dict[str, dict] = {}
            kwargs_ledger = {"confirmados": self.confirmados} if self.confirmados else {}
            if ids_batch is None:
                for rid, caso in list(self.casos.items()):
                    if rid in self.descartados or caso.get("descartado"):
                        continue
                    info = self.clf.evaluar_brotes(
                        [caso], reportes_por_id,
                        descartados=self.descartados,
                        **kwargs_ledger,
                    )
                    if rid in info:
                        detalles[rid] = info[rid]
            else:
                casos_lote = [self.casos[rid] for rid in ids_batch
                              if rid in self.casos and rid not in self.descartados]
                detalles = self.clf.evaluar_brotes(
                    casos_lote, reportes_por_id,
                    descartados=self.descartados,
                    **kwargs_ledger,
                )

            for rid, info in detalles.items():
                caso = self.casos.get(rid)
                if not caso:
                    continue
                caso["_brote_n"] = info["n"]
                caso["_brote_refs"] = info["refs"]
                caso["_brote_modo"] = info.get("modo")
                caso["_brote_confirmados"] = bool(info.get("confirmados"))
                if rid in self.estado["enviados"]:
                    # Ya está en la API: no se puede cambiar; solo se audita.
                    continue
                decision = decidir_brote(info["n"])
                if decision is None:
                    caso.pop("brote", None)
                    caso["_brote_dudoso"] = True
                    continue
                caso.pop("_brote_dudoso", None)
                if bool(caso.get("brote")) == decision:
                    continue
                caso["brote"] = decision
                try:
                    self.repo.actualizar_brote(rid, decision)
                except Exception as exc:
                    print(f"[{ahora()}] aviso Supabase (brote {rid}): {exc}")
        except Exception as exc:
            print(f"[{ahora()}] no se pudieron recalcular brotes: {exc}")

    def _guardar(self) -> None:
        guardar_json(CASOS_TODOS, list(self.casos.values()))
        guardar_json(ESTADO, self.estado)

    def _preguntar_si_falta(self, reporte: dict, detalle: dict, caso: dict) -> None:
        """Pregunta al productor cuando falta la parcela o la plaga.

        Es el flujo validado con R-2128: `POST /preguntas` -> el productor
        responde un `-R` con la parcela y el porcentaje, y el caso se completa
        con datos reales en vez de inferirlos. No arriesga puntos y suma en el
        reto extra de "preguntas".
        """
        if not self.preguntas or not self.extras:
            return
        rid = caso.get("reporte_id") or reporte.get("id")
        if not rid or rid in self.estado["preguntadas"]:
            return
        if reporte.get("respuesta_a"):
            return  # es una respuesta del productor, no un reporte nuevo
        # Si ya está registrado y completo, no hay nada que preguntar.
        if rid in self.estado["enviados"] and caso.get("semaforo") and caso.get("tecnico_id"):
            return
        texto = self.extras.sugerir_pregunta(reporte, caso)
        if not texto:
            return
        resp = self.extras.preguntar(rid, texto)
        if resp:
            self.estado["preguntadas"].append(rid)
            guardar_json(ESTADO, self.estado)
            print(f"[{ahora()}] pregunta enviada a {rid}: {texto[:80]}")

    def _es_dudoso(self, detalle: dict, caso: dict) -> str | None:
        """Devuelve el motivo si el caso merece revisión conjunta, o None.

        Regla de la sesión (21-oct, tarde, Rafa): TODO caso con ``brote=True``
        se aparca SIEMPRE, sin importar la confianza, para evaluarlo juntos y
        dar el visto bueno antes de registrarlo. Un brote mal marcado vale
        -1 punto (MISA 100% vs nuestro ~92%), así que ninguna brote se manda
        a ciegas.
        """
        if not caso.get("es_plaga"):
            conf = detalle.get("confianza") or 0
            if float(conf) >= CONFIANZA_DUDOSA:
                return None
        conf = float(detalle.get("confianza") or 0)
        # 0) BROTE: siempre requiere visto bueno (regla de Rafa).
        if caso.get("brote"):
            return f"brote activo (evaluar juntos antes de registrar) · n={caso.get('_brote_n', '?')} · conf={conf:.2f}"
        if caso.get("_brote_dudoso"):
            return f"brote en el límite (n={caso.get('_brote_n', 2)}; no se envía brote hasta revisar)"
        # Voz sin transcripción: no leímos el mensaje, así que no se registra a
        # ciegas aunque la regla de cultivo exclusivo dé una plaga (R-2121).
        if detalle.get("tipo") == "voz" and not str(detalle.get("texto") or "").strip():
            return "voz sin transcripción (no se leyó el mensaje; revisar antes de enviar)"
        # Parcela inferida: el reporte no traía parcela y se dedujo del
        # productor. No se envía a ciegas: hay que preguntarle (R-2128, donde
        # la inferencia habría elegido P-050 y la real era P-051).
        if caso.get("_parcela_inferida"):
            return (f"parcela inferida ({caso['_parcela_inferida']}); "
                    f"preguntar al productor antes de enviar")
        if caso.get("plaga") == "desconocida":
            return "plaga desconocida (el motor no identificó qué plaga es)"
        if conf < CONFIANZA_DUDOSA:
            return f"confianza baja ({conf:.2f})"
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
        rid = str(caso["reporte_id"])
        pendientes.append({
            "reporte_id": rid,
            "recibido": reporte.get("recibido"),
            "parcela_id": reporte.get("parcela_id"),
            "productor_id": reporte.get("productor_id"),
            "tipo": reporte.get("tipo"),
            "texto": (detalle.get("texto") or "")[:280],
            "motivo": motivo,
            "caso": caso_para_api(caso),
            "n": caso.get("_brote_n"),
            "refs": caso.get("_brote_refs") or [],
            "brote": caso.get("brote"),
            "sugerencia": ("marcar brote" if caso.get("brote")
                           else "marcar sin brote" if caso.get("_brote_dudoso")
                           else "revisar"),
            "procesado": ahora(),
        })
        guardar_json(PENDIENTES_REVISION, pendientes)
        self._parkeados.add(rid)
        print(f"[{ahora()}] CASO DUDOSO {rid}: {motivo} -> pendiente de revisión")
        # La notificación no depende del hilo del bot: el notificador ya sabe
        # trabajar en seco si faltan TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID.
        if rid in self.estado["dudosos_avisados"]:
            return
        try:
            from telegram_notificador import alerta_dudoso

            enviado = alerta_dudoso(caso, motivo, detalle,
                                    refs=caso.get("_brote_refs"))
            if enviado:
                self.estado["dudosos_avisados"].append(rid)
                print(f"[{ahora()}] alerta Telegram enviada: {rid}")
            else:
                print(f"[{ahora()}] alerta Telegram no enviada (seco o error): {rid}")
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
    parser.add_argument("--resolver-dudosos", action="store_true",
                        help="Procesa la cola de dudosos con el flujo validado y registra "   
                             "solo lo seguro (+Telegram con resultado y posición)")
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
    if args.resolver_dudosos:
        try:
            import threading
            from resolver_cola import ResolverCola

            resolver = ResolverCola(api=listener.api, telegram=args.telegram)
            hilo = threading.Thread(target=resolver.correr, daemon=True, name="resolver-dudosos")
            hilo.start()
            print(f"[{ahora()}] resolver de dudosos activo (hilo {hilo.name})")
        except Exception as exc:
            print(f"[{ahora()}] no se pudo arrancar el resolver de dudosos: {exc}")
    listener.correr(una_vez=args.una_vez)


if __name__ == "__main__":
    main()
