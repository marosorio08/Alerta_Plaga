"""
supabase_repositorio.py — Persistencia del bot en Supabase.

Usa la API REST de Supabase (PostgREST) con la service_role key. Esa llave
solo vive en el .env del servidor: nunca debe llegar al navegador ni al repo.

Si SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY no están definidas, el repositorio
queda inactivo y el bot sigue trabajando con su caché local.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

RAIZ = Path(__file__).resolve().parent.parent


class RepositorioSupabase:
    def __init__(self) -> None:
        self.url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
        self.activo = bool(self.url and self.key)
        self.sesion = requests.Session()
        if self.activo:
            self.sesion.headers.update(
                {
                    "apikey": self.key,
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                }
            )

    # ---------- núcleo ----------

    def _upsert(self, tabla: str, filas: list[dict], conflicto: str) -> None:
        if not self.activo or not filas:
            return
        resp = self.sesion.post(
            f"{self.url}/rest/v1/{tabla}",
            params={"on_conflict": conflicto},
            json=filas,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            timeout=40,
        )
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"Supabase {tabla} {resp.status_code}: {resp.text[:300]}")

    def _insertar(self, tabla: str, fila: dict) -> dict | None:
        if not self.activo:
            return None
        resp = self.sesion.post(
            f"{self.url}/rest/v1/{tabla}",
            json=[fila],
            headers={"Prefer": "return=representation"},
            timeout=40,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Supabase {tabla} {resp.status_code}: {resp.text[:300]}")
        datos = resp.json()
        return datos[0] if datos else None

    # ---------- reportes y clasificación ----------

    def guardar_reporte(self, reporte: dict) -> None:
        fila = {
            "id": reporte.get("id"),
            "productor_id": reporte.get("productor_id"),
            "parcela_id": reporte.get("parcela_id"),
            "tipo": reporte.get("tipo"),
            "texto": reporte.get("texto"),
            "audio_url": reporte.get("audio_url"),
            "foto_url": reporte.get("foto_url"),
            "duracion_s": reporte.get("duracion_s"),
            "lat": reporte.get("lat"),
            "lon": reporte.get("lon"),
            "recibido": reporte.get("recibido"),
            "respuesta_a": reporte.get("respuesta_a"),
            "raw": reporte,
        }
        self._upsert("reportes", [fila], "id")

    def guardar_caso(self, detalle: dict) -> None:
        caso = detalle.get("caso") or {}
        es_plaga = bool(caso.get("es_plaga"))
        plaga = (caso.get("plaga") or "desconocida") if es_plaga else None
        fila = {
            "reporte_id": caso.get("reporte_id") or detalle.get("reporte_id"),
            "es_plaga": es_plaga,
            "plaga_id": plaga,
            "urgente": bool(caso.get("urgente")),
            "semaforo": caso.get("semaforo") or detalle.get("semaforo"),
            "tecnico_id": caso.get("tecnico_id") or detalle.get("tecnico_id"),
            "prioridad": caso.get("prioridad") or detalle.get("prioridad"),
            "pct": caso.get("pct") or detalle.get("pct"),
            "brote": bool(caso.get("brote") or detalle.get("brote")),
            "confianza": detalle.get("confianza"),
            "motor": detalle.get("motor"),
            "razon": detalle.get("razon"),
            "inyeccion": bool(detalle.get("injection")),
            "seguimiento": bool(detalle.get("seguimiento") or detalle.get("seguimiento_de")),
            "seguimiento_de": detalle.get("seguimiento_de"),
            "raw": detalle,
        }
        self._upsert("casos", [fila], "reporte_id")

    # ---------- envío a la API ----------

    def guardar_envio(self, reporte_id: str, caso: dict, estado: str,
                      respuesta: dict | None = None, error: str | None = None,
                      intentos: int = 1) -> None:
        fila = {
            "reporte_id": reporte_id,
            "caso": caso,
            "estado": estado,
            "intentos": intentos,
            "respuesta": respuesta,
            "error": error,
            "enviado_en": datetime.now(timezone.utc).isoformat() if estado == "enviado" else None,
        }
        self._upsert("envios", [fila], "reporte_id")

    # ---------- acciones ----------

    def guardar_aviso(self, reporte_id: str, tipo: str, para: list[str], mensaje: str) -> None:
        self._insertar(
            "avisos",
            {"reporte_id": reporte_id, "tipo": tipo, "para": para, "mensaje": mensaje},
        )

    def guardar_pregunta(self, reporte_id: str, texto: str) -> None:
        self._upsert(
            "preguntas",
            [{"reporte_id": reporte_id, "texto": texto}],
            "reporte_id",
        )

    def guardar_evento(self, tipo: str, detalle: dict, reporte_id: str | None = None) -> None:
        self._insertar(
            "eventos",
            {"tipo": tipo, "reporte_id": reporte_id, "detalle": detalle},
        )

    # ---------- catálogos ----------

    def sincronizar_catalogos(self, plagas: list[dict], parcelas: list[dict],
                              productores: list[dict], tecnicos: list[dict]) -> None:
        filas_plagas = [
            {
                "id": p.get("id"),
                "nombre": p.get("nombre"),
                "nombre_cientifico": p.get("nombre_cientifico"),
                "nombres_locales": p.get("nombres_locales") or [],
                "tipo": p.get("tipo"),
                "especialidad": p.get("especialidad"),
                "severidad": p.get("severidad"),
                "cuarentenaria": bool(p.get("cuarentenaria")),
                "cultivos": p.get("cultivos") or [],
                "sintomas": p.get("sintomas") or [],
                "etapas_criticas": p.get("etapas_criticas") or {},
                "etapas_susceptibles": p.get("etapas_susceptibles") or {},
            }
            for p in plagas
            if p.get("id") and p.get("id") != "desconocida"
        ]
        self._upsert("plagas", filas_plagas, "id")

        self._upsert(
            "productores",
            [
                {
                    "id": p.get("id"),
                    "nombre": p.get("nombre"),
                    "municipio": p.get("municipio"),
                    "localidad": p.get("localidad"),
                    "parcelas_ids": p.get("parcelas") or [],
                }
                for p in productores
            ],
            "id",
        )

        self._upsert(
            "parcelas",
            [
                {
                    "id": p.get("id"),
                    "productor_id": p.get("productor_id"),
                    "nombre": p.get("nombre"),
                    "municipio": p.get("municipio"),
                    "localidad": p.get("localidad"),
                    "cultivo": p.get("cultivo"),
                    "superficie_ha": p.get("superficie_ha"),
                    "etapa": p.get("etapa"),
                    "lat": p.get("lat"),
                    "lon": p.get("lon"),
                }
                for p in parcelas
            ],
            "id",
        )

        self._upsert(
            "tecnicos",
            [
                {
                    "id": t.get("id"),
                    "nombre": t.get("nombre"),
                    "especialidad": t.get("especialidad"),
                    "base": t.get("base"),
                    "lat": t.get("lat"),
                    "lon": t.get("lon"),
                    "carga": t.get("carga"),
                    "tope": t.get("tope"),
                    "momento": t.get("momento"),
                }
                for t in tecnicos
            ],
            "id",
        )

        resumen = [
            {"nombre": "plagas", "registros": len(filas_plagas)},
            {"nombre": "parcelas", "registros": len(parcelas)},
            {"nombre": "productores", "registros": len(productores)},
            {"nombre": "tecnicos", "registros": len(tecnicos)},
        ]
        self._upsert(
            "catalogos_sync",
            [{**r, "ok": True, "detalle": "sincronizado por el listener"} for r in resumen],
            "nombre",
        )
