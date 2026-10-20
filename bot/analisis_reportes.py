"""
analisis_reportes.py — Precarga y unión reportes + parcelas.

Paso 1 (análisis): cruza GET /reportes con GET /parcelas para
conocer el cultivo y etapa de cada parcela reportada, y muestra un
resumen que nos sirve para decidir las reglas deterministas.

Uso:
    python bot/analisis_reportes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"


def cargar(nombre: str) -> list:
    archivo = CACHE / f"{nombre}.json"
    if not archivo.exists():
        sys.exit(f"No existe cache/{nombre}.json. Ejecuta antes: python bot/descargar_catalogos.py --reportes")
    return json.loads(archivo.read_text(encoding="utf-8"))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    reportes = cargar("reportes")
    parcelas = {p["id"]: p for p in cargar("parcelas")}

    sin_parcela = [r for r in reportes if r["parcela_id"] not in parcelas]
    print(f"Reportes: {len(reportes)} | parcelas cargadas: {len(parcelas)} | sin parcela en catálogo: {len(sin_parcela)}")

    # Tabla resumen: reporte -> cultivo
    filas = []
    for r in reportes:
        p = parcelas.get(r["parcela_id"])
        filas.append(
            (
                r["id"],
                r["tipo"] or "?",
                r["parcela_id"] or "?",
                r["productor_id"] or "?",
                p["cultivo"] if p else "??",
                p["etapa"] if p else "??",
            )
        )

    ancho = max(len(str(f[0])) for f in filas)
    print(f"\n{'reporte':<{ancho}} {'tipo':<6} {'parcela':<8} {'productor':<9} {'cultivo':<18} {'etapa'}")
    for r, t, pa, pr, c, e in filas:
        print(f"{str(r):<{ancho}} {str(t):<6} {str(pa):<8} {str(pr):<9} {str(c):<18} {str(e)}")

    # Conteo por cultivo
    from collections import Counter

    print("\nConteo de reportes por cultivo de la parcela:")
    for cultivo, n in Counter(f[4] for f in filas).most_common():
        print(f"  {cultivo:<18} {n}")


if __name__ == "__main__":
    main()
