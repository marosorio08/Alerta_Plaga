"""
procesar_multimedia.py — Procesa en lote todos los reportes de voz y foto.

Transcribe los .ogg con Whisper y analiza las .jpg con visión, guardando
el resultado en cache/multimedia.json para no repetir llamadas (y ahorrar
tokens). Reanudable: salta lo ya procesado con --reanudar.

Uso:
    python bot/procesar_multimedia.py
    python bot/procesar_multimedia.py --reanudar
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clasificador import Clasificador  # noqa: E402
from motor_audio_foto import procesar_reporte_multimedia  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
SALIDA = CACHE / "multimedia.json"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reanudar", action="store_true", help="Saltar los ya procesados")
    args = parser.parse_args()

    clf = Clasificador(con_ia=True)
    reportes = json.loads((CACHE / "reportes.json").read_text(encoding="utf-8"))
    pendientes = [r for r in reportes if r["tipo"] in ("voz", "foto")]

    resultados: dict = {}
    if SALIDA.exists():
        resultados = json.loads(SALIDA.read_text(encoding="utf-8"))

    for i, r in enumerate(pendientes, 1):
        rid = r["id"]
        if args.reanudar and rid in resultados and not resultados[rid].get("error"):
            continue
        parcela = clf.parcelas.get(r.get("parcela_id") or "", {})
        cultivo = parcela.get("cultivo", "")
        etapa = parcela.get("etapa", "")
        t0 = time.time()
        res = procesar_reporte_multimedia(r, cultivo, etapa)
        res["_cultivo"] = cultivo
        res["_etapa"] = etapa
        res["_segundos"] = round(time.time() - t0, 1)
        resultados[rid] = res
        estado = res.get("error") or res.get("fuente")
        print(f"[{i}/{len(pendientes)}] {rid} {r['tipo']:<5} {cultivo:<18} {estado} {res['_segundos']}s")
        if res.get("texto"):
            print(f"      txt: {res['texto'][:120]}")
        if res.get("fuente") == "vision":
            print(f"      vision: es_plaga={res.get('es_plaga_sugerida')} plaga={res.get('plaga_sugerida')} "
                  f"({res.get('confianza')}) {str(res.get('sintomas'))[:90]}")
        SALIDA.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nTotal procesados: {len(resultados)} -> {SALIDA}")


if __name__ == "__main__":
    main()
