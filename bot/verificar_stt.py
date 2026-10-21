"""
verificar_stt.py — Auditoría de transcripción: ¿qué modelo entiende mejor al productor?

Transcribe los audios más difíciles con varios modelos de speech-to-text y
compara resultados lado a lado. Sirve para decidir el modelo principal y el
de respaldo, y para medir cuánto se equivoca Whisper de verdad.

Uso:
    python bot/verificar_stt.py                # audios de prueba predefinidos
    python bot/verificar_stt.py R-2003 R-2055  # audios concretos
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from motor_audio_foto import MODELO_STT, descargar_media, transcribir_audio  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"

# audios con modismos o ruido detectados en la primera pasada
AUDIOS_PRUEBA = ["R-2003", "R-2005", "R-2012", "R-2013", "R-2025", "R-2030", "R-2055", "R-2053"]

MODELOS = [
    MODELO_STT,                    # openai/whisper-large-v3
    "openai/gpt-4o-transcribe",
    "openai/gpt-4o-mini-transcribe",
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    reportes = json.loads((CACHE / "reportes.json").read_text(encoding="utf-8"))
    ids = sys.argv[1:] or AUDIOS_PRUEBA

    salida = {}
    for rid in ids:
        rep = next((r for r in reportes if r["id"] == rid), None)
        if not rep or not rep.get("audio_url"):
            print(f"{rid}: sin audio, se omite")
            continue
        archivo = descargar_media(rep["audio_url"])
        print(f"\n=== {rid} ({rep.get('duracion_s')}s) ===")
        votos = {}
        for modelo in MODELOS:
            try:
                texto = transcribir_audio(archivo, modelo=modelo).strip()
                votos[modelo] = texto
                print(f"  [{modelo:<28}] {texto}")
            except Exception as exc:
                votos[modelo] = None
                print(f"  [{modelo:<28}] ERROR: {str(exc)[:110]}")
        salida[rid] = votos

    (CACHE / "stt_doble.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado en cache/stt_doble.json ({len(salida)} audios)")


if __name__ == "__main__":
    main()
