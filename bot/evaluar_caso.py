"""
evaluar_caso.py — Evalúa un reporte con el motor real SIN registrar nada.

Usa el MISMO motor que el agente de producción: consenso híbrido Reglas + IA
(INTERPRETAR_IA=2) y, para voz/foto, STT/visión con consenso. Así lo que ves
aquí es lo que el listener calcularía, no una aproximación solo-reglas.

Uso:
    python bot/evaluar_caso.py R-2117
    python bot/evaluar_caso.py R-2117 --json
    python bot/evaluar_caso.py R-2117 --sin-ia    # comparar solo reglas

Sirve para revisar a mano un caso nuevo antes de decidir si se envía. No hace
POST /casos; solo lee la API, calcula y muestra el payload propuesto.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente  # noqa: E402
from clasificador import Clasificador, caso_para_api, decidir_brote, resultados_a_casos  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
# En el servidor el agente comparte los casos con el dashboard por CASOS_SALIDA.
CASOS = Path(os.getenv("CASOS_SALIDA") or (CACHE / "casos_propuestos.json"))


def cargar_json(archivo: Path, defecto):
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except Exception:
        return defecto


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evalúa un reporte sin registrarlo")
    parser.add_argument("reporte_id")
    parser.add_argument("--json", action="store_true", help="Salida JSON")
    parser.add_argument("--sin-ia", action="store_true",
                        help="Solo reglas (sin consenso híbrido), para comparar")
    args = parser.parse_args()

    api = ApiCliente()
    reporte = api.get(f"reportes/{args.reporte_id}")
    if not reporte or not reporte.get("id"):
        print(f"No encontré {args.reporte_id}")
        return 1

    # Igual que el listener: consenso híbrido con IA (INTERPRETAR_IA=2).
    clf = Clasificador(api, con_ia=not args.sin_ia)
    try:
        clf.recargar_catalogo()
    except Exception as exc:
        print(f"[aviso] catálogo sin refrescar: {exc}")

    reportes = api.get_reportes()
    por_id = {r["id"]: r for r in reportes}
    if reporte["id"] not in por_id:
        por_id[reporte["id"]] = reporte

    # Contexto de casos propios ya clasificados (caché compartida).
    casos_cache = {
        c["reporte_id"]: c
        for c in cargar_json(CASOS, [])
        if c.get("reporte_id")
    }
    clf.casos_actuales = dict(casos_cache)
    clf.reportes_actuales = por_id

    res = clf.clasificar_reporte(reporte)
    caso = resultados_a_casos([reporte], clf)[0]
    # El brote se recalcula con el conjunto completo (previos + propios).
    casos_cache[reporte["id"]] = caso
    detalles = clf.evaluar_brotes(list(casos_cache.values()), por_id)
    info = detalles.get(reporte["id"], {"n": None, "refs": [], "brote": False})
    decision = decidir_brote(info.get("n"))
    if decision is None:
        caso.pop("brote", None)
        caso["_brote_dudoso"] = True
    else:
        caso["brote"] = decision
        # El cálculo inicial (un solo reporte) pudo marcarlo como zona gris;
        # al recalcular con el conjunto completo la decisión ya es firme.
        caso.pop("_brote_dudoso", None)

    salida = {
        "reporte_id": reporte["id"],
        "payload_propuesto": caso_para_api(caso),
        "n_brote": info.get("n"),
        "refs_brote": info.get("refs", []),
        "brote_dudoso": bool(caso.get("_brote_dudoso")),
        "injection": bool(res.get("injection")),
        "motor": res.get("motor"),
        "confianza": res.get("confianza"),
        "razon": res.get("razon"),
        "pct": res.get("pct_ia"),
        "modo_ia": "solo reglas (--sin-ia)" if args.sin_ia
                   else f"consenso híbrido IA (INTERPRETAR_IA={os.getenv('INTERPRETAR_IA', '2')})",
        "seguimiento_de": res.get("seguimiento_de"),
        "parcela_id": reporte.get("parcela_id"),
        "texto": reporte.get("texto"),
    }
    if args.json:
        print(json.dumps(salida, ensure_ascii=False, indent=2))
    else:
        print(f"Reporte {salida['reporte_id']}")
        print(f"  payload: {json.dumps(salida['payload_propuesto'], ensure_ascii=False)}")
        print(f"  n_brote: {salida['n_brote']}  dudoso: {salida['brote_dudoso']}")
        print(f"  injection: {salida['injection']}  motor: {salida['motor']}  conf: {salida['confianza']}")
        print(f"  modo: {salida['modo_ia']}")
        print(f"  razon: {salida['razon']}")
        print(f"  seguimiento_de: {salida['seguimiento_de']}")
        for ref in salida["refs_brote"]:
            actual = " (actual)" if ref.get("es_actual") else ""
            print(f"    - {ref.get('reporte_id')} {ref.get('plaga')} "
                  f"{ref.get('distancia_km')} km {ref.get('recibido')}{actual}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
