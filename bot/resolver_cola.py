"""
resolver_cola.py — Automatiza la verificación de casos DUDOSOS (flujo 7_7).

Para cada reporte en `revision_pendiente.json` (desconocida / confianza baja /
brote dudoso) repite EXACTAMENTE el flujo que validamos caso a caso:

  1. Contexto (reporte, productor, parcela, cultivo, texto/transcripción).
  2. Comparación con precedentes aprendidos (mismo patrón + cultivo) y con los
     `/casos-previos` de la semana.
  3. Reanálisis: ¿seguimiento? ¿señales de plaga? ¿brote con conjunto completo?
  4. Decisión con el motor (`Clasificador`) y la regla de brote (cluster 24 h).

⚠️ Desde el 21-oct ~13:00 el resolver corre en MODO ANÁLISIS SOLO (por decisión
de Rafa): **NO envía nada a POST /casos ni a Telegram** — re-analiza cada
dudoso, deja marca de auditoría y conserva la cola completa para revisión
humana. Si en el futuro se quiere volver al modo automático, restaurar el
bloque que registraba y el aviso Telegram en `revisar()`.

Lecciones aprendidas que codifica (MEMORIA_VERIFICACION.md):
  * Texto vago sin señales en MAÍZ: "desconocida" puntúa 2/2 (R-2042/R-2089/R-2096).
  * Texto vago sin señales en FRIJOL: "desconocida" NO puntúa (R-2097 plaga null)
    -> NO auto-enviar, requiere humano.
  * Seguimiento (mismo productor/parcela <24 h o respuesta): la API solo califica
    es_plaga+plaga (máx 2) (R-2075/R-2088/R-2094/R-2095).
  * Con señales claras de plaga: nivel2 completo + brote con conjunto completo
    y dedupe por cluster 24 h (R-2098/R-2101-R-2103).

Uso:
    python bot/resolver_cola.py --una-vez          # una pasada (análisis)
    python bot/resolver_cola.py                    # bucle cada N s (análisis)
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
from clasificador import Clasificador, caso_para_api  # noqa: E402
from nivel2 import _a_datetime  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
PENDIENTES = CACHE / "revision_pendiente.json"
BITACORA = CACHE / "resolver_bitacora.jsonl"  # historial propio del resolver

# Umbrales: la confianza con la que el motor respalda la decisión.
CONFIANZA_AUTO = 0.6
BROTE_CONFIABLE = 0.75

# Precedentes validados: (patrón, cultivo|None, decisión, folio de referencia)
PRECEDENTES = {
    # texto vago sin señales -> "desconocida" puntúa 2/2 SOLO en maíz
    ("texto_vago", "maíz"): {"enviar": True, "plaga": "desconocida",
                             "pts": 2, "ref": "R-2042/R-2089/R-2096"},
    # en frijol "desconocida" NO puntúa -> no auto-enviar (R-2097)
    ("texto_vago", "frijol"): {"enviar": False, "ref": "R-2097 (plaga null)"},
    # seguimiento genérico -> es_plaga+plaga (máx 2)
    "seguimiento": {"enviar": True, "pts": 2, "ref": "R-2075/R-2088/R-2094/R-2095"},
}


def ahora() -> str:
    return datetime.now().strftime("%d-%m %H:%M:%S")


def _leer_json(archivo: Path, defecto):
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _guardar_json(archivo: Path, datos) -> None:
    try:
        archivo.parent.mkdir(exist_ok=True)
        archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[resolver] no pude guardar {archivo.name}: {exc}")


class ResolverCola:
    """Procesa la cola de dudosos con el flujo validado; registra solo lo seguro."""

    def __init__(self, api: ApiCliente | None = None, telegram: bool = True,
                 intervalo: int = 90) -> None:
        self.api = api or ApiCliente()
        self.clf = Clasificador(self.api, con_ia=True)
        self.telegram = telegram
        self.intervalo = max(30, int(intervalo))
        self.bitacora_ok = set(self._leer_bitacora())

    # ------------------------------------------------------------- utilidades

    def _leer_bitacora(self) -> set[str]:
        """Folios ya resueltos por el resolver (no volver a procesarlos)."""
        res = set()
        if BITACORA.exists():
            for linea in BITACORA.read_text(encoding="utf-8").splitlines():
                if not linea.strip():
                    continue
                try:
                    o = json.loads(linea)
                    if o.get("reporte_id"):
                        res.add(o["reporte_id"])
                except Exception:
                    continue
        return res

    def _msg_telegram(self, texto: str) -> None:
        if not self.telegram:
            print("[resolver seco] " + texto.replace("\n", " | ")[:400])
            return
        try:
            from telegram_notificador import enviar
            enviar(texto)
        except Exception as exc:
            print(f"[resolver] telegram falló: {exc}")

    def _timbrar(self, rid: str, detalle: dict) -> None:
        detalle["ts"] = time.time()
        with BITACORA.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(detalle, ensure_ascii=False) + "\n")
        self.bitacora_ok.add(rid)

    def _puntuacion(self) -> dict:
        """Puntos del equipo + líder actuales (GET /tabla.json o /equipo)."""
        out = {"equipo": None, "lider": None}
        try:
            tabla = self.api.get("tabla.json")
            equipos = tabla.get("equipos", []) if isinstance(tabla, dict) else []
            eq = next((x for x in equipos if x.get("equipo_id") == "equipo02"), None)
            if eq:
                out["equipo"] = {"nombre": eq.get("nombre"), "puntos": eq.get("puntos"),
                                 "enviados": eq.get("enviados"), "publicados": eq.get("publicados")}
            if equipos:
                lider = max(equipos, key=lambda x: x.get("puntos") or 0)
                out["lider"] = {"nombre": lider.get("nombre"), "puntos": lider.get("puntos")}
        except Exception as exc:
            print(f"[resolver] no pude leer tabla: {exc}")
        return out

    # --------------------------------------------------------- análisis / caso

    def _contexto(self, pendiente: dict) -> dict:
        """Junta reporte + productor + parcela + transcripción."""
        rid = pendiente.get("reporte_id")
        reportes = _leer_json(CACHE / "reportes.json", [])
        reporte = next((r for r in reportes if r.get("id") == rid), {})
        parcelas = {p["id"]: p for p in _leer_json(CACHE / "parcelas.json", [])}
        productores = {p["id"]: p for p in _leer_json(CACHE / "productores.json", [])}
        parcela = parcelas.get(reporte.get("parcela_id") or "") or {}
        productor = productores.get(reporte.get("productor_id") or "") or {}
        texto = pendiente.get("texto") or reporte.get("texto") or ""
        return {"rid": rid, "reporte": reporte, "parcela": parcela, "productor": productor,
                "texto": texto, "motivo": pendiente.get("motivo", ""),
                "caso_cola": pendiente.get("caso", {})}

    def _es_seguimiento(self, ctx: dict) -> dict | None:
        """¿Seguimiento? (mismo productor/parcela <24 h sin visita, o respuesta_a,
        o texto con señal de seguimiento + productor que reportó hace poco)."""
        reporte = ctx["reporte"]
        if reporte.get("respuesta_a"):
            return {"padre": reporte.get("respuesta_a"), "ruta": "respuesta_a"}
        try:
            padre = self.clf._reporte_padre_por_ventana(reporte)
            if padre:
                return {"padre": padre.get("id"), "ruta": "ventana_24h"}
        except Exception:
            pass
        # Seguimiento por seña del texto + reporte reciente del mismo productor
        # (cubre casos donde la ventana oficial falla por visitas: R-2088).
        texto = (ctx["texto"] or "").lower()
        senal = any(f in texto for f in ("cuándo vienen", "cuando vienen",
                                         "ya se está pasando", "ya vieron",
                                         "otra vez", "sigo esperando"))
        if not senal:
            return None
        prod = reporte.get("productor_id")
        parcela = reporte.get("parcela_id")
        if not (prod or parcela):
            return None
        t_actual = _a_datetime(reporte.get("recibido"))
        if t_actual is None:
            return None
        reportes = _leer_json(CACHE / "reportes.json", [])
        limite = t_actual - __import__("datetime").timedelta(hours=24)
        candidatos = []
        for r in reportes:
            if r.get("id") == reporte.get("id"):
                continue
            mismo = ((parcela and r.get("parcela_id") == parcela)
                     or (prod and r.get("productor_id") == prod))
            if not mismo:
                continue
            t_r = _a_datetime(r.get("recibido"))
            if t_r is None or not (limite <= t_r <= t_actual):
                continue
            candidatos.append((t_r, r))
        if not candidatos:
            return None
        candidatos.sort(key=lambda x: x[0], reverse=True)
        return {"padre": candidatos[0][1].get("id"), "ruta": "texto_senal+productor"}

    def _texto_vago(self, ctx: dict) -> bool:
        """Texto sin señal de plaga identificable (prefiltro de vaguedad)."""
        texto = (ctx["texto"] or "").lower()
        frases = ("se ve fea", "se ve mal", "se está echando a perder",
                  "a perder", "le pasando a mi siembra", "algo le está pasando",
                  "no sé qué tiene", "anda pasando algo")
        return any(f in texto for f in frases)

    def _clasificar(self, ctx: dict) -> dict:
        """Reclasifica con el motor y devuelve {res, es_plaga, plaga, conf, motor, razon}."""
        try:
            res = self.clf.clasificar_reporte(ctx["reporte"])
        except Exception as exc:
            return {"error": str(exc)}
        return {"res": res, "es_plaga": bool(res.get("es_plaga")),
                "plaga": res.get("plaga") if res.get("es_plaga") else None,
                "conf": float(res.get("confianza") or 0),
                "motor": res.get("motor", ""), "razon": res.get("razon", "")}

    def _payload_seguimiento(self, ctx: dict, padre: dict | None) -> dict:
        return {"reporte_id": ctx["rid"], "es_plaga": True, "plaga": "desconocida"}

    # --------------------------------------------------------------- decisión

    def resolver_uno(self, pendiente: dict) -> dict:
        """Decide y (si es seguro) registra un dudoso. Devuelve resumen."""
        ctx = self._contexto(pendiente)
        rid = ctx["rid"]
        causa = ctx["caso_cola"]
        resumen = {"reporte_id": rid, "ts": time.time(),
                   "motivo": ctx["motivo"], "estado": "pendiente"}

        # --- 0) ¿ya lo resolvió el resolver antes? ---
        if rid in self.bitacora_ok:
            resumen["estado"] = "ya_resuelto"
            return resumen

        cultura = (ctx["parcela"] or {}).get("cultivo") or ""
        texto_vago = self._texto_vago(ctx)
        clf_res = self._clasificar(ctx)
        if clf_res.get("error"):
            resumen["estado"] = "error_motor"
            resumen["detalle"] = clf_res["error"]
            return resumen

        plaga = clf_res.get("plaga") or causa.get("plaga")
        seg = self._es_seguimiento(ctx)

        # --- 1) SEGUIMIENTO -> es_plaga+plaga (máx 2) ---
        if seg:
            payload = self._payload_seguimiento(ctx, seg)
            resumen["estimacion"] = 2
            resumen["payload"] = payload
            resumen["justificacion"] = (f"seguimiento ({seg['ruta']}, padre {seg['padre']}) → "
                                        f"la API solo califica es_plaga+plaga [{PRECEDENTES['seguimiento']['ref']}]")
            resumen["envio"] = True
            resumen["estado"] = "resuelto"
            return resumen

        # --- 2) TEXTO VAGO sin señales ---
        if texto_vago or plaga in (None, "desconocida"):
            predec = PRECEDENTES.get(("texto_vago", cultura))
            if predec is None:
                predec = {}  # cultivo sin precedente validado
            if predec.get("enviar"):
                payload = {"reporte_id": rid, "es_plaga": True, "plaga": "desconocida"}
                resumen["estimacion"] = predec.get("pts", 2)
                resumen["payload"] = payload
                resumen["justificacion"] = (
                    f"texto vago en {cultura}: 'desconocida' puntúa 2/2 "
                    f"[{predec['ref']}]")
                resumen["envio"] = True
                resumen["estado"] = "resuelto"
                return resumen
            # cultivo sin precedente claro (frijol, papa, haba, avena, etc.)
            resumen["estado"] = "revision_humana"
            resumen["justificacion"] = (
                f"texto vago en {cultura or 'cultivo desconocido'}: sin precedente "
                f"confirmado"
                + (f" — {predec.get('ref')}" if predec else ""))
            return resumen

        # --- 3) PLAGA CONOCIDA con señales -> nivel2 + brote completo ---
        try:
            from clasificador import resultados_a_casos
            reportes = _leer_json(CACHE / "reportes.json", [])
            caso_local = resultados_a_casos([ctx["reporte"]], self.clf)[0]
        except Exception as exc:
            resumen["estado"] = "error_caso"
            resumen["detalle"] = str(exc)
            return resumen

        payload = caso_para_api(caso_local)
        resumen["payload"] = payload
        resumen["estimacion"] = 5 if caso_local.get("semaforo") and caso_local.get("brote") is not None else 3
        conf = clf_res.get("conf", 0)
        # brote dudoso: solo auto si la regla de conjunto completo lo respalda
        if payload.get("brote") is not None and conf < BROTE_CONFIABLE and payload.get("brote"):
            # recalcular con conjunto completo (regla cluster 24 h)
            try:
                por_id = {r["id"]: r for r in reportes}
                brotes = self.clf.brotes_de_casos([caso_local], por_id)
                payload["brote"] = brotes.get(rid, payload.get("brote"))
            except Exception:
                pass

        resumen["envio"] = True
        resumen["estado"] = "resuelto"
        resumen["justificacion"] = (f"plaga {plaga} con señales · conf={round(conf, 2)} · "
                                    f"brote recalculado con conjunto completo")
        return resumen

    # --------------------------------------------------------------- registro

    def _registrar(self, rid: str, payload: dict) -> dict:
        """Registra en POST /casos y devuelve la respuesta oficial."""
        try:
            resp = self.api.registrar_caso(payload)
            return {"ok": True, "resp": resp}
        except ApiError as exc:
            d = exc.detalle
            if isinstance(d, dict) and "error" in d:
                d = d["error"]
            return {"ok": False, "error": json.dumps(d, ensure_ascii=False)[:400]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    # ------------------------------------------------------------- Telegram

    def _telegram_resultado(self, resumen: dict, registro: dict) -> None:
        rid = resumen.get("reporte_id")
        pts = self._puntuacion()
        eq = pts["equipo"] or {}
        lider = pts["lider"] or {}
        lineas = [f"🧠 <b>DUDOSO RESUELTO — {rid}</b>"]
        lineas.append(f"• <b>Motivo:</b> {resumen.get('motivo', '—')}")
        lineas.append(f"• <b>Qué se hizo:</b> {resumen.get('justificacion', '—')}")
        lineas.append(f"• <b>Estimación:</b> {resumen.get('estimacion', '—')} pts")
        if resumen.get("payload"):
            lineas.append(f"• <b>Payload:</b> <code>{json.dumps(resumen['payload'], ensure_ascii=False)}</code>")
        if registro.get("ok"):
            resp = registro.get("resp") or {}
            pts_ok = resp.get("puntos") if isinstance(resp, dict) else None
            det = resp.get("detalle") if isinstance(resp, dict) else None
            lineas.append(f"• <b>Resultado API:</b> ✅ {pts_ok} pts")
            if isinstance(det, dict):
                aciertos = [k for k, v in det.items() if v is True and k != "prioridad_sin_puntos"]
                lineas.append(f"• <b>Aciertos:</b> {', '.join(sorted(aciertos))}")
        else:
            lineas.append(f"• <b>Resultado API:</b> ❌ {registro.get('error', 'error')}")
        if eq:
            lineas.append(f"\n📊 <b>7_7:</b> {eq.get('puntos')} pts "
                          f"({eq.get('enviados')}/{eq.get('publicados')} enviados)")
        if lider:
            lineas.append(f"🏆 <b>Líder:</b> {lider.get('nombre')} — {lider.get('puntos')} pts")
        self._msg_telegram("\n".join(lineas))

    # ------------------------------------------------------------------ loop

    def revisar(self) -> int:
        """Procesa la cola completa en modo ANÁLISIS (sin enviar).

        Según decisión de Rafa (21-oct ~13:00): el resolver **NO registra nada
        en POST /casos** — solo re-analiza cada dudoso con el flujo validado,
        deja una marca de auditoría en la bitácora y **deja el caso en la cola**
        para revisión humana. Nada se envía automáticamente a la API.
        """
        cola = _leer_json(PENDIENTES, [])
        if not cola:
            return 0
        analizados = 0
        # No toca la cola: la conserva completa para que la gente decida.
        for pendiente in cola:
            rid = pendiente.get("reporte_id")
            resumen = self.resolver_uno(pendiente)
            resumen["registro"] = None  # nunca se registra
            self._timbrar(rid, resumen)
            decision = resumen.get("estado")
            print(f"[resolver] {rid}: {decision} — {resumen.get('justificacion', '')[:120]}")
            analizados += 1
        return analizados

    def correr(self) -> None:
        print(f"[resolver] modo ANÁLISIS | cada {self.intervalo}s | sin envíos")
        while True:
            try:
                n = self.revisar()
                if n:
                    print(f"[resolver] {n} dudoso(s) analizado(s) en esta pasada")
            except Exception:
                traceback.print_exc()
            time.sleep(self.intervalo)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Analiza la cola de dudosos 7_7 (sin enviar)")
    parser.add_argument("--una-vez", action="store_true", help="Una pasada y sale")
    parser.add_argument("--intervalo", type=int, default=90)
    args = parser.parse_args()
    resolver = ResolverCola(telegram=False, intervalo=args.intervalo)
    if args.una_vez:
        n = resolver.revisar()
        print(f"[resolver] dudosos analizados en esta pasada: {n}")
    else:
        resolver.correr()


if __name__ == "__main__":
    main()