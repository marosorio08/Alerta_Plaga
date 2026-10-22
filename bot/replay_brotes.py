"""
replay_brotes.py - Replay offline del modelo de brote con datos reales.

No llama a la API y no registra nada. Compara cuatro variantes:
  * propuestos_productor : comportamiento histórico (todos los casos locales).
  * confirmados_productor: solo previos + casos confirmados (ledger).
  * confirmados_parcela  : confirmados, dedupe por productor+parcela 24 h.
  * confirmados_sin_dedupe: confirmados, regla pura sin dedupe.

Fuentes:
  cache/cache_casos_previos.json        verdad oficial (40 casos)
  cache/listener_bitacora_servidor.jsonl casos reales ya procesados
  cache/reportes.json y cache/parcelas.json

Limitación: para los casos propios no hay una etiqueta oficial por caso. El
replay mide cambios de decisión y verifica los 5 casos documentados, no una
exactitud inventada.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clasificador import Clasificador  # noqa: E402
from nivel2 import decidir_brote  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
BITACORA = CACHE / "listener_bitacora_servidor.jsonl"

CASOS_REALES_ESPERADOS = {
    "R-2043": False,
    "R-2055": True,
    "R-2070": True,
    "R-2073": True,
    "R-2084": True,
}


def cargar_json(nombre: str, defecto):
    try:
        return json.loads((CACHE / nombre).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defecto


def cargar_bitacora(ruta: Path) -> dict[str, dict]:
    """Unifica las entradas de la bitácora por reporte.

    Las respuestas/complementos no crean casos propios. Si hay una plaga
    concreta en cualquier entrada, esa manda sobre "desconocida".
    """
    por_rid: dict[str, dict] = {}
    if not ruta.exists():
        return por_rid
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            o = json.loads(linea)
        except json.JSONDecodeError:
            continue
        rid = o.get("reporte_id")
        caso = o.get("caso") or {}
        if not rid or not caso:
            continue
        # Las respuestas `-R` no son casos propios: aportan parcela/texto al
        # padre y no compiten en el conteo.
        es_respuesta = str(rid).endswith("-R")
        es_complemento = bool(o.get("complemento")) or o.get("entrada_id") != rid
        padre = caso.get("seguimiento_de")
        if es_respuesta and padre:
            destino = por_rid.setdefault(str(padre), {
                "reporte_id": str(padre), "es_plaga": False, "plaga": None,
                "seguimiento_de": None, "recibido": None, "parcela_id": None,
            })
            if o.get("parcela_id"):
                destino["parcela_id"] = o["parcela_id"]
            continue
        actual = por_rid.setdefault(rid, {
            "reporte_id": str(rid),
            "es_plaga": False,
            "plaga": None,
            "seguimiento_de": None,
            "recibido": None,
            "parcela_id": None,
        })
        if caso.get("es_plaga"):
            actual["es_plaga"] = True
        if caso.get("plaga") and caso["plaga"] != "desconocida":
            actual["plaga"] = caso["plaga"]
        if caso.get("seguimiento_de") and not es_complemento:
            actual["seguimiento_de"] = caso["seguimiento_de"]
        if o.get("recibido") and not actual["recibido"]:
            actual["recibido"] = o["recibido"]
        if o.get("parcela_id"):
            actual["parcela_id"] = o["parcela_id"]
    return por_rid


def construir_dataset(ruta_bitacora: Path):
    previos = cargar_json("cache_casos_previos.json", [])
    crudos = cargar_json("reportes.json", [])
    parcelas = {p["id"]: p for p in cargar_json("parcelas.json", [])}
    reportes_cache = {r["id"]: r for r in crudos}
    bitacora = cargar_bitacora(ruta_bitacora)

    casos: list[dict] = []
    reportes: dict[str, dict] = {}
    for rid, c in bitacora.items():
        reporte = dict(reportes_cache.get(rid) or {})
        parcela_id = c.get("parcela_id") or reporte.get("parcela_id")
        reporte["id"] = rid
        reporte["parcela_id"] = parcela_id
        reporte["recibido"] = c.get("recibido") or reporte.get("recibido")
        if not reporte.get("productor_id") and parcela_id in parcelas:
            reporte["productor_id"] = parcelas[parcela_id].get("productor_id")
        reportes[rid] = reporte
        casos.append({
            "reporte_id": rid,
            "es_plaga": c.get("es_plaga"),
            "plaga": c.get("plaga"),
            "seguimiento_de": c.get("seguimiento_de"),
        })
    return previos, casos, reportes, parcelas


def referencia(caso: dict, reporte: dict, parcelas: dict) -> dict | None:
    parcela_id = reporte.get("parcela_id")
    parcela = parcelas.get(parcela_id or "") or {}
    try:
        lat, lon = float(parcela["lat"]), float(parcela["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not caso.get("plaga") or caso["plaga"] == "desconocida":
        return None
    if caso.get("seguimiento_de"):
        return None
    return {
        "reporte_id": caso["reporte_id"],
        "plaga": caso["plaga"],
        "lat": lat,
        "lon": lon,
        "recibido": reporte.get("recibido"),
        "productor_id": reporte.get("productor_id"),
        "parcela_id": parcela_id,
        "seguimiento_de": None,
        "propio": True,
    }


def evaluar_previos(previos: list[dict], clf: Clasificador) -> dict[str, int]:
    """La verdad oficial no tiene casos propios: todas las variantes dan 40/40."""
    from nivel2 import MINIMO_CASOS_BROTE, contar_casos_cercanos
    refs = [
        {"plaga": p["plaga"], "lat": p["lat"], "lon": p["lon"],
         "recibido": p.get("recibido")}
        for p in previos
        if p.get("plaga") and p["plaga"] != "desconocida"
        and p.get("lat") is not None and p.get("lon") is not None
    ]
    resultados = {}
    for nombre, kwargs in {
        "oficial": {},
        "sin_dedupe": {"dedupe_productor_propios": False},
        "parcela": {"dedupe_por_parcela": True},
    }.items():
        ok = 0
        for p in previos:
            n = contar_casos_cercanos(p["plaga"], p["lat"], p["lon"],
                                      p.get("recibido"), refs, **kwargs)
            ok += (n >= MINIMO_CASOS_BROTE) == bool(p.get("brote"))
        resultados[nombre] = ok
    return resultados


def simular(casos: list[dict], reportes: dict[str, dict], previos: list[dict],
            parcelas: dict, modo: str, clf: Clasificador,
            confirmar_todos: bool = False) -> dict:
    """Procesa los casos en orden de recibido y compara con el histórico.

    Política conservadora: los casos con n != 2 se consideran confirmados
    (False se envía, True se aprueba). Los n=2 quedan aparcados y NO cuentan
    para los siguientes, que es justo el agujero que tapa el ledger.

    ``confirmar_todos=True`` asume que todos los casos reales de la bitácora
    fueron confirmados por la API. Sirve para medir regresiones históricas:
    con la misma base, el modelo nuevo debe decidir igual que el viejo.
    """
    confirmados: dict[str, dict] = {}
    prior: list[dict] = []
    filas: list[dict] = []
    distintos = 0
    sin_n = 0

    kwargs = {}
    if modo == "confirmados_parcela":
        kwargs["dedupe_por_parcela"] = True
    elif modo == "confirmados_sin_dedupe":
        kwargs["sin_dedupe"] = True

    for c in sorted(casos, key=lambda x: str(reportes.get(x["reporte_id"], {}).get("recibido") or "")):
        rid = c["reporte_id"]
        reporte = reportes.get(rid) or {}
        # Histórico: todos los casos anteriores + actual.
        info_viejo = clf.evaluar_brotes(
            prior + [c], reportes, previos=previos, confirmados=None,
        ).get(rid)
        # Estricto: previos + confirmados + actual.
        if modo == "propuestos_productor":
            info_nuevo = info_viejo
        else:
            info_nuevo = clf.evaluar_brotes(
                [c], reportes, previos=previos,
                confirmados=confirmados, **kwargs,
            ).get(rid)
        if not info_viejo or not info_nuevo:
            prior.append(c)
            sin_n += 1
            continue
        dec_viejo = decidir_brote(info_viejo["n"])
        dec_nuevo = decidir_brote(info_nuevo["n"])
        if dec_viejo != dec_nuevo:
            distintos += 1
            filas.append({
                "reporte_id": rid,
                "recibido": reporte.get("recibido"),
                "plaga": c.get("plaga"),
                "n_viejo": info_viejo["n"],
                "n_nuevo": info_nuevo["n"],
                "decision_vieja": dec_viejo,
                "decision_nueva": dec_nuevo,
            })
        if modo != "propuestos_productor" and (confirmar_todos or dec_nuevo is not None):
            ref = referencia(c, reporte, parcelas)
            if ref:
                confirmados[rid] = ref
        prior.append(c)

    return {
        "modo": modo,
        "casos": len(prior),
        "sin_n": sin_n,
        "confirmados": len(confirmados) if modo != "propuestos_productor" else len(prior),
        "distintos": distintos,
        "filas": filas,
    }


def evaluar_casos_reales(casos: list[dict], reportes: dict[str, dict],
                         previos: list[dict], parcelas: dict,
                         clf: Clasificador) -> dict[str, dict]:
    """Reconstruye los 5 casos documentados con el ledger completo."""
    por_rid = {c["reporte_id"]: c for c in casos}
    refs = {
        c["reporte_id"]: referencia(c, reportes.get(c["reporte_id"]) or {}, parcelas)
        for c in casos
    }
    refs = {rid: ref for rid, ref in refs.items() if ref}
    salida = {}
    for rid, esperado in CASOS_REALES_ESPERADOS.items():
        caso = por_rid.get(rid)
        if not caso:
            salida[rid] = {"esperado": esperado, "n": None, "decision": None,
                           "ok": False, "nota": "no está en la bitácora"}
            continue
        confirmados = {k: v for k, v in refs.items() if k != rid}
        info = clf.evaluar_brotes([caso], reportes, previos=previos,
                                  confirmados=confirmados, descartados=set()).get(rid)
        if not info:
            salida[rid] = {"esperado": esperado, "n": None, "decision": None,
                           "ok": False, "nota": "no elegible (seguimiento/sin parcela)"}
            continue
        decision = decidir_brote(info["n"])
        ok = decision == esperado
        salida[rid] = {"esperado": esperado, "n": info["n"],
                       "decision": decision, "ok": ok}
    return salida


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Replay offline de brotes")
    parser.add_argument("--bitacora", type=Path, default=BITACORA)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--detalle", action="store_true",
                        help="Lista todos los casos que cambian de decisión")
    args = parser.parse_args()

    previos, casos, reportes, parcelas = construir_dataset(args.bitacora)
    clf = Clasificador.__new__(Clasificador)
    clf.parcelas = parcelas

    if not casos:
        print(f"No hay casos en {args.bitacora}")
        return 1

    previos_ok = evaluar_previos(previos, clf)
    reales = evaluar_casos_reales(casos, reportes, previos, parcelas, clf)
    modos = [
        "propuestos_productor",
        "confirmados_productor",
        "confirmados_parcela",
        "confirmados_sin_dedupe",
    ]
    resultados_hist = [
        simular(casos, reportes, previos, parcelas, m, clf, confirmar_todos=True)
        for m in modos
    ]
    resultados_cola = [
        simular(casos, reportes, previos, parcelas, m, clf, confirmar_todos=False)
        for m in modos
    ]

    if args.json:
        print(json.dumps({
            "previos": previos_ok,
            "casos_reales": reales,
            "historico": resultados_hist,
            "cola_n2": resultados_cola,
        }, ensure_ascii=False, indent=2))
        return 0

    print("=" * 76)
    print("REPLAY DE BROTES - datos reales (sin API, sin registrar)")
    print("=" * 76)
    print(f"Previos oficiales: {len(previos)}")
    for nombre, ok in previos_ok.items():
        print(f"  {nombre:<12} {ok}/{len(previos)}")
    print(f"\nCasos de la bitácora: {len(casos)} únicos")
    con_coords = sum(
        1 for c in casos
        if (reportes.get(c['reporte_id'], {}).get('parcela_id') in parcelas)
        and c.get("plaga") and c["plaga"] != "desconocida"
    )
    print(f"  con plaga y parcela: {con_coords}")
    print(f"  seguimientos: {sum(1 for c in casos if c.get('seguimiento_de'))}")

    print("\nCasos reales documentados (verdad de la API):")
    for rid, info in reales.items():
        marca = "OK" if info["ok"] else "FAIL"
        nota = f" ({info['nota']})" if info.get("nota") else ""
        print(f"  {marca:<4} {rid}: esperado={info['esperado']} "
              f"n={info['n']} decision={info['decision']}{nota}")

    for titulo, resultados in (
        ("A) HISTÓRICO: todos los casos reales ya confirmados (sin regresión)",
         resultados_hist),
        ("B) COLA: los n=2 aparcados NO se confirman (peor caso conservador)",
         resultados_cola),
    ):
        print(f"\n{titulo}")
        print(f"  {'variante':<26} {'casos':>6} {'conf.':>6} {'n!=2':>6} {'cambios':>8}")
        for r in resultados:
            print(f"  {r['modo']:<26} {r['casos']:>6} {r['confirmados']:>6} "
                  f"{r['sin_n']:>6} {r['distintos']:>8}")
        for r in resultados[1:]:
            cambios = [f for f in r["filas"] if f["decision_vieja"] != f["decision_nueva"]]
            print(f"  {r['modo']}: {len(cambios)} caso(s)")
            if args.detalle:
                for f in cambios:
                    print(f"    {f['reporte_id']:<7} {str(f['plaga']):<18} "
                          f"n {f['n_viejo']}->{f['n_nuevo']} "
                          f"{f['decision_vieja']}->{f['decision_nueva']} "
                          f"{(f['recibido'] or '')[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
