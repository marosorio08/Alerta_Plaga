"""
analizar_brotes.py — Toma TODOS los reportes con brote, analiza las respuestas
correctas de /casos-previos, y verifica la regla actual contra:
  1. los 40 previos (verdad oficial),
  2. los casos REALES que la API ya evaluó (nuestros errores documentados),
  3. los reportes de esta semana con valor de brote en la caché del servidor.

Imprime el patrón encontrado y las diferencias. NO registra nada.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

from nivel2 import contar_casos_cercanos, distancia_km, MINIMO_CASOS_BROTE, RADIO_BROTE_KM, VENTANA_BROTE_HORAS  # noqa: E402
from clasificador import Clasificador, resultados_a_casos  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"


def cargar(nombre):
    try:
        return json.loads((CACHE / nombre).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  (no pude cargar {nombre}: {exc})")
        return []


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    previos = cargar("cache_casos_previos.json")
    reportes = cargar("reportes.json")
    por_id = {r["id"]: r for r in reportes}

    # ---------- 1) PATRÓN en los casos previos (verdad oficial) ----------
    print("=" * 78)
    print("1) BROTES OFICIALES en /casos-previos (40 casos)")
    print("=" * 78)
    brotes_previos = [p for p in previos if p.get("brote")]
    no_brotes_previos = [p for p in previos if not p.get("brote")]
    print(f"Con brote=True: {len(brotes_previos)}  |  brote=False: {len(no_brotes_previos)}")

    refs = [
        {"plaga": p["plaga"], "lat": p["lat"], "lon": p["lon"],
         "recibido": p.get("recibido")}
        for p in previos
        if p.get("plaga") and p.get("plaga") != "desconocida"
        and p.get("lat") is not None and p.get("lon") is not None
    ]

    print(f"\n--- Distribución por plaga (brote=True) ---")
    por_plaga: dict[str, int] = {}
    for p in brotes_previos:
        por_plaga[p["plaga"]] = por_plaga.get(p["plaga"], 0) + 1
    for plaga, n in sorted(por_plaga.items(), key=lambda x: -x[1]):
        print(f"  {plaga:<20} {n} caso(s)")

    print(f"\n--- Vecinos dentro de {RADIO_BROTE_KM:.1f} km para cada brote oficial ---")
    for p in brotes_previos:
        vecinos = []
        for q in refs:
            if q["plaga"] != p["plaga"]:
                continue
            if q.get("recibido") == p.get("recibido"):
                continue
            try:
                d = distancia_km(p["lat"], p["lon"], q["lat"], q["lon"])
            except Exception:
                continue
            if d < RADIO_BROTE_KM:
                t_p = q.get("recibido", "")[:10]
                t_q = q.get("recibido", "")[:10]
                vecinos.append((d, t_p, t_q))
        vecinos.sort()
        n_vec = len(vecinos)
        print(f"  {p['reporte_id']:<7} {p['plaga']:<18} P-{p.get('parcela_id','?'):<6} "
              f"-> {n_vec} vecino(s) <5km | {p.get('recibido','')[:10]}")

    # ---------- 2) ¿La regla actual reproduce la verdad? ----------
    print("\n" + "=" * 78)
    print("2) REGLA ACTUAL vs VERDAD OFICIAL (previos)")
    print("=" * 78)
    aciertos, total = 0, 0
    for p in previos:
        n = contar_casos_cercanos(p["plaga"], p["lat"], p["lon"],
                                  p.get("recibido"), refs, dedupe_productor_propios=False)
        pred = n >= MINIMO_CASOS_BROTE
        esperado = bool(p.get("brote"))
        total += 1
        marca = "OK " if pred == esperado else "FAIL"
        if pred == esperado:
            aciertos += 1
        else:
            print(f"  {marca} {p['reporte_id']}: esperado={esperado} calculado={pred} (n={n})")
    print(f"Previos: {aciertos}/{total}")

    # ---------- 3) Nuestros casos fallidos REALES (la API ya los evaluó) ----------
    print("\n" + "=" * 78)
    print("3) CASOS REALES FALLIDOS (la API ya los evaluó) — ¿qué diría la regla hoy?")
    print("=" * 78)
    clf = Clasificador(con_ia=False)
    bitacora = CACHE / "listener_bitacora_servidor.jsonl"
    casos_locales = resultados_a_casos(reportes, clf)
    casos_por_rid = {c["reporte_id"]: c for c in casos_locales}
    if bitacora.exists():
        for linea in bitacora.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            try:
                o = json.loads(linea)
            except Exception:
                continue
            rid = o.get("reporte_id")
            caso = o.get("caso") or {}
            if rid and caso.get("plaga"):
                base = dict(casos_por_rid.get(rid) or {})
                base["reporte_id"] = rid
                base["es_plaga"] = bool(caso.get("es_plaga", base.get("es_plaga")))
                base["plaga"] = caso.get("plaga")
                casos_por_rid[rid] = base

    elegibles = [c for c in casos_por_rid.values()
                 if c.get("es_plaga") and c.get("plaga")
                 and c.get("plaga") != "desconocida"]
    brotes_calc = clf.brotes_de_casos(elegibles, por_id)

    casos_reales = {
        # (folio, plaga esperada por la API según la memoria)
        "R-2043": False,   # falso positivo (dedupe) -> API NO brote
        "R-2055": True,    # regla conservadora -> API SÍ brote
        "R-2070": True,    # bug de orden -> API SÍ brote
        "R-2073": True,    # bug de orden -> API SÍ brote
        "R-2084": True,    # dedupe global -> API SÍ brote
    }
    for rid, esperado in casos_reales.items():
        calc = brotes_calc.get(rid)
        if calc is None:
            print(f"  {rid:<7} sin calcular (¿no elegible?)")
            continue
        marca = "OK  " if calc == esperado else "FAIL"
        print(f"  {marca} {rid}: esperado={esperado} calculado={calc}")

    # ---------- 4) Nuestros reportes de hoy con brote calculado ----------
    print("\n" + "=" * 78)
    print("4) REPORTES NUESTROS que la regla marca como BROTE (conjunto completo)")
    print("=" * 78)
    con_brote = [rid for rid, v in brotes_calc.items() if v]
    con_brote.sort()
    for rid in con_brote:
        c = casos_por_rid.get(rid) or {}
        r = por_id.get(rid) or {}
        print(f"  {rid:<7} {str(c.get('plaga')):<18} P-{str(r.get('parcela_id') or '?'):<6} "
              f"{str(r.get('tipo') or '?'):<4} {str(r.get('recibido') or '')[:10]}")
    print(f"\nTotal casos con brote en nuestro cálculo: {len(con_brote)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())