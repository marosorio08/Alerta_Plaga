"""
evaluar_caso.py — Evalúa un reporte con el motor real SIN registrar nada.

Uso:
    python bot/evaluar_caso.py R-2117
    python bot/evaluar_caso.py R-2117 --json

Sirve para revisar a mano un caso nuevo antes de decidir si se envía. No hace
POST /casos; solo lee la API, calcula y muestra el payload propuesto.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente  # noqa: E402
from clasificador import Clasificador, caso_para_api, decidir_brote, resultados_a_casos  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"


def cargar_json(nombre: str, defecto):
    try:
        return json.loads((CACHE / nombre).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evalúa un reporte sin registrarlo")
    parser.add_argument("reporte_id")
    parser.add_argument("--json", action="store_true", help="Salida JSON")
    args = parser.parse_args()

    api = ApiCliente()
    reporte = api.get(f"reportes/{args.reporte_id}")
    if not reporte or not reporte.get("id"):
        print(f"No encontré {args.reporte_id}")
        return 1

    clf = Clasificador(api, con_ia=False)
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
        for c in cargar_json("casos_propuestos.json", [])
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
        print(f"  seguimiento_de: {salida['seguimiento_de']}")
        for ref in salida["refs_brote"]:
            actual = " (actual)" if ref.get("es_actual") else ""
            print(f"    - {ref.get('reporte_id')} {ref.get('plaga')} "
                  f"{ref.get('distancia_km')} km {ref.get('recibido')}{actual}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
