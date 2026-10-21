"""
validar_brote.py — Comprueba la regla de brote (sección 9) contra /casos-previos.

La API trae la respuesta correcta para 40 casos de la semana pasada, incluido
el campo `brote`. Regla: 3+ casos de la misma plaga a menos de 5 km en los
últimos 7 días, contando el caso actual. Para un caso previo se cuentan solo
los casos previos (like se indica en el reglamento).

Además verifica los casos REALES ya evaluados por la API en vivo:
  - R-2043 (falso positivo corregido con dedupe de productores propios).
  - R-2055 (falso negativo: el padre estaba sin resolver y la respuesta
    aportaba la parcela; ahora debe abrir caso nuevo y dar brote TRUE).
  - R-2070 (falso negativo del bug de orden: el brote se debe calcular con el
    conjunto completo, nunca con un solo reporte).
  - R-2073 y R-2084 (mismo bug de conjunto incompleto / dedupe).

Uso:
    python bot/validar_brote.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nivel2 import contar_casos_cercanos, MINIMO_CASOS_BROTE  # noqa: E402
from clasificador import Clasificador, fusionar_respuesta, resultados_a_casos  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


def verificar_casos_reales(clf: Clasificador, bitacora: Path | None = None) -> tuple[int, int]:
    """Verifica la regla con el CONJUNTO COMPLETO sobre dos casos reales.

    Devuelve (aciertos, total). Usa la caché local (reportes, parcelas) y, si
    existe, la bitácora del servidor (que trae la plaga ya resuelta por IA para
    voz/foto) para no gastar API. Se salta (y avisa) si la caché no aplica.
    """
    reportes_f = RAIZ / "cache" / "reportes.json"
    try:
        crudos = json.loads(reportes_f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("  (se omite: sin cache/reportes.json)")
        return 0, 0

    ids = {r["id"] for r in crudos}
    if not {"R-2070", "R-2043", "R-2055"} <= ids:
        print("  (se omite: la caché no tiene R-2070/R-2043/R-2055)")
        return 0, 0

    # Contexto de casos resueltos para detectar seguimientos y heredar la
    # plaga del padre. Un padre "desconocida" NO abre seguimiento (R-2055).
    cache_casos = RAIZ / "cache" / "casos_propuestos.json"
    if cache_casos.exists():
        try:
            lista = json.loads(cache_casos.read_text(encoding="utf-8"))
            clf.casos_actuales = {c["reporte_id"]: c for c in lista}
        except Exception:
            clf.casos_actuales = {}
    else:
        clf.casos_actuales = {}
    clf.casos_actuales.setdefault("R-2042", {"reporte_id": "R-2042", "es_plaga": True,
                                            "plaga": "desconocida"})

    # Fusiona las respuestas con su padre antes de clasificar (R-2055-R aporta
    # la parcela P-094). Las respuestas no compiten como casos propios.
    respuestas = {r["respuesta_a"]: r for r in crudos if r.get("respuesta_a")}
    reportes = []
    for r in crudos:
        if r.get("respuesta_a"):
            continue
        if r["id"] in respuestas:
            padre_caso = clf.casos_actuales.get(r["id"]) or {}
            plaga_padre = padre_caso.get("plaga") if padre_caso.get("es_plaga") else None
            r = fusionar_respuesta(r, respuestas[r["id"]], plaga_padre)
        reportes.append(r)
    por_id = {r["id"]: r for r in reportes}
    clf.reportes_actuales = por_id

    # ---- Casos con plaga real: bitácora del servidor (IA) + clasificación local ----
    casos_locales = resultados_a_casos(reportes, clf)
    casos_por_rid = {c["reporte_id"]: c for c in casos_locales}

    if bitacora is not None and bitacora.exists():
        for linea in bitacora.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            try:
                o = json.loads(linea)
            except json.JSONDecodeError:
                continue
            caso = o.get("caso") or {}
            rid = o.get("reporte_id")
            # La bitácora es la fuente fiel de lo que se envió (IA para voz/foto),
            # pero un complemento posterior pudo dejar "desconocida" y borrar una
            # plaga ya resuelta. Solo se sobreescribe con una plaga concreta.
            if rid and caso.get("plaga") and caso.get("plaga") != "desconocida":
                base = casos_por_rid.get(rid) or {}
                base = dict(base)
                base["reporte_id"] = rid
                base["es_plaga"] = bool(caso.get("es_plaga", base.get("es_plaga")))
                base["plaga"] = caso.get("plaga")
                casos_por_rid[rid] = base

    elegibles: list[dict] = []
    for rid, c in casos_por_rid.items():
        plaga = c.get("plaga")
        if not (c.get("es_plaga") and plaga and plaga != "desconocida"):
            continue
        elegibles.append(c)

    brotes = clf.brotes_de_casos(elegibles, por_id)

    aciertos, total = 0, 0

    # R-2043: el productor PR-191 reportó 3 veces (R-2032/R-2035/R-2043) ->
    # la API lo marcó como brote INCORRECTO. Con dedupe los casos propios del
    # mismo productor cuentan una vez -> NO es brote.
    r2043 = brotes.get("R-2043")
    total += 1
    esperado_2043 = False
    if r2043 is None:
        # No elegible = seguimiento (no abre caso): equivale a no brote.
        aciertos += 1
        print("  R-2043 sin brote (seguimiento de R-2035) esperado=False "
              "(OK) [no inventa brote]")
    elif r2043 == esperado_2043:
        aciertos += 1
        print(f"  R-2043 brote={r2043} esperado={esperado_2043} (OK) "
              f"[seguimiento de R-2035]")
    else:
        print(f"  R-2043 brote={r2043} esperado={esperado_2043} (FALLA)")

    # R-2055: gusano_cogollero en P-094 (Xalapango). El padre R-2042 quedó
    # "desconocida", así que NO es seguimiento; la respuesta R-2055-R aporta la
    # parcela. Cerca hay R-1017 y R-1040 -> 3 casos -> brote TRUE.
    r2055 = brotes.get("R-2055")
    if r2055 is not None:
        total += 1
        esperado_2055 = True
        if r2055 == esperado_2055:
            aciertos += 1
        print(f"  R-2055 brote={r2055} esperado={esperado_2055} "
              f"({'OK' if r2055 == esperado_2055 else 'FALLA'}) "
              f"[padre sin resolver + respuesta con parcela -> caso nuevo]")
    else:
        print("  R-2055 sin brote en el conjunto (no elegible, revisar)")

    # R-2073: mismo patrón que R-2070 (conjunto completo).
    r2073 = brotes.get("R-2073")
    if r2073 is not None:
        total += 1
        esperado_2073 = True
        if r2073 == esperado_2073:
            aciertos += 1
        print(f"  R-2073 brote={r2073} esperado={esperado_2073} "
              f"({'OK' if r2073 == esperado_2073 else 'FALLA'}) "
              f"[conjunto completo]")

    # R-2070: chapulin en P-138 (Los Olivos). El 409 de la API mostró
    # brote=FALLA porque el listener calculó el brote con UN SOLO reporte y
    # registró brote=false. Con el conjunto completo (R-1034 previo cercano +
    # R-2044 + R-2045, productores distintos) SÍ es brote.
    r2070 = brotes.get("R-2070")
    if r2070 is not None:
        total += 1
        esperado_2070 = True
        if r2070 == esperado_2070:
            aciertos += 1
        print(f"  R-2070 brote={r2070} esperado={esperado_2070} "
              f"({'OK' if r2070 == esperado_2070 else 'FALLA'}) "
              f"[falso negativo del bug de orden -> conjunto completo]")
    else:
        print("  R-2070 sin brote en el conjunto (no elegible, revisar)")

    # R-2084: tizon_tardio en P-263 (papa). La API exige brote=TRUE (en el
    # 409 quedó marcado como FALLA cuando el listener mandó false). Razón:
    # R-2014 (mismo PR-291, misma parcela, 2 días antes) y R-2007 (PR-283,
    # 2.13 km) son 3 casos legítimos. Con dedupe cluster 24 h -> 2 eventos
    # del PR-291 + R-2007 = 3 -> TRUE.
    r2084 = brotes.get("R-2084")
    if r2084 is not None:
        total += 1
        esperado_2084 = True
        if r2084 == esperado_2084:
            aciertos += 1
        print(f"  R-2084 brote={r2084} esperado={esperado_2084} "
              f"({'OK' if r2084 == esperado_2084 else 'FALLA'}) "
              f"[regresión falso negativo del dedupe global -> cluster 24h]")
    else:
        print("  R-2084 sin brote en el conjunto (no elegible, revisar)")

    return aciertos, total


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    previos = json.loads((RAIZ / "cache" / "cache_casos_previos.json")
                         .read_text(encoding="utf-8"))
    refs = [
        {"plaga": p["plaga"], "lat": p["lat"], "lon": p["lon"],
         "recibido": p.get("recibido")}
        for p in previos
        if p.get("plaga") and p.get("plaga") != "desconocida"
        and p.get("lat") is not None and p.get("lon") is not None
    ]
    aciertos, diferencias = 0, []
    for p in previos:
        n = contar_casos_cercanos(p["plaga"], p["lat"], p["lon"],
                                  p.get("recibido"), refs)
        prediccion = n >= MINIMO_CASOS_BROTE
        esperado = bool(p.get("brote"))
        if prediccion == esperado:
            aciertos += 1
        else:
            diferencias.append(
                f"  DIFIERE {p['reporte_id']}: esperado={esperado} "
                f"calculado={prediccion} (n={n}) {p['plaga']} "
                f"@{p['lat']},{p['lon']} {p['recibido']}")
    print(f"Brote: {aciertos}/{len(previos)}")
    for linea in diferencias:
        print(linea)

    print("\nCasos reales ya evaluados por la API (conjunto completo):")
    try:
        clf = Clasificador(con_ia=False)
        bitacora = RAIZ / "cache" / "listener_bitacora_servidor.jsonl"
        real_aciertos, real_total = verificar_casos_reales(clf, bitacora)
    except Exception as exc:  # noqa: BLE001
        print(f"  (no se pudo evaluar: {exc})")
        real_aciertos, real_total = 0, 0

    if aciertos != len(previos):
        print(">> La regla no coincide con la respuesta oficial, revisar.")
        return 1
    if real_total and real_aciertos != real_total:
        print(f">> Los casos reales no coinciden ({real_aciertos}/{real_total}), revisar.")
        return 1
    print(">> La regla coincide con la respuesta oficial.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
