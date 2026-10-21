"""
verificar_vision.py — Doble opinión para las fotos ambiguas.

Pregunta a dos modelos de visión distintos y compara. Si coinciden, se usa
esa plaga; si difieren, el clasificador la enviará como "desconocida".

Uso:
    python bot/verificar_vision.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clasificador import Clasificador  # noqa: E402
from motor_audio_foto import describir_foto, descargar_media  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
MODELOS = [
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash",
    "openai/gpt-4o",
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    clf = Clasificador(con_ia=True)
    reportes = json.loads((RAIZ / "cache" / "reportes.json").read_text(encoding="utf-8"))
    fotos = [r for r in reportes if r["tipo"] == "foto"]

    salida: dict = {}
    for r in fotos:
        parcela = clf.parcelas.get(r.get("parcela_id") or "", {})
        cultivo, etapa = parcela.get("cultivo", ""), parcela.get("etapa", "")
        candidatas = sorted(clf.cultivares_compatibles(cultivo))
        archivo = descargar_media(r["foto_url"])
        votos = {}
        for modelo in MODELOS:
            try:
                res = describir_foto(archivo, cultivo, etapa, candidatas)
                votos[modelo] = {
                    "es_plaga": res.get("es_plaga"),
                    "plaga": res.get("plaga"),
                    "confianza": res.get("confianza"),
                    "sintomas": str(res.get("sintomas"))[:70],
                }
            except Exception as exc:
                votos[modelo] = {"error": str(exc)[:120]}
        salida[r["id"]] = {"cultivo": cultivo, "etapa": etapa, "votos": votos}

        plagas = [v.get("plaga") for v in votos.values() if v.get("es_plaga") and v.get("plaga")]
        consenso = max(set(plagas), key=plagas.count) if plagas else None
        print(f"\n{r['id']}  {cultivo} ({etapa})  candidatas={candidatas}")
        for modelo, v in votos.items():
            print(f"   {modelo:<24} -> {v.get('plaga') if 'error' not in v else v['error']}")
        print(f"   CONSENSO: {consenso}  (votos: {plagas})")

    (RAIZ / "cache" / "vision_doble.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
