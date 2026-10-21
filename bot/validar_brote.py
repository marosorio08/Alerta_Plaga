"""
validar_brote.py — Comprueba la regla de brote (sección 9) contra /casos-previos.

La API trae la respuesta correcta para 40 casos de la semana pasada, incluido
el campo `brote`. Regla: 3+ casos de la misma plaga a menos de 5 km en los
últimos 7 días, contando el caso actual. Para un caso previo se cuentan solo
los casos previos (like se indica en el reglamento).

Uso:
    python bot/validar_brote.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nivel2 import contar_casos_cercanos, MINIMO_CASOS_BROTE  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


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
    if aciertos != len(previos):
        print(">> La regla no coincide con la respuesta oficial, revisar.")
        return 1
    print(">> La regla coincide con la respuesta oficial.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
