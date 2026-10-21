"""
extras.py — Retos extra del Nivel 2: avisos, preguntas, brotes y plazos.

Todo está preparado pero **apagado por defecto**: solo se ejecuta si se llama
explícitamente desde el listener (--extras) o por consola. Así se puede probar
sin mandar avisos reales a la API.

Endpoints que usa:
    POST /avisos      {reporte_id, tipo, para, mensaje}
    POST /preguntas   {reporte_id, texto}
    GET  /visitas     [{reporte_id, tecnico_id, fecha}]

Tipos de aviso: folio, asignacion, brote, cuarentenaria, escalamiento, respuesta.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nivel2 import distancia_km

RAIZ = Path(__file__).resolve().parent.parent
ZONA_MX = timezone(timedelta(hours=-6))

RADIO_BROTE_KM = 5.0
MINIMO_CASOS_BROTE = 3
VENTANA_BROTE_DIAS = 7

# plazo máximo de visita según el semáforo (sección 7 del reglamento)
PLAZO_HORAS = {"rojo": 24, "naranja": 48, "amarillo": 72, "verde": 168}


class Extras:
    def __init__(self, api, seco: bool = True, repo=None) -> None:
        """seco=True -> imprime lo que haría pero no manda nada a la API."""
        self.api = api
        self.seco = seco
        self.repo = repo
        self.enviados: list[dict] = []

    # ---------------------------------------------------------------- avisos

    def avisar(self, reporte_id: str, tipo: str, para, mensaje: str) -> dict | None:
        cuerpo = {"reporte_id": reporte_id, "tipo": tipo, "para": para, "mensaje": mensaje[:2000]}
        if self.seco:
            print(f"  [seco] aviso {tipo} -> {para}: {mensaje[:90]}")
            self.enviados.append(cuerpo)
            return cuerpo
        try:
            respuesta = self.api.post("avisos", cuerpo)
            self.enviados.append(cuerpo)
            self._guardar_aviso(reporte_id, tipo, para, cuerpo["mensaje"])
            return respuesta
        except Exception as exc:
            print(f"  aviso falló ({tipo}): {exc}")
            return None

    def _guardar_aviso(self, reporte_id: str, tipo: str, para, mensaje: str) -> None:
        if not self.repo:
            return
        destinos = para if isinstance(para, list) else [para]
        try:
            self.repo.guardar_aviso(reporte_id, tipo, destinos, mensaje)
        except Exception as exc:
            print(f"  aviso guardado en BD falló ({tipo}): {exc}")

    def avisar_cuarentenaria(self, caso: dict, plaga: dict, parcela: dict) -> None:
        """Plaga cuarentenaria: sanidad vegetal debe saberlo de inmediato."""
        if not plaga.get("cuarentenaria"):
            return
        mensaje = (
            f"ALERTA CUARENTENARIA: {plaga['nombre']} ({plaga['id']}) en la parcela "
            f"{parcela.get('id')} de {parcela.get('cultivo')} "
            f"({parcela.get('municipio')}, {parcela.get('localidad')}). "
            f"Reporte {caso['reporte_id']}."
        )
        self.avisar(caso["reporte_id"], "cuarentenaria",
                    ["coordinador", "sanidad_vegetal"], mensaje)

    def avisar_asignacion(self, caso: dict, plaga: dict, parcela: dict,
                          productor_id: str | None) -> None:
        """Avisa al técnico asignado y da folio al productor."""
        tecnico = caso.get("tecnico_id")
        if tecnico:
            self.avisar(caso["reporte_id"], "asignacion", [tecnico],
                        f"Caso {caso['reporte_id']}: {plaga['nombre']} en {parcela.get('nombre')} "
                        f"({parcela.get('cultivo')}, {parcela.get('superficie_ha')} ha). "
                        f"Semáforo {caso.get('semaforo')} (prioridad {caso.get('prioridad')}).")
        if productor_id:
            self.avisar(caso["reporte_id"], "folio", [productor_id],
                        f"Recibimos su reporte {caso['reporte_id']}. "
                        f"Quedó con semáforo {caso.get('semaforo')} y ya tiene técnico asignado.")

    # -------------------------------------------------------------- preguntas

    def preguntar(self, reporte_id: str, texto: str) -> dict | None:
        if self.seco:
            print(f"  [seco] pregunta a {reporte_id}: {texto[:90]}")
            return {"reporte_id": reporte_id, "texto": texto}
        try:
            respuesta = self.api.post("preguntas", {"reporte_id": reporte_id, "texto": texto[:500]})
            if self.repo:
                try:
                    self.repo.guardar_pregunta(reporte_id, texto[:500])
                except Exception as exc:
                    print(f"  pregunta guardada en BD falló: {exc}")
            return respuesta
        except Exception as exc:
            print(f"  pregunta falló: {exc}")
            return None

    def sugerir_pregunta(self, reporte: dict, resultado: dict) -> str | None:
        """Pregunta útil cuando falta un dato para calcular semáforo o plaga."""
        if not reporte.get("parcela_id"):
            return ("¿En cuál de sus parcelas está el problema y qué tanto ha avanzado? "
                    "Con eso podemos asignarle un técnico.")
        if resultado.get("es_plaga") and resultado.get("plaga") == "desconocida":
            return ("¿Qué es lo que ve en la planta: insectos, manchas, hojas comidas o "
                    "la planta se marchita? ¿Qué parte de la parcela está afectada?")
        return None

    # ----------------------------------------------------------------- brotes

    def detectar_brotes(self, casos: list[dict], parcelas: dict[str, dict],
                        casos_previos: list[dict] | None = None,
                        ahora: datetime | None = None) -> list[dict]:
        """3+ casos de la misma plaga a menos de 5 km en los últimos 7 días."""
        ahora = ahora or datetime.now(ZONA_MX)
        limite = ahora - timedelta(days=VENTANA_BROTE_DIAS)

        registros = []
        for c in (casos_previos or []) + casos:
            plaga = c.get("plaga")
            parcela = parcelas.get(c.get("parcela_id") or "")
            recibido = c.get("recibido")
            if not plaga or plaga == "desconocida" or not parcela or not recibido:
                continue
            try:
                fecha = datetime.fromisoformat(recibido)
            except ValueError:
                continue
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=ZONA_MX)
            if fecha < limite:
                continue
            registros.append({"id": c.get("reporte_id") or c.get("id"), "plaga": plaga,
                              "parcela": parcela, "fecha": fecha})

        brotes = []
        vistos: set[str] = set()
        for base in registros:
            if base["id"] in vistos:
                continue
            # agrupación transitiva: cualquier caso a <=5 km de algún miembro entra
            grupo = [base]
            cola = [base]
            while cola:
                actual = cola.pop()
                for otro in registros:
                    if otro["id"] in vistos or otro in grupo:
                        continue
                    if otro["plaga"] != base["plaga"]:
                        continue
                    if distancia_km(actual["parcela"]["lat"], actual["parcela"]["lon"],
                                    otro["parcela"]["lat"], otro["parcela"]["lon"]) <= RADIO_BROTE_KM:
                        grupo.append(otro)
                        cola.append(otro)
            vistos.update(g["id"] for g in grupo)
            if len(grupo) < MINIMO_CASOS_BROTE:
                continue
            lat = sum(g["parcela"]["lat"] for g in grupo) / len(grupo)
            lon = sum(g["parcela"]["lon"] for g in grupo) / len(grupo)
            brotes.append({
                "plaga": base["plaga"],
                "casos": [g["id"] for g in grupo],
                "parcelas": [g["parcela"]["id"] for g in grupo],
                "centro": {"lat": round(lat, 5), "lon": round(lon, 5)},
            })
        return brotes

    def avisar_brote(self, brote: dict, parcelas: dict[str, dict], productores: dict[str, dict]) -> None:
        """Avisa a los productores vecinos con el mismo cultivo."""
        referencia = parcelas.get(brote["parcelas"][0])
        if not referencia:
            return
        cultivo = referencia.get("cultivo")
        vecinos = []
        for parcela in parcelas.values():
            if parcela.get("cultivo") != cultivo or parcela["id"] in brote["parcelas"]:
                continue
            if distancia_km(referencia["lat"], referencia["lon"],
                            parcela["lat"], parcela["lon"]) <= RADIO_BROTE_KM:
                vecinos.append(parcela.get("productor_id"))
        vecinos = sorted({v for v in vecinos if v})
        if not vecinos:
            return
        mensaje = (f"BROTE de {brote['plaga']} detectado en su zona "
                   f"({len(brote['casos'])} casos en menos de {RADIO_BROTE_KM:.0f} km). "
                   f"Revise su cultivo de {cultivo}.")
        self.avisar(brote["casos"][0], "brote", vecinos, mensaje)

    # ----------------------------------------------------------------- plazos

    def revisar_plazos(self, casos: list[dict], visitas: list[dict],
                       ahora: datetime | None = None) -> list[dict]:
        """Casos sin visita dentro del plazo de su semáforo -> escalar."""
        ahora = ahora or datetime.now(ZONA_MX)
        visitados = {v.get("reporte_id") for v in visitas}
        vencidos = []
        for caso in casos:
            if not caso.get("es_plaga") or not caso.get("semaforo"):
                continue
            if caso["reporte_id"] in visitados:
                continue
            recibido = caso.get("recibido")
            if not recibido:
                continue
            try:
                fecha = datetime.fromisoformat(recibido)
            except ValueError:
                continue
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=ZONA_MX)
            horas = PLAZO_HORAS.get(caso["semaforo"], 168)
            if ahora - fecha > timedelta(hours=horas):
                vencidos.append({"caso": caso, "horas": horas,
                                 "retraso_h": round((ahora - fecha).total_seconds() / 3600, 1)})
        return vencidos

    def escalar(self, vencido: dict) -> None:
        caso = vencido["caso"]
        self.avisar(caso["reporte_id"], "escalamiento", ["coordinador"],
                    f"El caso {caso['reporte_id']} (semáforo {caso['semaforo']}) lleva "
                    f"{vencido['retraso_h']} h sin visita; el plazo era {vencido['horas']} h.")


def main() -> None:
    """Demostración por consola (modo seco, no manda nada)."""
    import argparse
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from api_cliente import ApiCliente
    from clasificador import Clasificador, resultados_a_casos

    parser = argparse.ArgumentParser(description="Retos extra (modo seco por defecto)")
    parser.add_argument("--real", action="store_true", help="Enviar avisos de verdad")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    api = ApiCliente()
    clf = Clasificador(api, con_ia=True)
    extras = Extras(api, seco=not args.real)

    reportes = json.loads((RAIZ / "cache" / "reportes.json").read_text(encoding="utf-8"))
    casos = resultados_a_casos(reportes, clf)
    casos_por_id = {c["reporte_id"]: c for c in casos}
    for r in reportes:
        if r["id"] in casos_por_id:
            casos_por_id[r["id"]]["recibido"] = r.get("recibido")
            casos_por_id[r["id"]]["parcela_id"] = r.get("parcela_id")

    productores = {p["id"]: p for p in clf.api.get_productores()}
    previos = api.get("casos-previos") or []
    visitas = api.get("visitas") or []

    print("== Brotes detectados ==")
    brotes = extras.detectar_brotes(list(casos_por_id.values()), clf.parcelas, previos)
    for b in brotes:
        print(f"  {b['plaga']}: {len(b['casos'])} casos -> {b['casos']}")
        extras.avisar_brote(b, clf.parcelas, productores)
    if not brotes:
        print("  (ninguno)")

    print("\n== Plazos vencidos ==")
    vencidos = extras.revisar_plazos(list(casos_por_id.values()), visitas)
    for v in vencidos:
        print(f"  {v['caso']['reporte_id']} {v['caso']['semaforo']} retraso {v['retraso_h']} h")
        extras.escalar(v)
    if not vencidos:
        print("  (ninguno)")

    print("\n== Cuarentenarias ==")
    for rid, caso in casos_por_id.items():
        plaga = next((p for p in clf.plagas if p["id"] == caso.get("plaga")), None)
        parcela = clf.parcelas.get(caso.get("parcela_id") or "")
        if plaga and plaga.get("cuarentenaria") and parcela:
            extras.avisar_cuarentenaria(caso, plaga, parcela)
            print(f"  {rid}: {plaga['id']}")

    print(f"\nAvisos preparados: {len(extras.enviados)} | modo {'REAL' if args.real else 'seco'}")


if __name__ == "__main__":
    main()
