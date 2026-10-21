"""inspeccionar_api.py â€” Muestra parÃ¡metros y esquemas nuevos de la API."""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
spec = json.loads((Path(__file__).resolve().parent.parent / "cache" / "openapi.json").read_text(encoding="utf-8"))

for ruta in ["/tecnicos", "/visitas", "/avisos", "/preguntas", "/reportes"]:
    for metodo, info in spec["paths"][ruta].items():
        print(f"{metodo.upper()} {ruta} | {info.get('summary')}")
        for prm in info.get("parameters", []):
            sch = prm.get("schema", {})
            print(f"   param: {prm['name']} | {prm.get('description', '')[:120]} | {sch.get('type') or sch.get('anyOf')}")
        cuerpo = info.get("requestBody")
        if cuerpo:
            ref = cuerpo["content"]["application/json"]["schema"].get("$ref", "")
            print("   body:", ref.split("/")[-1])
    print()

for nombre in ["Aviso", "Pregunta", "Visita", "Tecnico", "ReporteEnVivo"]:
    if nombre in spec["components"]["schemas"]:
        print(f"SCHEMA {nombre}:")
        print(json.dumps(spec["components"]["schemas"][nombre], ensure_ascii=False, indent=1)[:1100])
        print()
