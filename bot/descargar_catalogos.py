"""
descargar_catalogos.py — Ingesta y caché local de los catálogos.

Paso 1 del plan: baja /plagas, /parcelas, /productores y /tecnicos
y los guarda en cache/ para que el clasificador trabaje sin red.

Uso:
    python bot/descargar_catalogos.py [--reportes]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"


def guardar(nombre: str, datos) -> None:
    CACHE.mkdir(exist_ok=True)
    archivo = CACHE / f"{nombre}.json"
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  OK {nombre}.json  ({len(datos)} registros) -> {archivo.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga los catálogos de la API IT GREEN")
    parser.add_argument("--reportes", action="store_true", help="Incluir también GET /reportes")
    args = parser.parse_args()

    api = ApiCliente()
    print("Descargando catálogos desde", api.base_url)

    guardar("plagas", api.get_plagas())
    guardar("parcelas", api.get_parcelas())
    guardar("productores", api.get_productores())
    guardar("tecnicos", api.get_tecnicos())
    if args.reportes:
        guardar("reportes", api.get_reportes())


if __name__ == "__main__":
    main()
