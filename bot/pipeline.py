"""
pipeline.py — Orquestador de los 5 pasos oficiales del Hackathon IT GREEN.

    PASO 1 RECIBIR     -> GET /reportes (ApiCliente) o un reporte ya descargado.
    PASO 2 INTERPRETAR -> IA (OpenRouter, JSON estricto) con respaldo a reglas.
    PASO 3 DECIDIR     -> reglas puras (nivel2): semaforo, tecnico_id, brote
                          + notificación push al coordinador (Telegram).
    PASO 4 GUARDAR     -> Supabase (si hay llaves) + caché local.
    PASO 5 REGISTRAR   -> POST /casos con el payload oficial
                          {reporte_id, es_plaga, plaga, semaforo, tecnico_id,
                           brote} + prioridad (opcional) para sumar los 5 pts.

Latencia: los pasos que NO puntúan (notificar y guardar) corren en un hilo;
el paso 5 (REGISTRAR) se ejecuta en línea, de inmediato. Cada paso tiene su
propio try/except para que un fallo nunca tumbe el siguiente.

Uso:
    python bot/pipeline.py --desde-api                    # lote completo (dry-run)
    python bot/pipeline.py --reporte R-2016 --interpretar-ia
    python bot/pipeline.py --desde-api --enviar --interpretar-ia   # registra
"""

from __future__ import annotations

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente, ApiError  # noqa: E402
from clasificador import (Clasificador, cargar_previos, caso_para_api,  # noqa: E402
                          resultados_a_casos)  # noqa: E402
from supabase_repositorio import RepositorioSupabase  # noqa: E402

_EJECUTOR = ThreadPoolExecutor(max_workers=4)


def _paralelo(fn) -> None:
    """Lanza fn en un hilo (notificación/guardado no bloquean el registro)."""
    try:
        _EJECUTOR.submit(fn)
    except Exception:
        threading.Thread(target=fn, daemon=True).start()


def recibir(api: ApiCliente, reporte_id: str | None = None) -> list[dict]:
    """PASO 1: consume GET /reportes (o devuelve un reporte concreto)."""
    reportes = api.get_reportes() or []
    if reporte_id:
        return [r for r in reportes if r["id"] == reporte_id]
    return reportes


def procesar(reporte: dict, clasif: Clasificador, *,
             casos_contexto: list[dict] | None = None,
             reportes_extra: dict | None = None,
             enviar: bool = False, notificar: bool = True,
             repo: RepositorioSupabase | None = None,
             api: ApiCliente | None = None) -> dict:
    """Ejecuta los 5 pasos para un reporte y devuelve el resultado."""
    api = api or ApiCliente()
    rid = reporte.get("id")
    paso1 = {"reporte_id": rid, "parcela_id": reporte.get("parcela_id"),
             "texto": (reporte.get("texto") or "")[:200],
             "recibido": reporte.get("recibido")}

    # ---------------- PASO 2: INTERPRETAR (IA estricta + respaldo) ----------
    try:
        res = clasif.clasificar_reporte(reporte)
    except Exception as exc:
        print(f"[pipeline] paso2 falló para {rid}, uso 'desconocida': {exc}")
        res = {"es_plaga": True, "plaga": "desconocida", "confianza": 0.0,
               "razon": f"paso2_error={exc}"}

    caso = {"reporte_id": rid, "es_plaga": bool(res.get("es_plaga")),
            "plaga": res.get("plaga") if res.get("es_plaga") else None,
            "seguimiento_de": res.get("seguimiento_de")}

    # ---------------- PASO 3: DECIDIR (reglas puras, NO IA) ----------------
    semaforo = tecnico_id = prioridad = None
    brote = False
    if (caso["es_plaga"] and caso["plaga"] and caso["plaga"] != "desconocida"
            and not res.get("seguimiento_de")):
        try:
            n2 = clasif.resolver_nivel2(reporte, caso["plaga"], res)
            if n2:
                semaforo, tecnico_id, prioridad = (n2["semaforo"],
                                                   n2["tecnico_id"],
                                                   n2["prioridad"])
        except Exception as exc:
            print(f"[pipeline] paso3 (nivel2) falló para {rid}: {exc}")
        try:
            contexto = [c for c in (casos_contexto or [])
                        if c.get("reporte_id") != rid]
            contexto.append(caso)
            por_id = dict(reportes_extra or {})
            por_id[rid] = reporte
            for c in contexto:
                por_id.setdefault(c.get("reporte_id"), {"id": c.get("reporte_id")})
            brotes = clasif.brotes_de_casos(contexto, por_id)
            brote = bool(brotes.get(rid))
        except Exception as exc:
            print(f"[pipeline] paso3 (brote) falló para {rid}: {exc}")

    caso.update({"semaforo": semaforo, "tecnico_id": tecnico_id,
                 "prioridad": prioridad, "brote": brote})
    caso["urgente"] = caso.get("semaforo") in ("rojo", "naranja") or bool(brote)
    decidir = {"semaforo": semaforo, "tecnico_id": tecnico_id,
               "prioridad": prioridad, "brote": brote, "urgente": caso["urgente"]}

    # Notificación push al coordinador (en hilo, no bloquea el registro)
    if notificar and caso["urgente"]:
        def _push() -> None:
            try:
                from telegram_notificador import alerta_caso

                plaga = next((p for p in clasif.plagas
                              if p.get("id") == caso.get("plaga")), None)
                parcela = clasif.parcelas.get(reporte.get("parcela_id") or "")
                alerta_caso(caso, plaga, parcela)
            except Exception as exc:
                print(f"[pipeline] push Telegram falló: {exc}")
        _paralelo(_push)

    # ---------------- PASO 4: GUARDAR (Supabase + caché, en hilo) -----------
    if repo is not None:
        def _guardar() -> None:
            try:
                repo.guardar_caso({
                    "reporte_id": rid, "caso": caso,
                    "confianza": res.get("confianza"),
                    "motor": res.get("motor"),
                    "razon": res.get("razon"),
                    "injection": bool(res.get("injection")),
                    "seguimiento_de": res.get("seguimiento_de"),
                })
            except Exception as exc:
                print(f"[pipeline] paso4 falló para {rid}: {exc}")
        _paralelo(_guardar)

    # ---------------- PASO 5: REGISTRAR (POST /casos) ----------------------
    registrado, respuesta = False, None
    if enviar and rid and rid.startswith("R-"):
        try:
            respuesta = api.registrar_caso(caso_para_api(caso))
            registrado = True
            print(f"[pipeline] REGISTRADO {rid} -> {str(respuesta)[:140]}")
        except ApiError as exc:
            print(f"[pipeline] paso5 falló para {rid}: {exc}")

    return {"paso1": paso1, "interpretar": {k: res.get(k) for k in
            ("es_plaga", "plaga", "pct_ia", "confianza", "motor", "razon", "injection")},
            "decidir": decidir, "caso": caso,
            "registrado": registrado, "respuesta": respuesta}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Pipeline 5 pasos IT GREEN")
    parser.add_argument("--desde-api", action="store_true", help="Todo GET /reportes")
    parser.add_argument("--reporte", default="", help="Un reporte R-XXXX")
    parser.add_argument("--enviar", action="store_true", help="POST /casos (irreversible)")
    parser.add_argument("--interpretar-ia", action="store_true",
                        help="Usar IA en el paso 2 (INTERPRETAR_IA=1)")
    parser.add_argument("--sin-notificar", action="store_true")
    args = parser.parse_args()

    import os

    if args.interpretar_ia:
        os.environ["INTERPRETAR_IA"] = "1"

    api = ApiCliente()
    clasif = Clasificador(api, con_ia=True)
    repo = RepositorioSupabase()

    reportes = recibir(api, args.reporte or None)
    previos = cargar_previos()
    casos_contexto = [
        {"reporte_id": p["reporte_id"], "es_plaga": True, "plaga": p["plaga"],
         "seguimiento_de": None}
        for p in previos]
    reportes_extra = {
        p["reporte_id"]: {"id": p["reporte_id"], "parcela_id": p.get("parcela_id"),
                          "recibido": p.get("recibido")}
        for p in previos}

    registrados = 0
    for r in reportes:
        resultado = procesar(r, clasif, casos_contexto=casos_contexto,
                             reportes_extra=reportes_extra,
                             enviar=args.enviar, notificar=not args.sin_notificar,
                             repo=repo, api=api)
        casos_contexto = [c for c in casos_contexto if c.get("reporte_id") != r["id"]] + [resultado["caso"]]
        caso = resultado["caso"]
        if resultado["registrado"]:
            registrados += 1
        print(f"  {caso['reporte_id']} plaga={str(caso.get('plaga')):<18} "
              f"sem={str(caso.get('semaforo')):<8} tec={str(caso.get('tecnico_id')):<5} "
              f"pri={caso.get('prioridad')} brote={bool(caso.get('brote'))}"
              f"{' [ENVIADO]' if resultado['registrado'] else ''}")
    print(f"\nReportes: {len(reportes)} | registrados: {registrados}")
    _EJECUTOR.shutdown(wait=False)


if __name__ == "__main__":
    main()