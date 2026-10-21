"""analizar_complementos.py — filtra los 14 candidatos: ¿realmente suman?

Criterio seguro (MEMORIA_VERIFICACION):
- Suman +1 por campo SI el reporte ABRE CASO NUEVO y la plaga es real.
- NO suman si es seguimiento (respuesta_a / mismo prod+parcela <24h / motivo
  "seguimiento") o si la plaga es "desconocida" (máx 2, la API no califica
  nivel 2 en esos casos).

Base: escaneo_resultado.json + reportes.json + bitácora servidor.
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

from nivel2 import _a_datetime  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"


def cargar(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d or {}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    resultado = cargar(CACHE / "escaneo_resultado.json")
    complementos = resultado.get("complementos", [])
    reportes = cargar(CACHE / "reportes.json", [])
    por_id = {r["id"]: r for r in reportes}

    # seguimientos conocidos declarados en bitácora
    seg_declarados: dict[str, str] = {}
    bf = CACHE / "listener_bitacora_servidor.jsonl"
    if bf.exists():
        for ln in bf.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            caso = o.get("caso") or {}
            rid = caso.get("reporte_id")
            if rid and caso.get("seguimiento_de"):
                seg_declarados[rid] = caso["seguimiento_de"]

    def es_seguimiento(rid: str) -> str | None:
        if rid in seg_declarados:
            return f"declarado seg de {seg_declarados[rid]}"
        r = por_id.get(rid) or {}
        if r.get("respuesta_a"):
            return f"respuesta_a={r['respuesta_a']}"
        # ventana 24h mismo productor/parcela
        t_actual = _a_datetime(r.get("recibido"))
        if not t_actual:
            return None
        limite = t_actual - timedelta(hours=24)
        for otro in reportes:
            if otro.get("id") == rid:
                continue
            if (r.get("productor_id") and otro.get("productor_id") == r.get("productor_id")) or \
               (r.get("parcela_id") and otro.get("parcela_id") == r.get("parcela_id")):
                t_o = _a_datetime(otro.get("recibido"))
                if t_o and limite <= t_o <= t_actual:
                    return f"ventana 24h con {otro['id']} (PR-{otro.get('productor_id')} P-{otro.get('parcela_id')})"
        return None

    print(f"{'RID':<8} {'plaga':<18} {'faltan':<28} {'¿abre caso?':<28} texto")
    print("-" * 120)
    recuperables: list[dict] = []
    for c in sorted(complementos, key=lambda x: x["rid"]):
        rid = c["rid"]
        r = por_id.get(rid) or {}
        texto = (r.get("texto") or "")[:60]
        seg = es_seguimiento(rid)
        plaga = c["plaga"]
        if plaga == "desconocida":
            juicio = "NO (plaga desconocida -> la API no califica nivel2)"
        elif seg:
            juicio = f"NO (seguimiento: {seg})"
        else:
            juicio = f"SÍ (+{len(c['agregables'])} potencial)"
            recuperables.append(c)
        print(f"{rid:<8} {plaga:<18} {','.join(c['agregables']):<28} {juicio:<28} {texto}")

    print(f"\n>>> COMPLEMENTOS QUE SÍ PUEDEN SUMAR: {len(recuperables)}")
    for c in recuperables:
        r = por_id.get(c["rid"]) or {}
        print(f"    {c['rid']} · {c['plaga']} · faltan {','.join(c['agregables'])} · "
              f"P-{r.get('parcela_id')} · PR-{r.get('productor_id')} · {str(r.get('texto'))[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())