"""
confirmados.py - Fuente de verdad para la regla de brote.

La API solo puede contar los casos que realmente recibió por POST /casos.
Este módulo mantiene un *ledger* local e inmutable de esos casos confirmados
(HTTP 201 o 409 "ya registrado"), con la plaga y las coordenadas que se
enviaron en ese momento.

También guarda los casos descartados (falsa alarma) para que no sigan
contando como referencia de brotes posteriores.

Los archivos viven en cache/ y nunca se versionan:
    cache/casos_confirmados.json
    cache/casos_descartados.json

Se pueden reubicar con CONFIRMADOS_SALIDA y DESCARTADOS_SALIDA (útil si el
dashboard y el agente comparten otra carpeta).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
CONFIRMADOS = Path(os.getenv("CONFIRMADOS_SALIDA") or (CACHE / "casos_confirmados.json"))
DESCARTADOS = Path(os.getenv("DESCARTADOS_SALIDA") or (CACHE / "casos_descartados.json"))


def cargar_json(archivo: Path, defecto):
    if not archivo.exists():
        return defecto
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defecto


def guardar_json(archivo: Path, datos) -> None:
    archivo.parent.mkdir(parents=True, exist_ok=True)
    temporal = archivo.with_suffix(archivo.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(archivo)


def cargar_confirmados() -> dict[str, dict]:
    """Devuelve {reporte_id: referencia} del ledger de confirmados."""
    crudo = cargar_json(CONFIRMADOS, {})
    if isinstance(crudo, list):
        crudo = {
            str(c.get("reporte_id")): c
            for c in crudo
            if isinstance(c, dict) and c.get("reporte_id")
        }
    if not isinstance(crudo, dict):
        return {}
    return {str(rid): c for rid, c in crudo.items() if isinstance(c, dict)}


def guardar_confirmados(confirmados: dict[str, dict]) -> None:
    """Fusiona con el disco para no perder confirmaciones de otro proceso."""
    fusion = {str(rid): ref for rid, ref in (confirmados or {}).items()}
    for rid, ref in cargar_confirmados().items():
        fusion.setdefault(rid, ref)  # el primer dato congelado es el válido
    guardar_json(CONFIRMADOS, fusion)
    confirmados.clear()
    confirmados.update(fusion)


def cargar_descartados() -> set[str]:
    crudo = cargar_json(DESCARTADOS, [])
    if isinstance(crudo, dict):
        crudo = list(crudo.keys())
    if not isinstance(crudo, list):
        return set()
    return {str(rid) for rid in crudo if rid}


def guardar_descartados(descartados: set[str]) -> None:
    guardar_json(DESCARTADOS, sorted(descartados))


def marcar_descartado(reporte_id: str) -> None:
    """Marca un caso como falsa alarma/descartado para el conteo de brotes."""
    rid = str(reporte_id)
    descartados = cargar_descartados()
    if rid not in descartados:
        descartados.add(rid)
        guardar_descartados(descartados)


def reactivar_descartado(reporte_id: str) -> None:
    rid = str(reporte_id)
    descartados = cargar_descartados()
    if rid in descartados:
        descartados.remove(rid)
        guardar_descartados(descartados)


def _coordenadas(parcela: dict | None, reporte: dict | None) -> tuple[float | None, float | None]:
    for fuente in (parcela or {}, reporte or {}):
        try:
            lat, lon = float(fuente["lat"]), float(fuente["lon"])
            return lat, lon
        except (KeyError, TypeError, ValueError):
            continue
    return None, None


def referencia_confirmada(caso: dict, reporte: dict | None, parcelas: dict) -> dict | None:
    """Congela los datos que la API conoce de un caso confirmado.

    Se usan las coordenadas de la parcela (regla oficial); si no existen, se
    conservan las del reporte como último recurso. Un caso sin coordenadas se
    guarda igual (para auditoría), pero no contará para brotes.
    """
    caso = caso or {}
    reporte = reporte or {}
    rid = caso.get("reporte_id") or reporte.get("id")
    if not rid:
        return None
    parcela_id = (reporte.get("parcela_id") or caso.get("parcela_id")
                  or caso.get("_parcela_inferida"))
    parcela = parcelas.get(parcela_id) if parcela_id else None
    lat, lon = _coordenadas(parcela, reporte)
    return {
        "reporte_id": str(rid),
        "plaga": caso.get("plaga"),
        "es_plaga": bool(caso.get("es_plaga")),
        "lat": lat,
        "lon": lon,
        "recibido": reporte.get("recibido") or caso.get("recibido"),
        "productor_id": reporte.get("productor_id") or caso.get("productor_id"),
        "parcela_id": parcela_id,
        "seguimiento_de": caso.get("seguimiento_de"),
        "propio": True,
        "fuente": "confirmado",
    }


def confirmar(confirmados: dict[str, dict], caso: dict, reporte: dict | None,
              parcelas: dict) -> dict | None:
    """Añade un caso confirmado sin perder el primer dato concreto.

    Si ya existe una plaga concreta con coordenadas, no se reescribe: la API
    cuenta el caso con lo que recibió primero. Sí se completa un registro que
    estaba vacío/desconocido (por ejemplo, un complemento que aclara la plaga).
    """
    ref = referencia_confirmada(caso, reporte, parcelas)
    if not ref:
        return None
    previo = confirmados.get(ref["reporte_id"])
    if (previo and previo.get("plaga") not in (None, "desconocida")
            and previo.get("lat") is not None and previo.get("lon") is not None):
        return previo
    confirmados[ref["reporte_id"]] = ref
    return ref


def sembrar_desde_enviados(confirmados: dict[str, dict], casos: dict[str, dict],
                           reportes_por_id: dict[str, dict], parcelas: dict,
                           enviados) -> int:
    """Recupera el historial de casos ya enviados cuando el ledger no existe.

    Solo agrega los que faltan; nunca borra ni reescribe los ya congelados.
    Devuelve cuántos agregó.
    """
    nuevos = 0
    for rid in enviados or []:
        rid = str(rid)
        if rid in confirmados:
            continue
        caso = casos.get(rid)
        if not caso:
            continue
        ref = referencia_confirmada(caso, reportes_por_id.get(rid) or {}, parcelas)
        if ref:
            confirmados[rid] = ref
            nuevos += 1
    return nuevos
