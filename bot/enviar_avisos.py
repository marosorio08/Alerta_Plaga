"""
enviar_avisos.py — Lote de AVISOS REALES (POST /avisos) para el reto extra.

Envía, para los casos ya clasificados:
  * asignación al técnico + folio al productor (casos con semáforo),
  * alerta cuarentenaria a sanidad vegetal (HLB / gorgojo khapra),
  * aviso de brote a los productores vecinos del mismo cultivo.

No toca puntos: los avisos NO se califican en POST /casos; son la parte del
20 % de retos extra y la demo del viernes.

Uso:
    python bot/enviar_avisos.py            # envía de verdad (--real no hace falta)
    python bot/enviar_avisos.py --seco     # solo imprime lo que haría
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente  # noqa: E402
from clasificador import Clasificador, resultados_a_casos  # noqa: E402
from extras import Extras  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Avisos reales del reto extra")
    parser.add_argument("--seco", action="store_true", help="Solo imprimir")
    args = parser.parse_args()

    api = ApiCliente()
    clf = Clasificador(api, con_ia=True)
    extras = Extras(api, seco=args.seco)

    reportes = json.loads((RAIZ / "cache" / "reportes.json").read_text(encoding="utf-8"))
    productores = {p["id"]: p for p in api.get_productores()}
    previos = api.get("casos-previos") or []
    casos = resultados_a_casos(reportes, clf)
    por_mensaje = {r["id"]: r for r in reportes}

    cont = 0
    # --- asignación + folio + cuarentenarias (casos con semáforo) ---
    for c in casos:
        if not c.get("es_plaga") or not c.get("semaforo"):
            continue
        r = por_mensaje.get(c["reporte_id"]) or {}
        plaga = next((p for p in clf.plagas if p.get("id") == c.get("plaga")), None)
        parcela = clf.parcelas.get(r.get("parcela_id") or "")
        if not plaga or not parcela:
            continue
        extras.avisar_asignacion(c, plaga, parcela, r.get("productor_id"))
        extras.avisar_cuarentenaria(c, plaga, parcela)
        cont += 2 if c.get("tecnico_id") else 1

    # --- brotes: aviso a vecinos del mismo cultivo < 5 km ---
    enriquecidos = []
    for c in casos:
        r = por_mensaje.get(c["reporte_id"]) or {}
        copia = dict(c)
        copia["recibido"] = r.get("recibido")
        copia["parcela_id"] = r.get("parcela_id")
        enriquecidos.append(copia)
    brotes = extras.detectar_brotes(enriquecidos, clf.parcelas, previos)
    for b in brotes:
        extras.avisar_brote(b, clf.parcelas, productores)
        cont += 1

    print(f"Avisos preparados/enviados: {cont} | modo: {'seco' if args.seco else 'REAL'}")


if __name__ == "__main__":
    main()