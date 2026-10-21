"""
generar_casos.py — Recalcula cache/casos_propuestos.json con el clasificador actual.

Lo consume el dashboard (app_web) para pintar estados y urgencias. No envía
nada a la API: es solo la propuesta local.

Uso:
    python bot/generar_casos.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente  # noqa: E402
from clasificador import Clasificador, resultados_a_casos  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    archivo_reportes = CACHE / "reportes.json"
    reportes = json.loads(archivo_reportes.read_text(encoding="utf-8"))

    clf = Clasificador(ApiCliente(), con_ia=True)
    casos = resultados_a_casos(reportes, clf)

    salida = CACHE / "casos_propuestos.json"
    salida.write_text(json.dumps(casos, ensure_ascii=False, indent=2), encoding="utf-8")

    plaga = sum(1 for c in casos if c["es_plaga"] and c["plaga"] != "desconocida")
    desc = sum(1 for c in casos if c["es_plaga"] and c["plaga"] == "desconocida")
    nop = sum(1 for c in casos if not c["es_plaga"])
    urg = sum(1 for c in casos if c["urgente"])
    print(f"{len(casos)} casos -> {salida.name}")
    print(f"  plaga identificada={plaga}  desconocida={desc}  no_plaga={nop}  urgentes={urg}")


if __name__ == "__main__":
    main()
