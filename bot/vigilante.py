"""
vigilante.py — Vela los reportes en vivo y avisa al coordinador por Telegram.

Objetivo: NO perder puntos. Cada ciclo revisa:

  1. POR REGISTRAR  — reportes PUBLICADOS en la API que todavía no están
                      registrados en POST /casos (puntos en riesgo si se queda).
  2. SUMAN MÁS      — casos ya registrados pero con campos AGREGABLES
                      (brote/semaforo/tecnico_id) que se pueden completar
                      después (+3, como R-2071).
  3. DUDOSOS        — casos que el motor aparcó en cache/revision_pendiente.json
                      (plaga desconocida, confianza baja, brote dudoso) y que
                      conviene revisar juntos antes de subir.

El vigilante NUNCA registra nada: usa POST /casos/validar (que no puntúa y
dice "ya_registrado_antes" + los agregables que faltan), así que es 100 % seguro.
Solo avisa por Telegram; la decisión la tomamos juntos.

Uso:
    from vigilante import Vigilante
    v = Vigilante(telegram=True)
    v.correr()            # loop cada intervalo segundos
    v.revisar()           # una pasada
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente, ApiError  # noqa: E402
from clasificador import caso_para_api  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
ESTADO_LISTENER = Path(os.getenv("CASOS_SALIDA_DIR", CACHE)) / "listener_estado.json"
PENDIENTES = CACHE / "revision_pendiente.json"
ESTADO_VIGILANTE = CACHE / "vigilante_estado.json"
# En el servidor los casos compartidos con el dashboard viven en ~/app/cache.
CASOS_LOCAL = Path(os.getenv("CASOS_SALIDA") or (CACHE / "casos_propuestos.json"))


def ahora() -> str:
    return datetime.now().strftime("%d-%m %H:%M")


def _leer_json(archivo: Path, defecto):
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except Exception:
        return defecto


class Vigilante:
    """Monitorea la API y avisa por Telegram cuando hay algo que revisar."""

    def __init__(self, api: ApiCliente | None = None, telegram: bool = True,
                 intervalo: int = 90, minimo_revisita_min: int = 30) -> None:
        self.api = api or ApiCliente()
        self.telegram = telegram
        self.intervalo = max(20, int(intervalo))
        # No repetir avisos del mismo reporte en menos de N minutos salvo que
        # cambie su estado (evita spam: mismo pendiente se avisa 1 vez/30 min).
        self.minimo_revisita_s = int(minimo_revisita_min) * 60
        self.ultimo_envio: dict = {}

    # ------------------------------------------------------------------ util

    def _msg_telegram(self, texto: str) -> None:
        if not self.telegram:
            print("[vigilante] (sin telegram) " + texto.replace("\n", " | ")[:400])
            return
        try:
            from telegram_notificador import enviar

            enviar(texto)
        except Exception as exc:
            print(f"[vigilante] telegram falló: {exc}")

    def _guarda_estado(self) -> None:
        try:
            ESTADO_VIGILANTE.parent.mkdir(exist_ok=True)
            tmp = ESTADO_VIGILANTE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.ultimo_envio, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(ESTADO_VIGILANTE)
        except Exception as exc:
            print(f"[vigilante] no pude guardar estado: {exc}")

    # -------------------------------------------------------------- análisis

    def _estado_registro(self, rid: str, caso: dict):
        """Consulta el estado de registro de un caso SIN registrarlo.

        POST /casos/validar no puntúa: devuelve si el reporte ya se registró
        y qué campos agregables le faltan. Nunca abre un caso nuevo.
        """
        try:
            resp = self.api.validar_caso(caso_para_api(caso))
        except ApiError as exc:
            return {"ok": False, "error": str(exc)[:120]}
        if not isinstance(resp, dict):
            return {"ok": False, "error": "respuesta rara"}
        ya = bool(resp.get("ya_registrado_antes"))
        mensaje = str(resp.get("mensaje") or "")
        agregables: list[str] = []
        for campo in ("brote", "semaforo", "tecnico_id"):
            if campo in mensaje:
                agregables.append(campo)
        return {"ya_registrado": ya, "agregables": agregables, "mensaje": mensaje[:160]}

    def _categorias(self) -> dict:
        """Devuelve {por_registrar, suman_mas, dudosos} con lo que hay que mirar."""
        reportes = self.api.get_reportes() or []
        casos_local = {c["reporte_id"]: c for c in _leer_json(CASOS_LOCAL, [])}
        estado_listener = _leer_json(ESTADO_LISTENER, {})
        enviados = set(estado_listener.get("enviados", []))
        dudosos = _leer_json(PENDIENTES, [])

        por_registrar: list[dict] = []
        suman_mas: list[dict] = []
        ahora_ts = time.time()
        dudosos_ids = {p.get("reporte_id") for p in dudosos if p.get("reporte_id")}

        for r in reportes:
            rid = r["id"]
            if rid.endswith("-R"):          # respuestas de productor, no reporte
                continue
            caso = casos_local.get(rid)
            if not caso or not caso.get("es_plaga"):
                # sin plaga (administrativo) o aún sin clasificar: el listener lo hace
                continue
            previo = self.ultimo_envio.get(rid) or {}
            revisita = ahora_ts - previo.get("ts", 0)
            if revisita < self.minimo_revisita_s and previo.get("estado"):
                # ya avisado y sin cambios recientes -> no volver a molestar aún
                continue

            st = self._estado_registro(rid, caso)
            if not st.get("ok"):
                continue
            # 1) ya registrado pero con agregables -> puede sumar más
            if st.get("ya_registrado") and st.get("agregables"):
                suman_mas.append({"rid": rid, "plaga": caso.get("plaga"),
                                  "agregables": st["agregables"]})
                self.ultimo_envio[rid] = {"ts": ahora_ts, "estado": "suman"}
            # 2) publicado y NO registrado -> puntos en riesgo
            #    (si además es dudoso, aparece solo en la sección DUDOSOS)
            elif not st.get("ya_registrado") and rid not in dudosos_ids:
                por_registrar.append({"rid": rid, "plaga": caso.get("plaga"),
                                      "sem": caso.get("semaforo"), "tec": caso.get("tecnico_id"),
                                      "brote": caso.get("brote"), "texto": (r.get("texto") or "")[:70]})
                self.ultimo_envio[rid] = {"ts": ahora_ts, "estado": "porRegistrar"}
            elif rid in enviados:
                self.ultimo_envio[rid] = {"ts": ahora_ts, "estado": "ok"}

        # 3) dudosos aparcados por el motor (revisión conjunta).
        # Se filtran los que YA están registrados (ej. los resolvimos manual):
        # no tiene sentido avisarlos de nuevo.
        dudosos_vistos: list[dict] = []
        for p in dudosos:
            rid = p.get("reporte_id", "")
            caso = p.get("caso") or casos_local.get(rid) or {"reporte_id": rid,
                                                             "es_plaga": True, "plaga": p.get("plaga")}
            st = self._estado_registro(rid, caso)
            if st.get("ya_registrado"):
                # ya resuelto (lo subimos nosotros): quitarlo y no avisar
                self.ultimo_envio[rid] = {"ts": ahora_ts, "estado": "ok"}
                continue
            previo = self.ultimo_envio.get(rid) or {}
            revisita = ahora_ts - previo.get("ts", 0)
            if revisita < self.minimo_revisita_s and previo.get("estado"):
                continue
            self.ultimo_envio[rid] = {"ts": ahora_ts, "estado": "dudoso"}
            dudosos_vistos.append({"rid": rid, "motivo": p.get("motivo", ""),
                                   "caso": caso})

        return {"por_registrar": por_registrar,
                "suman_mas": suman_mas,
                "dudosos": dudosos_vistos}

    def _armar_mensaje(self, cat: dict) -> str | None:
        if not (cat.get("por_registrar") or cat.get("suman_mas")):
            return None
        lineas = [f"🔎 VIGILANTE 7_7 — {ahora()}"]
        if cat["por_registrar"]:
            lineas.append("\n📌📤 REPORTES NUEVOS SIN REGISTRAR (¡puntos en riesgo!):")
            for c in cat["por_registrar"][:12]:
                det = f"{c.get('sem')} t={c.get('tec')} brote={c.get('brote')}"
                lineas.append(f"  • {c['rid']} {str(c.get('plaga'))[:16]:16} | {det} | {c.get('texto','')[:40]}")
        if cat["suman_mas"]:
            lineas.append("\n💰 PUEDEN SUMAR +3 (completar campos):")
            for c in cat["suman_mas"][:12]:
                lineas.append(f"  • {c['rid']} {str(c.get('plaga'))[:16]} -> agregar {','.join(c['agregables'])}")
        lineas.append("\nEl vigilante solo informa; el modelo autónomo decide y avisa solo si hay duda persistente.")
        return "\n".join(lineas)

    # --------------------------------------------------------------- bucle

    def revisar(self) -> None:
        """Una pasada: analiza, y si hay novedades avisa por Telegram."""
        try:
            cat = self._categorias()
        except Exception as exc:
            print(f"[vigilante] error en revisar: {exc}")
            import traceback

            traceback.print_exc()
            return
        mensaje = self._armar_mensaje(cat)
        if mensaje:
            # comparar con el último mensaje para no repetir el mismo aviso
            huella = mensaje.split("👉")[0].strip()
            if huella != self.ultimo_envio.get("_huella"):
                self._msg_telegram(mensaje)
                self.ultimo_envio["_huella"] = huella
        self._guarda_estado()

    def correr(self) -> None:
        print(f"[vigilante] activo | cada {self.intervalo}s | telegram={self.telegram}")
        while True:
            try:
                self.revisar()
            except KeyboardInterrupt:
                print("[vigilante] detenido")
                return
            except Exception:
                import traceback

                traceback.print_exc()
            time.sleep(self.intervalo)


def main() -> None:
    import argparse

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Vigilante de puntos 7_7")
    parser.add_argument("--una-vez", action="store_true", help="Una pasada y sale")
    parser.add_argument("--sin-telegram", action="store_true", help="Solo imprime")
    parser.add_argument("--intervalo", type=int, default=90)
    args = parser.parse_args()
    v = Vigilante(telegram=not args.sin_telegram, intervalo=args.intervalo)
    if args.una_vez:
        v.revisar()
    else:
        v.correr()


if __name__ == "__main__":
    main()
