"""validar_nivel2.py — Comprueba las fórmulas REALES de nivel2.py contra
GET /casos-previos, que trae prioridad, semáforo y técnico correctos.

Uso:
    python bot/validar_nivel2.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente
from nivel2 import calcular_prioridad, calcular_semaforo, elegir_tecnico


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    api = ApiCliente()
    casos = api.get("casos-previos") or []
    parcelas = {p["id"]: p for p in api.get_parcelas()}
    plagas = {p["id"]: p for p in api.get_plagas()}
    print(f"Casos previos: {len(casos)}")

    ok_pri = ok_sem = ok_tec = total = 0
    for c in casos:
        parcela = parcelas.get(c["parcela_id"])
        plaga = plagas.get(c["plaga"])
        if not parcela or not plaga:
            continue
        total += 1
        pct = c.get("pct") if c.get("pct") is not None else 10
        prioridad = calcular_prioridad(plaga, parcela, pct)
        semaforo = calcular_semaforo(prioridad)
        tecnicos = api.get("tecnicos", {"momento": c["recibido"]}) or []
        tecnico = elegir_tecnico(tecnicos, plaga, parcela)

        ok_pri += prioridad == c.get("prioridad")
        ok_sem += semaforo == c.get("semaforo")
        ok_tec += tecnico == c.get("tecnico_id")
        if (prioridad, semaforo, tecnico) != (c.get("prioridad"), c.get("semaforo"), c.get("tecnico_id")):
            print(f"  dif {c['reporte_id']}: pri {prioridad}/{c.get('prioridad')} · "
                  f"sem {semaforo}/{c.get('semaforo')} · tec {tecnico}/{c.get('tecnico_id')}")

    print(f"\nPrioridad: {ok_pri}/{total}   Semáforo: {ok_sem}/{total}   Técnico: {ok_tec}/{total}")
    if total and (ok_pri, ok_sem, ok_tec) != (total, total, total):
        sys.exit(1)


if __name__ == "__main__":
    main()
