"""
enviar_casos.py — Envío de casos a POST /casos con doble seguridad.

Flujo:
  1. Clasifica todos los reportes (determinista + IA si hay key válida).
  2. Valida el formato de cada caso con POST /casos/validar (no puntúa).
  3. Imprime resumen y pide confirmación ANTES de registrar (una sola
     oportunidad por reporte_id).
  4. Envía a POST /casos solo los casos aprobados.

Uso:
    python bot/enviar_casos.py               # plan + validar (dry-run)
    python bot/enviar_casos.py --enviar      # registra en la API (irreversible)
    python bot/enviar_casos.py --solo R-2002,R-2006   # subset por ids
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente, ApiError  # noqa: E402
from clasificador import Clasificador, caso_para_api, resultados_a_casos  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Envía casos a la API del hackathon")
    parser.add_argument("--enviar", action="store_true", help="Registra de verdad (irreversible)")
    parser.add_argument("--solo", default="", help="Solo estos reporte_id (coma): R-2002,R-2006")
    args = parser.parse_args()

    api = ApiCliente()
    clf = Clasificador(api, con_ia=True)  # IA si hay key válida; si no, determinista
    reportes = json.loads((RAIZ / "cache" / "reportes.json").read_text(encoding="utf-8"))

    if args.solo:
        ids = {s.strip() for s in args.solo.split(",") if s.strip()}
        reportes = [r for r in reportes if r["id"] in ids]

    casos = resultados_a_casos(reportes, clf)
    print(f"Casos a procesar: {len(casos)}")

    # 1) validar formato (no puntúa)
    ok, falla = 0, 0
    for c in casos:
        try:
            api.validar_caso(caso_para_api(c))
            ok += 1
        except ApiError as e:
            falla += 1
            print(f"  ERROR validando {c['reporte_id']}: {e}")
    print(f"Validación formato: {ok} OK / {falla} con fallo")

    # 2) resumen
    n_plaga = sum(1 for c in casos if c["es_plaga"])
    n_noplaga = sum(1 for c in casos if not c["es_plaga"])
    n_des = sum(1 for c in casos if c["es_plaga"] and c.get("plaga") == "desconocida")
    n_urg = sum(1 for c in casos if c.get("urgente"))
    con_sem = sum(1 for c in casos if c.get("semaforo"))
    con_tec = sum(1 for c in casos if c.get("tecnico_id"))
    con_brote = sum(1 for c in casos if c.get("brote") is True)
    print(f"  plaga identificada={n_plaga - n_des} | desconocida={n_des} | no_plaga={n_noplaga}")
    print(f"  con semáforo={con_sem} | con técnico={con_tec} | rojo/naranja={n_urg}"
          f" | brote={con_brote}")

    if not args.enviar:
        print("\n[DRY-RUN] No se registró nada. Agrega --enviar para registrar.")
        for c in casos:
            print(f"  {c['reporte_id']} es_plaga={c['es_plaga']} plaga={c['plaga']} "
                  f"sem={c.get('semaforo')} tec={c.get('tecnico_id')} pri={c.get('prioridad')} "
                  f"brote={c.get('brote')}")
        return

    # 3) confirmación
    print("\n⚠️  Estás por REGISTRAR casos en la API (una sola oportunidad por reporte).")
    resp = input("Escribe CONFIRMAR para continuar: ").strip()
    if resp != "CONFIRMAR":
        print("Cancelado.")
        return

    # 4) envío real
    enviados, errores = 0, 0
    for c in casos:
        try:
            r = api.registrar_caso(caso_para_api(c))
            print(f"  OK {c['reporte_id']} -> {json.dumps(r, ensure_ascii=False)[:160]}")
            enviados += 1
        except ApiError as e:
            errores += 1
            print(f"  ERROR {c['reporte_id']}: {e}")
    print(f"\nEnviados: {enviados} | errores: {errores}")


if __name__ == "__main__":
    main()
