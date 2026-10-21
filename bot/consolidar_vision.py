"""consolidar_vision.py — Pasa el consenso de los 3 modelos a la caché multimedia."""

import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CACHE = Path(__file__).resolve().parent.parent / "cache"

multi = json.loads((CACHE / "multimedia.json").read_text(encoding="utf-8"))
doble = json.loads((CACHE / "vision_doble.json").read_text(encoding="utf-8"))

for rid, info in doble.items():
    votos = info["votos"]
    plagas = [v.get("plaga") for v in votos.values() if v.get("es_plaga") and v.get("plaga")]
    consenso = Counter(plagas).most_common(1)[0][0] if plagas else "desconocida"
    confs = [v.get("confianza") for v in votos.values() if isinstance(v.get("confianza"), (int, float))]
    multi[rid] = {
        "texto": "",
        "fuente": "vision",
        "es_plaga_sugerida": True,
        "plaga_sugerida": consenso,
        "confianza": round(sum(confs) / len(confs), 2) if confs else 0.8,
        "sintomas": "consenso 3 modelos: "
        + ", ".join(f"{k.split('/')[-1]}={v.get('plaga')}" for k, v in votos.items()),
        "consenso": len(set(plagas)) == 1 and len(plagas) == len(votos),
        "_cultivo": info["cultivo"],
        "_etapa": info["etapa"],
    }
    print(f"{rid} ({info['cultivo']}) -> {consenso} | unanime={multi[rid]['consenso']}")

(CACHE / "multimedia.json").write_text(
    json.dumps(multi, ensure_ascii=False, indent=2), encoding="utf-8"
)
