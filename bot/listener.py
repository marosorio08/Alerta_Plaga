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
                 telegram: bool = False) -> None:
        self.api = ApiCliente()
        self.clf = Clasificador(self.api, con_ia=True)
        self.intervalo = intervalo
        self.refresco = refresco_min * 60
        self.enviar = enviar
        self.preguntas = preguntas
        self.telegram = telegram
        self.repo = RepositorioSupabase()
        self.extras = Extras(self.api, seco=not avisos_reales, repo=self.repo) if extras else None
        self.productores = {p["id"]: p for p in self.clf.api.get_productores()} if extras else {}
        self.estado = cargar_json(ESTADO, {"procesados": [], "enviados": [], "iniciado": ahora()})
        self.estado.setdefault("brotes_avisados", [])
        self.casos = {c["reporte_id"]: c for c in cargar_json(CASOS_TODOS, [])}
        self.ultimo_refresco = time.time()
        self.nuevos_total = 0
        print(f"[{ahora()}] Supabase: {'conectado' if self.repo.activo else 'no configurado (solo caché local)'}")

    # ---------- clasificación ----------

    def procesar(self, reporte: dict) -> dict:
        try:
            self.repo.guardar_reporte(reporte)
        except Exception as exc:
            print(f"[{ahora()}] aviso Supabase (reporte {reporte.get('id')}): {exc}")
        try:
            res = self.clf.clasificar_reporte(reporte)
            caso = resultados_a_casos([reporte], self.clf)[0]
        except Exception as exc:  # un reporte raro nunca tumba el listener
            print(f"[{ahora()}] error clasificando {reporte.get('id')}: {exc}")
            traceback.print_exc()
            return {"reporte_id": reporte.get("id"), "es_plaga": True,
                    "plaga": "desconocida", "urgente": False, "error": str(exc)}

        detalle = {
            "reporte_id": reporte["id"],
            "tipo": reporte.get("tipo"),
            "parcela_id": reporte.get("parcela_id"),
            "cultivo": self.clf.cultivo_de_parcela(reporte.get("parcela_id")),
            "recibido": reporte.get("recibido"),
            "procesado": ahora(),
            "caso": caso,
            "motor": res.get("motor"),
            "confianza": res.get("confianza"),
            "razon": res.get("razon"),
            "injection": res.get("injection"),
            "texto": (res.get("texto") or reporte.get("texto") or "")[:280],
            "seguimiento_de": res.get("seguimiento_de"),
        }
        with BITACORA.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(detalle, ensure_ascii=False) + "\n")
        try:
            self.repo.guardar_caso(detalle)
        except Exception as exc:
            print(f"[{ahora()}] aviso Supabase (caso {detalle.get('reporte_id')}): {exc}")
        return detalle

    # ---------- ciclo ----------

    def ciclo(self) -> int:
        try:
            reportes = self.api.get_reportes()
        except ApiError as exc:
            print(f"[{ahora()}] API no responde: {exc}")
            return 0

        procesados = set(self.estado["procesados"])
        pendientes = [r for r in reportes if r["id"] not in procesados]
        if not pendientes:
            # Sin reportes nuevos igual se refresca el brote en la caché
            # compartida (los casos previos pudieron cambiar al reprocesar).
            self._recalcular_brotes({r["id"]: r for r in reportes})
            self._guardar()
            return 0

        for reporte in pendientes:
            detalle = self.procesar(reporte)
            caso = detalle.get("caso", {k: detalle.get(k) for k in ("reporte_id", "es_plaga", "plaga", "urgente")})
            self.casos[caso["reporte_id"]] = caso
            self.estado["procesados"].append(caso["reporte_id"])
            self.nuevos_total += 1

            marca = "URGENTE" if caso.get("urgente") else ("plaga" if caso["es_plaga"] else "no-plaga")
            conf = detalle.get("confianza") or 0
            nivel2 = ""
            if caso.get("semaforo"):
                nivel2 = f" sem={caso['semaforo']} tec={caso.get('tecnico_id')} pri={caso.get('prioridad')}"
            print(f"[{ahora()}] {caso['reporte_id']} {reporte.get('tipo', '?'):<5} "
                  f"{marca:<8} plaga={caso.get('plaga')} conf={round(float(conf), 2)}{nivel2} "
                  f"| {str(detalle.get('texto', ''))[:60]}")

            # validación de formato (no puntúa, no registra)
            try:
                self.api.validar_caso(caso_para_api(caso))
            except ApiError as exc:
                print(f"[{ahora()}] AVISO validación {caso['reporte_id']}: {exc}")

            if self.enviar and caso["reporte_id"] not in self.estado["enviados"]:
                try:
                    respuesta = self.api.registrar_caso(caso_para_api(caso))
                    self.estado["enviados"].append(caso["reporte_id"])
                    print(f"[{ahora()}] registrado en POST /casos: {caso['reporte_id']}")
                    try:
                        self.repo.guardar_envio(caso["reporte_id"], caso, "enviado", respuesta=respuesta)
                    except Exception as exc:
                        print(f"[{ahora()}] aviso Supabase (envío {caso['reporte_id']}): {exc}")
                except ApiError as exc:
                    print(f"[{ahora()}] error registrando {caso['reporte_id']}: {exc}")
                    try:
                        self.repo.guardar_envio(caso["reporte_id"], caso, "error", error=str(exc))
                    except Exception as exc2:
                        print(f"[{ahora()}] aviso Supabase (error {caso['reporte_id']}): {exc2}")

            self.acciones_extra(reporte, detalle, caso)

        if self.extras:
            self.revisar_brotes()

        # El brote es una regla global: se recalcula con previos + todos los
        # casos propios (el orden de llegada no puede sesgar el resultado).
        self._recalcular_brotes({r["id"]: r for r in reportes})
        self._guardar()
        return len(pendientes)

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
        reportes = {r["id"]: r for r in cargar_json(RAIZ / "cache" / "reportes.json", [])}
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
    parser.add_argument("--reiniciar", action="store_true", help="Ignorar el estado y reprocesar todo")
    args = parser.parse_args()

    if args.reiniciar:
        for archivo in (ESTADO,):
            if archivo.exists():
                archivo.unlink()

    listener = Listener(intervalo=args.intervalo, refresco_min=args.refresco, enviar=args.enviar,
                        extras=args.extras, preguntas=args.preguntas,
                        avisos_reales=args.avisos_reales, telegram=args.telegram)
    listener.correr(una_vez=args.una_vez)


if __name__ == "__main__":
    main()
