"""escaneo_puntos.py — Barrido seguro de todos los reportes publicados.

Objetivo: encontrar puntos que se nos hayan escapado (complementos +3).
Protocolo (MEMORIA_VERIFICACION §3): POST /casos/validar NO registra y
devuelve "ya_registrado_antes" + qué campos agregables faltan.

Para cada caso enviado con plaga (de la bitácora del servidor), consulta el
estado real y detecta:
  1. COMPLEMENTO (+3): registrado con "todavía le pueden agregar: ..."
  2. SIN REGISTRAR: publicado pero no enviado (puntos en riesgo).

NO registra NADA. Solo informa.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

from api_cliente import ApiCliente, ApiError  # noqa: E402
from clasificador import caso_para_api  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
BITACORA_SERVER = CACHE / "listener_bitacora_servidor.jsonl"
BITACORA_LOCAL = CACHE / "listener_bitacora.jsonl"


def ahora() -> str:
    return datetime.now().strftime("%H:%M:%S")


def cargar_json(p, defecto):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    api = ApiCliente()
    tabla = api.get("tabla.json")
    eqs = {e["equipo_id"]: e for e in tabla.get("equipos", [])}
    eq = eqs.get("equipo02") or {}
    lider = eqs.get("equipo07") or {}
    print(f"7_7  = {eq.get('puntos')}/{eq.get('maximo_posible')} "
          f"({eq.get('enviados')}/{eq.get('publicados')}) err={eq.get('errores_total')}")
    print(f"MISA = {lider.get('puntos')} err={lider.get('errores_total')} "
          f"diferencia={lider.get('puntos') - eq.get('puntos')}")

    # ---- reconstruct casos enviados desde la bitácora (payload real) ----
    casos_env: dict[str, dict] = {}
    for bf in (BITACORA_SERVER, BITACORA_LOCAL):
        if not bf.exists():
            continue
        for linea in bf.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            try:
                o = json.loads(linea)
            except json.JSONDecodeError:
                continue
            caso = o.get("caso") or {}
            rid = caso.get("reporte_id") or o.get("reporte_id")
            if not rid or rid.endswith("-R"):
                continue
            if not caso.get("es_plaga"):
                continue
            # último procesamiento gana
            casos_env[rid] = {
                "reporte_id": rid,
                "es_plaga": bool(caso.get("es_plaga")),
                "plaga": caso.get("plaga"),
                "semaforo": caso.get("semaforo"),
                "tecnico_id": caso.get("tecnico_id"),
                "brote": caso.get("brote"),
                "peso_directo": 5 if (caso.get("semaforo") and caso.get("brote") is not None) else 3,
            }
    print(f"casos con plaga reconstruidos desde bitácora: {len(casos_env)}")

    reportes = cargar_json(CACHE / "reportes.json", [])
    publicado = [r["id"] for r in reportes if not r["id"].endswith("-R")]
    print(f"reportes publicados (sin -R): {len(publicado)}")

    # ---- escaneo validar_caso sobre cada uno ----
    complementos: list[dict] = []
    por_registrar: list[dict] = []
    con_confirmaciones = 0
    errores_validar = 0
    for rid in sorted(publicado):
        caso = casos_env.get(rid)
        if not caso:
            continue
        payload = caso_para_api(caso)
        try:
            st = api.validar_caso(payload)
        except ApiError as exc:
            errores_validar += 1
            print(f"  [{ahora()}] {rid} validar ERROR: {str(exc)[:80]}")
            continue
        time.sleep(0.15)
        if not isinstance(st, dict):
            continue
        ya = bool(st.get("ya_registrado_antes"))
        mensaje = str(st.get("mensaje") or "")
        agregables = [c for c in ("brote", "semaforo", "tecnico_id") if c in mensaje]
        if ya and agregables:
            # complemento potencial: faltan campos que se pueden reenviar
            complementos.append({"rid": rid, "agregables": agregables,
                                 "plaga": caso.get("plaga"),
                                 "payload_actual": payload})
        elif not ya:
            por_registrar.append({"rid": rid, "plaga": caso.get("plaga"),
                                  "mensaje": mensaje[:120]})
        else:
            con_confirmaciones += 1

    print(f"\n=== RESULTADO ===")
    print(f"revisados: {len(publicado)} | validar errores: {errores_validar}")
    print(f"complementos potenciales (+3): {len(complementos)}")
    for c in complementos:
        print(f"  {c['rid']} plaga={c['plaga']} faltan={','.join(c['agregables'])}")
    print(f"no registrados en la API: {len(por_registrar)}")
    for c in por_registrar:
        print(f"  {c['rid']} plaga={c['plaga']} -> {c['mensaje']}")

    # guardar resultados para análisis posterior
    Path(CACHE / "escaneo_resultado.json").write_text(
        json.dumps({"complementos": complementos, "por_registrar": por_registrar},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())