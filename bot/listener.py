"""
listener.py — Vigila la API y clasifica los reportes nuevos en cuanto llegan.

Diseño pensado para el "reporte en vivo" del viernes y para que nada se rompa
si los organizadores cambian el catálogo o agregan objetivos:

  * Consulta GET /reportes?desde=... cada N segundos y deduplica por id.
  * Clasifica con el motor completo (texto, STT con consenso, visión con
    consenso, cruce por cultivo, seguimientos y urgencia por catálogo).
  * Valida el formato con POST /casos/validar (no registra ni puntúa).
  * Mantiene cache/casos_propuestos.json al día para el dashboard.
  * Refresca los catálogos cada X minutos: si agregan plagas, cultivos o
    severidades, el motor los toma sin tocar código.
  * Por defecto NO registra nada (POST /casos). Para eso hace falta --enviar
    de forma explícita.

Uso:
    python bot/listener.py                    # vigila para siempre (no registra)
    python bot/listener.py --una-vez          # una pasada y sale
    python bot/listener.py --intervalo 20     # cada 20 s (por defecto 20)
    python bot/listener.py --enviar           # registra los nuevos (irreversible)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_cliente import ApiCliente, ApiError  # noqa: E402
from clasificador import Clasificador  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
ESTADO = CACHE / "listener_estado.json"
CASOS_TODOS = CACHE / "casos_propuestos.json"   # lo consume el dashboard
BITACORA = CACHE / "listener_bitacora.jsonl"    # historial de decisiones


def ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cargar_json(archivo: Path, defecto):
    if not archivo.exists():
        return defecto
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[{ahora()}] aviso: {archivo.name} corrupto, se reinicia")
        return defecto


def guardar_json(archivo: Path, datos) -> None:
    temporal = archivo.with_suffix(archivo.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(archivo)  # escritura atómica: el dashboard nunca lee a medias


class Listener:
    def __init__(self, intervalo: int = 20, refresco_min: int = 10, enviar: bool = False) -> None:
        self.api = ApiCliente()
        self.clf = Clasificador(self.api, con_ia=True)
        self.intervalo = intervalo
        self.refresco = refresco_min * 60
        self.enviar = enviar
        self.estado = cargar_json(ESTADO, {"procesados": [], "enviados": [], "iniciado": ahora()})
        self.casos = {c["reporte_id"]: c for c in cargar_json(CASOS_TODOS, [])}
        self.ultimo_refresco = time.time()
        self.nuevos_total = 0

    # ---------- clasificación ----------

    def procesar(self, reporte: dict) -> dict:
        try:
            res = self.clf.clasificar_reporte(reporte)
        except Exception as exc:  # un reporte raro nunca tumba el listener
            print(f"[{ahora()}] error clasificando {reporte.get('id')}: {exc}")
            traceback.print_exc()
            return {"reporte_id": reporte.get("id"), "es_plaga": True,
                    "plaga": "desconocida", "urgente": False, "error": str(exc)}

        caso = {
            "reporte_id": reporte["id"],
            "es_plaga": bool(res.get("es_plaga")),
            "plaga": res.get("plaga") if res.get("es_plaga") else None,
            "urgente": bool(res.get("urgente")),
        }
        detalle = {
            "reporte_id": reporte["id"],
            "tipo": reporte.get("tipo"),
            "parcela_id": reporte.get("parcela_id"),
            "cultivo": self.clf.cultivo_de_parcela(reporte.get("parcela_id")),
            "recibido": reporte.get("recibido"),
            "procesado": ahora(),
            "caso": caso,
            "motor": res.get("motor"),
            "confianza": res.get("confianza"),
            "razon": res.get("razon"),
            "injection": res.get("injection"),
            "texto": (res.get("texto") or reporte.get("texto") or "")[:280],
            "seguimiento_de": res.get("seguimiento_de"),
        }
        with BITACORA.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(detalle, ensure_ascii=False) + "\n")
        return detalle

    # ---------- ciclo ----------

    def ciclo(self) -> int:
        try:
            reportes = self.api.get_reportes()
        except ApiError as exc:
            print(f"[{ahora()}] API no responde: {exc}")
            return 0

        procesados = set(self.estado["procesados"])
        pendientes = [r for r in reportes if r["id"] not in procesados]
        if not pendientes:
            return 0

        for reporte in pendientes:
            detalle = self.procesar(reporte)
            caso = detalle.get("caso", {k: detalle.get(k) for k in ("reporte_id", "es_plaga", "plaga", "urgente")})
            self.casos[caso["reporte_id"]] = caso
            self.estado["procesados"].append(caso["reporte_id"])
            self.nuevos_total += 1

            marca = "URGENTE" if caso.get("urgente") else ("plaga" if caso["es_plaga"] else "no-plaga")
            conf = detalle.get("confianza") or 0
            print(f"[{ahora()}] {caso['reporte_id']} {reporte.get('tipo', '?'):<5} "
                  f"{marca:<8} plaga={caso.get('plaga')} conf={round(float(conf), 2)} "
                  f"| {str(detalle.get('texto', ''))[:70]}")

            # validación de formato (no puntúa, no registra)
            try:
                self.api.validar_caso(caso)
            except ApiError as exc:
                print(f"[{ahora()}] AVISO validación {caso['reporte_id']}: {exc}")

            if self.enviar and caso["reporte_id"] not in self.estado["enviados"]:
                try:
                    self.api.registrar_caso(caso)
                    self.estado["enviados"].append(caso["reporte_id"])
                    print(f"[{ahora()}] registrado en POST /casos: {caso['reporte_id']}")
                except ApiError as exc:
                    print(f"[{ahora()}] error registrando {caso['reporte_id']}: {exc}")

        guardar_json(CASOS_TODOS, list(self.casos.values()))
        guardar_json(ESTADO, self.estado)
        return len(pendientes)

    # ---------- mantenimiento ----------

    def refrescar_catalogo(self) -> None:
        """Recarga /plagas, /parcelas y /tecnicos por si el reto cambió."""
        try:
            self.clf.recargar_catalogo()
            self.ultimo_refresco = time.time()
            print(f"[{ahora()}] catálogos refrescados ({len(self.clf.plagas)} plagas, "
                  f"{len(self.clf.parcelas)} parcelas)")
        except Exception as exc:
            print(f"[{ahora()}] no se pudo refrescar el catálogo: {exc}")

    def correr(self, una_vez: bool = False) -> None:
        print(f"[{ahora()}] listener iniciado | intervalo {self.intervalo}s | "
              f"registro automático: {'SÍ' if self.enviar else 'NO'}")
        while True:
            inicio = time.time()
            try:
                nuevos = self.ciclo()
                if nuevos:
                    print(f"[{ahora()}] {nuevos} reporte(s) nuevo(s) procesado(s) | "
                          f"total en esta sesión: {self.nuevos_total}")
                if time.time() - self.ultimo_refresco >= self.refresco:
                    self.refrescar_catalogo()
            except KeyboardInterrupt:
                print(f"\n[{ahora()}] listener detenido por el usuario")
                break
            except Exception:
                # nunca morir por un fallo inesperado
                print(f"[{ahora()}] error inesperado, el listener sigue:")
                traceback.print_exc()

            if una_vez:
                break
            espera = max(1.0, self.intervalo - (time.time() - inicio))
            try:
                time.sleep(espera)
            except KeyboardInterrupt:
                print(f"\n[{ahora()}] listener detenido por el usuario")
                break


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Listener continuo de reportes (Alerta Plaga)")
    parser.add_argument("--intervalo", type=int, default=20, help="Segundos entre consultas (por defecto 20)")
    parser.add_argument("--refresco", type=int, default=10, help="Minutos entre refrescos de catálogo")
    parser.add_argument("--una-vez", action="store_true", help="Una sola pasada y salir")
    parser.add_argument("--enviar", action="store_true", help="Registrar en POST /casos (irreversible)")
    parser.add_argument("--reiniciar", action="store_true", help="Ignorar el estado y reprocesar todo")
    args = parser.parse_args()

    if args.reiniciar:
        for archivo in (ESTADO,):
            if archivo.exists():
                archivo.unlink()

    listener = Listener(intervalo=args.intervalo, refresco_min=args.refresco, enviar=args.enviar)
    listener.correr(una_vez=args.una_vez)


if __name__ == "__main__":
    main()
