"""
probar_brotes.py - Pruebas de invariantes del modelo de brote con ledger.

No usa API ni registra nada. Verifica:
  * el dedupe por productor vs el dedupe por parcela,
  * que un caso NO confirmado no cuente,
  * que un caso descartado no cuente,
  * que los confirmados congelados manden sobre la clasificación local,
  * la política conservadora de n=2.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clasificador import Clasificador  # noqa: E402
from confirmados import confirmar  # noqa: E402
from nivel2 import contar_casos_cercanos, decidir_brote  # noqa: E402

BASE = "2026-10-21T10:00:00-06:00"
PARCELAS = {
    "P-1": {"lat": 19.5000, "lon": -98.8800},
    "P-2": {"lat": 19.5010, "lon": -98.8800},
    "P-3": {"lat": 19.5020, "lon": -98.8800},
}
REPORTES = {
    "R-A": {"id": "R-A", "parcela_id": "P-1", "productor_id": "PR-1",
            "recibido": "2026-10-20T10:00:00-06:00"},
    "R-B": {"id": "R-B", "parcela_id": "P-2", "productor_id": "PR-2",
            "recibido": "2026-10-21T08:00:00-06:00"},
    "R-C": {"id": "R-C", "parcela_id": "P-3", "productor_id": "PR-3",
            "recibido": BASE},
    "R-X": {"id": "R-X", "parcela_id": "P-1", "productor_id": "PR-9",
            "recibido": BASE},
}


def caso(rid: str, plaga: str = "pulgon", seguimiento: str | None = None) -> dict:
    return {"reporte_id": rid, "es_plaga": True, "plaga": plaga,
            "seguimiento_de": seguimiento}


def ref(rid: str, plaga: str = "pulgon") -> dict:
    return {"reporte_id": rid, "plaga": plaga, "lat": PARCELAS[REPORTES[rid]["parcela_id"]]["lat"],
            "lon": PARCELAS[REPORTES[rid]["parcela_id"]]["lon"],
            "recibido": REPORTES[rid]["recibido"],
            "productor_id": REPORTES[rid]["productor_id"],
            "parcela_id": REPORTES[rid]["parcela_id"], "propio": True}


def main() -> int:
    fallos = 0

    def revisar(nombre: str, condicion: bool, detalle: str = "") -> None:
        nonlocal fallos
        if not condicion:
            fallos += 1
        print(f"  {'OK ' if condicion else 'FAIL'} {nombre}{(' -> ' + detalle) if detalle else ''}")

    print("[1] Dedupe: productor vs parcela")
    refs_mismo_prod = [
        {"plaga": "pulgon", "lat": 19.5000, "lon": -98.8800,
         "recibido": "2026-10-20T10:00:00-06:00", "propio": True,
         "prod": "PR-1", "parcela_id": "P-1"},
        {"plaga": "pulgon", "lat": 19.5010, "lon": -98.8800,
         "recibido": "2026-10-21T08:00:00-06:00", "propio": True,
         "prod": "PR-1", "parcela_id": "P-2"},
        {"plaga": "pulgon", "lat": 19.5020, "lon": -98.8800,
         "recibido": "2026-10-21T09:00:00-06:00", "propio": True,
         "prod": "PR-1", "parcela_id": "P-3"},
    ]
    n_prod = contar_casos_cercanos("pulgon", 19.5000, -98.8800, BASE,
                                   refs_mismo_prod, dedupe_productor_propios=True)
    n_parc = contar_casos_cercanos("pulgon", 19.5000, -98.8800, BASE,
                                   refs_mismo_prod, dedupe_productor_propios=True,
                                   dedupe_por_parcela=True)
    revisar("mismo productor en 3 parcelas se colapsa (productor)", n_prod == 1, f"n={n_prod}")
    revisar("mismo productor en 3 parcelas NO se colapsa (parcela)", n_parc == 3, f"n={n_parc}")

    clf = Clasificador.__new__(Clasificador)
    clf.parcelas = dict(PARCELAS)
    confirmados = {"R-A": ref("R-A"), "R-B": ref("R-B")}

    print("\n[2] Ledger: solo cuentan los confirmados")
    info = clf.evaluar_brotes([caso("R-C")], REPORTES, previos=[],
                              confirmados=confirmados, descartados=set())
    revisar("A+B confirmados + C actual -> n=3", info["R-C"]["n"] == 3,
            f"n={info['R-C']['n']}")
    revisar("C se marca brote", info["R-C"]["brote"] is True)

    info = clf.evaluar_brotes([caso("R-C")], REPORTES, previos=[],
                              confirmados={"R-A": ref("R-A")}, descartados=set())
    revisar("B no confirmado no cuenta -> n=2", info["R-C"]["n"] == 2,
            f"n={info['R-C']['n']}")
    revisar("n=2 queda en zona gris (no se envía)", decidir_brote(info["R-C"]["n"]) is None)

    info = clf.evaluar_brotes([caso("R-C")], REPORTES, previos=[],
                              confirmados=confirmados, descartados={"R-B"})
    revisar("B descartado no cuenta -> n=2", info["R-C"]["n"] == 2,
            f"n={info['R-C']['n']}")

    print("\n[3] Datos congelados y exclusiones de la regla")
    congelado = {}
    confirmar(congelado, caso("R-A"), REPORTES["R-A"], PARCELAS)
    confirmar(congelado, caso("R-A", "roya_frijol"), REPORTES["R-A"], PARCELAS)
    revisar("no reescribe una plaga concreta ya congelada",
            congelado["R-A"]["plaga"] == "pulgon",
            f"plaga={congelado['R-A']['plaga']}")
    congelados = {"R-A": ref("R-A"), "R-B": ref("R-B", "roya_frijol")}
    info = clf.evaluar_brotes([caso("R-C")], REPORTES, previos=[],
                              confirmados=congelados, descartados=set())
    revisar("la plaga congelada manda (B=roya no suma a pulgon)",
            info["R-C"]["n"] == 2, f"n={info['R-C']['n']}")

    info = clf.evaluar_brotes([caso("R-C", seguimiento="R-A")], REPORTES, previos=[],
                              confirmados=confirmados, descartados=set())
    revisar("seguimiento actual no se evalúa", "R-C" not in info)

    REPORTES["R-NO"] = {"id": "R-NO", "parcela_id": "P-1", "productor_id": "PR-9",
                        "recibido": "2026-10-21T09:00:00-06:00"}
    info = clf.evaluar_brotes([caso("R-NO", plaga="desconocida")], REPORTES, previos=[],
                              confirmados=confirmados, descartados=set())
    revisar("plaga desconocida no se evalúa", "R-NO" not in info)

    print(f"\nResultado: {'TODO OK' if fallos == 0 else str(fallos) + ' fallo(s)'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
