"""
decision_autonoma.py — Modelo de decisión autónoma del equipo 7_7.

Filosofía (la que validamos en la sesión):

  1. Primero se evalúa TODO con el motor real (reglas + IA + STT/visión).
  2. Si la app y el análisis independiente coinciden y no hay dudas -> SEGURO.
  3. Si hay duda, se reanaliza hasta MAX_REINTENTOS veces usando:
       intento 1: app vs motor
       intento 2: solo reglas vs IA (consenso)
       intento 3: antecedentes (padre, misma parcela, seguimiento)
       intento 4: brote profundo (coordenadas del reporte, misma parcela,
                  n=2) + palabras clave del pct
  4. Si tras los 4 intentos sigue sin certeza -> NO se envía y se avisa al
     admin con descripción, duda, % de certeza y opciones + botones
     "Aceptar" / "Dejar en cola para reanálisis conjunto".

El envío automático está APAGADO por defecto (`PERMITIR_ENVIOS=0`). Para
activarlo, cambia la línea marcada abajo o define `PERMITIR_ENVIOS=1` en .env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"
REPORTES = CACHE / "reportes.json"


def _ruta_app_casos() -> Path:
    """En el servidor usa la caché compartida (CASOS_SALIDA); en local, la foto fresca."""
    for candidato in (os.getenv("CASOS_SALIDA"),
                      CACHE / "_app_casos_fresh.json",
                      CACHE / "casos_propuestos.json",
                      RAIZ.parent / "app" / "cache" / "casos_propuestos.json"):
        if candidato and Path(candidato).exists():
            return Path(candidato)
    return CACHE / "casos_propuestos.json"


APP_CASOS = _ruta_app_casos()
PARCELAS = CACHE / "parcelas.json"
PLAGAS = CACHE / "plagas.json"
TECNICOS = CACHE / "tecnicos.json"
PREVIOS = CACHE / "cache_casos_previos.json"

sys.path.insert(0, str(RAIZ / "bot"))

# ============================================================================
# CONFIGURACIÓN RÁPIDA — CAMBIAR AQUÍ
# ============================================================================
# Envío automático: False por defecto (no se manda nada sin visto bueno).
PERMITIR_ENVIOS = os.getenv("PERMITIR_ENVIOS", "0") == "1"
# Modelo de IA para el desempate/consenso. Si se acaban los tokens, cambia
# ESTA línea o define OPENROUTER_MODELO_IA en el .env.
MODELO_IA = os.getenv("OPENROUTER_MODELO_IA", "gpt-4o-mini")
# Reintentos antes de avisar al admin.
MAX_REINTENTOS = 4
# Certeza mínima para considerar un caso 100 % seguro / para enviar tras
# los 4 reintentos.
CERTEZA_SEGURA = 0.90
CERTEZA_ENVIAR = 0.85
# ============================================================================

ZONA = timezone(timedelta(hours=-6))


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _dt(valor) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=ZONA)
    except Exception:
        return None


def _ahora() -> str:
    return datetime.now(ZONA).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Decision:
    reporte_id: str
    seguro: bool
    certeza: float
    payload: dict | None = None
    plaga: str | None = None
    duda: str = ""
    motivo: str = ""
    intentos: int = 0
    evidencias: list[str] = field(default_factory=list)
    opciones: list[dict] = field(default_factory=list)
    brote: bool | None = None
    n_brote: int | None = None
    app: dict = field(default_factory=dict)

    def como_dict(self) -> dict:
        return {
            "reporte_id": self.reporte_id,
            "seguro": self.seguro,
            "certeza": round(self.certeza, 3),
            "payload": self.payload,
            "plaga": self.plaga,
            "duda": self.duda,
            "motivo": self.motivo,
            "intentos": self.intentos,
            "evidencias": self.evidencias,
            "opciones": self.opciones,
            "brote": self.brote,
            "n_brote": self.n_brote,
        }


class Contexto:
    """Carga una sola vez los catálogos y casos de la app."""

    def __init__(self) -> None:
        self.reportes = {r["id"]: r for r in _leer_json(REPORTES, [])}
        data = _leer_json(APP_CASOS, {})
        casos = data.get("casos") if isinstance(data, dict) else data
        self.app = {c["reporte_id"]: c for c in (casos or [])}
        self.parcelas = {p["id"]: p for p in _leer_json(PARCELAS, [])}
        self.plagas = {p["id"]: p for p in _leer_json(PLAGAS, [])}
        self.tecnicos = _leer_json(TECNICOS, [])
        self.previos = _leer_json(PREVIOS, [])

    def parcela_de(self, rid: str) -> dict:
        r = self.reportes.get(rid) or {}
        pid = r.get("parcela_id") or (self.app.get(rid) or {}).get("parcela_id")
        return self.parcelas.get(pid or "") or {}

    def respuesta_de(self, rid: str) -> dict | None:
        return next((r for r in self.reportes.values()
                     if r.get("respuesta_a") == rid), None)


def _motor(ctx: Contexto, rid: str, con_ia: bool = True):
    """Clasifica el reporte (o su respuesta, fusionada) con el motor real."""
    # La línea MODELO_IA de la configuración manda si no hay env explícito.
    if MODELO_IA and not os.getenv("OPENROUTER_MODELO_IA"):
        os.environ["OPENROUTER_MODELO_IA"] = MODELO_IA
    from api_cliente import ApiCliente
    from clasificador import Clasificador, caso_para_api, decidir_brote, resultados_a_casos

    api = ApiCliente()
    clf = Clasificador(api, con_ia=con_ia)
    try:
        clf.recargar_catalogo()
    except Exception:
        pass
    clf.casos_actuales = dict(ctx.app)
    clf.reportes_actuales = dict(ctx.reportes)

    reporte = ctx.reportes[rid]
    respuesta = ctx.respuesta_de(rid)
    # Clasificamos el reporte ORIGINAL (audio/foto/texto) y, si existe, la
    # respuesta. La respuesta solo se usa si aporta una plaga que el original
    # no tenía, o si el original no traía pct y la respuesta sí. R-2185: el
    # original es cogollero; la respuesta solo decía "El Salitre, la mitad".
    res = clf.clasificar_reporte(reporte)
    caso = resultados_a_casos([reporte], clf)[0]
    if respuesta:
        try:
            r_res = clf.clasificar_reporte(respuesta)
            r_caso = resultados_a_casos([respuesta], clf)[0]
            pl_orig = res.get("plaga")
            pl_resp = r_res.get("plaga")
            if (pl_orig in (None, "desconocida")) and (pl_resp not in (None, "desconocida")):
                res, caso = r_res, r_caso
            if (caso.get("_pct") in (None, 10)) and (r_caso.get("_pct") not in (None, 10)):
                caso["_pct"] = r_caso.get("_pct")
        except Exception:
            pass
    caso["reporte_id"] = rid

    # Brote con el conjunto completo (incluye el nuevo dedupe productor+parcela).
    casos = [dict(reporte_id=k, es_plaga=v.get("es_plaga"),
                  plaga=v.get("plaga"), seguimiento_de=v.get("seguimiento_de"))
             for k, v in ctx.app.items()]
    casos = [c for c in casos if c["reporte_id"] != rid]
    # OJO: una respuesta `-R` trae seguimiento_de = id del padre (que es este
    # mismo reporte). Eso NO es un seguimiento: es una respuesta a pregunta.
    seg_brote = ctx.app.get(rid, {}).get("seguimiento_de")
    if seg_brote is None and res.get("seguimiento_de") not in (None, rid):
        seg_brote = res.get("seguimiento_de")
    casos.append({"reporte_id": rid, "es_plaga": bool(caso.get("es_plaga")),
                  "plaga": caso.get("plaga"), "seguimiento_de": seg_brote})
    brotes = clf.evaluar_brotes(casos, ctx.reportes, previos=ctx.previos)
    info = brotes.get(rid, {"n": None, "refs": []})
    n = info.get("n")
    brote = decidir_brote(n)
    if brote is None:
        caso.pop("brote", None)
        caso["_brote_dudoso"] = True
    else:
        caso["brote"] = brote
        caso.pop("_brote_dudoso", None)
    return res, caso, n, brote, info


def _misma_parcela_previa(ctx: Contexto, rid: str) -> dict | None:
    """Caso previo no-seguimiento en la MISMA parcela (patrón R-2160/R-2179)."""
    r = ctx.reportes.get(rid) or {}
    pid = r.get("parcela_id") or (ctx.app.get(rid) or {}).get("parcela_id")
    if not pid:
        return None
    t = _dt(r.get("recibido"))
    if not t:
        return None
    for otro, c in ctx.app.items():
        if otro == rid or not c.get("es_plaga") or c.get("seguimiento_de"):
            continue
        ro = ctx.reportes.get(otro) or {}
        if (ro.get("parcela_id") or c.get("parcela_id")) != pid:
            continue
        to = _dt(ro.get("recibido"))
        if not to:
            continue
        if 0 < (t - to).total_seconds() / 3600 <= 168:
            return {"reporte_id": otro, "plaga": c.get("plaga"),
                    "horas": round((t - to).total_seconds() / 3600, 1)}
    return None


def _tercero_por_coords(ctx: Contexto, rid: str, plaga: str) -> dict | None:
    """Tercer caso de la misma plaga a <5 km usando coordenadas DEL REPORTE.

    Patrón R-2180: R-2027 estaba a 5.0068 km por parcela pero a 4.9624 km
    por reporte. La API usa el GPS del reporte.
    """
    from nivel2 import distancia_km

    r = ctx.reportes.get(rid) or {}
    lat, lon = r.get("lat"), r.get("lon")
    if lat is None or lon is None:
        return None
    t = _dt(r.get("recibido"))
    if not t:
        return None
    for otro, c in ctx.app.items():
        if otro == rid or c.get("plaga") != plaga or c.get("seguimiento_de"):
            continue
        ro = ctx.reportes.get(otro) or {}
        try:
            d = distancia_km(float(lat), float(lon), float(ro["lat"]), float(ro["lon"]))
        except (KeyError, TypeError, ValueError):
            continue
        to = _dt(ro.get("recibido"))
        if not to:
            continue
        h = (t - to).total_seconds() / 3600
        if 0 <= h <= 168 and d < 5:
            return {"reporte_id": otro, "plaga": c.get("plaga"),
                    "distancia_km": round(d, 3), "horas": round(h, 1)}
    return None


def _padre_por_parcela(ctx: Contexto, rid: str) -> str | None:
    """Caso resuelto en la MISMA parcela hace <24 h (aunque tenga visita).

    Lección R-2126: la API sigue considerando seguimiento aunque el padre
    tenga visita. Solo aplica a la misma parcela (R-2159 con otra parcela
    fue caso nuevo).
    """
    r = ctx.reportes.get(rid) or {}
    pid = r.get("parcela_id") or (ctx.app.get(rid) or {}).get("parcela_id")
    if not pid:
        return None
    t = _dt(r.get("recibido"))
    if not t:
        return None
    for otro, c in ctx.app.items():
        if otro == rid or not c.get("es_plaga"):
            continue
        if c.get("plaga") in (None, "desconocida"):
            continue
        ro = ctx.reportes.get(otro) or {}
        if (ro.get("parcela_id") or c.get("parcela_id")) != pid:
            continue
        to = _dt(ro.get("recibido"))
        if not to:
            continue
        h = (t - to).total_seconds() / 3600
        if 0 < h <= 24:
            return otro
    return None


def _padre_y_plaga(ctx: Contexto, rid: str, app: dict, res: dict) -> tuple[str | None, str | None, str | None]:
    """Devuelve (padre_id, plaga_esperada, cultivo_padre) para un seguimiento."""
    seg = app.get("seguimiento_de")
    if not seg:
        # Una respuesta `-R` marca seguimiento_de = su padre (este reporte).
        # Eso es una respuesta a pregunta, no un seguimiento real.
        seg = res.get("seguimiento_de")
        if seg == rid:
            seg = None
    if not seg:
        seg = _padre_por_parcela(ctx, rid)
    if not seg:
        return None, None, None
    padre = ctx.app.get(seg) or {}
    plaga_padre = padre.get("plaga")
    parcela_padre = ctx.parcelas.get(padre.get("parcela_id") or "") or {}
    cultivo = parcela_padre.get("cultivo")
    # Lección R-2193/R-2126: en papa/tizón el seguimiento se califica como
    # `desconocida`, NO con la plaga del padre.
    if plaga_padre == "tizon_tardio" or cultivo == "papa":
        return seg, "desconocida", cultivo
    return seg, plaga_padre, cultivo


def _texto_vago(texto: str | None) -> bool:
    t = (texto or "").lower()
    if not t.strip():
        return True
    señales = ("mancha", "chocolate", "pulgon", "pioj", "roya", "chahuixtle",
               "gusano", "cogollo", "chapulin", "mosquita", "mosquilla",
               "tizon", "hielo", "quemad", "gallina", "raices", "raíz",
               "hoja", "hojas", "fruto", "flor", "tallo", "seca", "podrid",
               "agujer", "perforad", "mordid", "bich", "insect", "larva")
    return not any(s in t for s in señales)


def _pct_confiable(texto: str | None, pct: int | None) -> tuple[bool, str]:
    """Valida el pct con las palabras clave aprendidas."""
    from nivel2 import extraer_pct

    if not texto:
        return True, "sin texto: pct por omisión 10 (criterio oficial)"
    esperado = extraer_pct(texto)
    if pct is None:
        return True, f"pct por omisión ({esperado}%)"
    if int(pct) == int(esperado):
        return True, f"pct {pct}% coherente con el texto"
    return False, f"pct app/motor {pct}% vs texto {esperado}%"


def evaluar(rid: str, ctx: Contexto, intento: int = 1,
            motor: tuple | None = None) -> Decision:
    """Evalúa un reporte. `intento` activa más evidencia (1..4).

    `motor` permite reutilizar la clasificación (IA/STT/visión) ya hecha
    para no gastar tokens en los 4 reintentos.
    """
    app = ctx.app.get(rid, {})
    if motor is None:
        motor = _motor(ctx, rid, con_ia=True)
    res, caso, n, brote, info = motor
    ev: list[str] = []
    dudas: list[str] = []

    # -------- seguimiento -------------------------------------------------
    padre, plaga_esperada, cultivo_padre = _padre_y_plaga(ctx, rid, app, res)
    es_seguimiento = bool(padre)
    if es_seguimiento:
        plaga = plaga_esperada or (res.get("plaga") if res.get("plaga") not in (None, "desconocida") else None)
        payload = {"reporte_id": rid, "es_plaga": True, "plaga": plaga or "desconocida"}
        if plaga is None:
            dudas.append(f"seguimiento de {padre} sin plaga heredable")
        ev.append(f"seguimiento de {padre} ({cultivo_padre or 'cultivo ?'}) -> {plaga or 'desconocida'}")
        # La app y el motor deben coincidir con la plaga esperada.
        app_plaga = app.get("plaga")
        coincide = (app_plaga == plaga) or (app_plaga in (None, "desconocida") and plaga == "desconocida")
        if not coincide:
            dudas.append(f"app dice {app_plaga or '—'} y el patrón del padre espera {plaga or 'desconocida'}")
        certeza = 0.55
        certeza += 0.20 if plaga else 0
        certeza += 0.10 if coincide else 0
        certeza += 0.05 if intento >= 3 else 0
        return Decision(rid, bool(plaga) and coincide and not dudas, min(1.0, certeza),
                        payload, plaga, "; ".join(dudas), "seguimiento",
                        intento, ev, brote=brote, n_brote=n, app=app)

    # -------- caso nuevo --------------------------------------------------
    plaga = res.get("plaga") or app.get("plaga")
    app_plaga = app.get("plaga")
    texto = res.get("texto") or ctx.reportes.get(rid, {}).get("texto") or ""
    parcela = ctx.parcela_de(rid)
    cultivo = parcela.get("cultivo")

    # Texto vago / plaga desconocida
    vago = _texto_vago(texto)
    if plaga in (None, "desconocida"):
        if vago and cultivo == "maíz":
            plaga = "desconocida"
            ev.append("texto vago en maíz: 'desconocida' puntúa 2/2 (R-2042/R-2089/R-2096)")
        elif vago:
            dudas.append(f"texto vago en {cultivo or 'cultivo desconocido'}: 'desconocida' no tiene precedente seguro")
        else:
            dudas.append("el motor no identificó la plaga pese a haber señales")

    # pct y nivel 2 (usamos el motor corregido)
    pct = caso.get("_pct")
    pct_ok, pct_msg = _pct_confiable(texto, pct)
    ev.append(pct_msg)
    if not pct_ok:
        dudas.append(pct_msg)

    semaforo = caso.get("semaforo")
    tecnico = caso.get("tecnico_id")
    app_sem = app.get("semaforo")
    app_tec = app.get("tecnico_id")
    if app_sem and semaforo and app_sem != semaforo:
        ev.append(f"semáforo app {app_sem} vs motor {semaforo} (se usa el motor corregido)")
    if app_tec and tecnico and app_tec != tecnico:
        dudas.append(f"técnico app {app_tec} vs motor {tecnico}")

    # Brote profundo
    brote_final = brote
    if n == 2:
        previo = _misma_parcela_previa(ctx, rid)
        tercero = _tercero_por_coords(ctx, rid, plaga) if intento >= 4 else None
        if previo:
            brote_final = True
            ev.append(f"n=2 + caso previo en la misma parcela {previo['reporte_id']} -> true (R-2160/R-2179)")
        elif tercero:
            brote_final = True
            ev.append(f"n=2 + tercero por coordenadas {tercero['reporte_id']} a {tercero['distancia_km']} km -> true (R-2180)")
        else:
            brote_final = False
            ev.append("n=2 sin mismo-parcela ni tercero por coordenadas -> false (R-2158/R-2167/R-2194)")
    elif n is not None and n >= 3:
        brote_final = True
        ev.append(f"n={n} >= 3 -> true")
    elif n is not None and n <= 1:
        brote_final = False
        ev.append(f"n={n} <= 1 -> false")

    # Parcela inferida
    inferida = app.get("_parcela_inferida")
    if inferida:
        dudas.append(f"parcela inferida {inferida}: no se envía a ciegas")

    # App vs motor en plaga. Si la app quedó desactualizada por un fix ya
    # validado (p. ej. decía desconocida y el motor corregido identifica la
    # plaga con alta confianza), se usa el motor y NO se duda.
    conf = float(res.get("confianza") or 0)
    if app_plaga and plaga and app_plaga != plaga:
        if app_plaga == "desconocida" and plaga != "desconocida" and conf >= 0.85:
            ev.append(f"app desactualizada (decía desconocida); el motor corregido identifica {plaga}")
        else:
            dudas.append(f"plaga app {app_plaga} vs motor {plaga}")
    elif app_plaga == plaga:
        ev.append(f"app y motor coinciden en plaga={plaga}")

    # Confianza del motor
    if conf < 0.55:
        dudas.append(f"confianza del motor baja ({conf:.2f})")
    if res.get("injection"):
        ev.append("intento de inyección detectado; la decisión es 100 % reglas")

    # Payload final: `desconocida` es un caso CON plaga (solo que sin
    # identificar), por eso es_plaga=True y plaga="desconocida".
    es_plaga = plaga is not None
    payload = {"reporte_id": rid, "es_plaga": es_plaga}
    if es_plaga:
        payload["plaga"] = plaga
        if semaforo:
            payload["semaforo"] = semaforo
        if tecnico:
            payload["tecnico_id"] = tecnico
        if brote_final is not None:
            payload["brote"] = brote_final

    # Certeza
    criticos = bool(plaga) and not dudas
    certeza = 0.45
    certeza += 0.15 if plaga else 0
    certeza += 0.10 if brote_final is not None else 0
    certeza += 0.10 if (app_plaga == plaga) else 0
    certeza += 0.05 if (not app_sem or not semaforo or app_sem == semaforo) else 0
    certeza += 0.05 if (not app_tec or not tecnico or app_tec == tecnico) else 0
    certeza += 0.05 if not inferida else 0
    certeza += 0.05 if pct_ok else 0
    certeza += 0.05 if conf >= 0.7 else 0
    if intento >= 2:
        # Consenso reglas vs IA: si el motor con_ia=False coincide en plaga.
        try:
            from api_cliente import ApiCliente
            from clasificador import Clasificador
            clf2 = Clasificador(ApiCliente(), con_ia=False)
            clf2.casos_actuales = dict(ctx.app)
            clf2.reportes_actuales = dict(ctx.reportes)
            res2 = clf2.clasificar_reporte(ctx.reportes[rid])
            if res2.get("plaga") == plaga:
                certeza += 0.05
                ev.append(f"solo-reglas coincide en {plaga}")
            elif res2.get("plaga") in (None, "desconocida") and plaga not in (None, "desconocida"):
                dudas.append(f"solo-reglas no identifica la plaga ({res2.get('plaga')})")
        except Exception as exc:
            ev.append(f"no se pudo correr solo-reglas: {exc}")
    if intento >= 3 and padre:
        certeza += 0.05
    if intento >= 4 and n == 2 and brote_final is not None:
        certeza += 0.05
    certeza = max(0.0, min(1.0, certeza))

    seguro = bool(criticos and not dudas and certeza >= CERTEZA_SEGURA)
    if not seguro and intento >= MAX_REINTENTOS and not dudas and certeza >= CERTEZA_ENVIAR:
        seguro = True
    if not seguro and certeza >= CERTEZA_SEGURA and not dudas:
        seguro = True

    opciones = []
    if payload:
        opciones.append({"texto": "Aceptar payload propuesto", "payload": payload})
        if "brote" in payload:
            sin_brote = dict(payload)
            sin_brote["brote"] = not payload["brote"]
            opciones.append({"texto": "Registrar con brote contrario", "payload": sin_brote})
    opciones.append({"texto": "Dejar en cola para reanálisis conjunto", "payload": None})

    return Decision(rid, seguro, certeza, payload, plaga, "; ".join(dudas),
                    "caso nuevo", intento, ev, opciones, brote_final, n, app)


def decidir(rid: str, ctx: Contexto | None = None) -> Decision:
    """Reanaliza hasta MAX_REINTENTOS y devuelve la mejor decisión."""
    ctx = ctx or Contexto()
    motor = _motor(ctx, rid, con_ia=True)  # una sola llamada a IA/STT/visión
    ultima: Decision | None = None
    for intento in range(1, MAX_REINTENTOS + 1):
        d = evaluar(rid, ctx, intento, motor=motor)
        ultima = d
        if d.seguro:
            d.intentos = intento
            return d
    assert ultima is not None
    ultima.intentos = MAX_REINTENTOS
    ultima.seguro = False
    return ultima


def notificar(decision: Decision, telegram: bool = False) -> bool:
    """Avisa al admin SOLO cuando tras 4 intentos no hubo certeza."""
    if decision.seguro:
        return False
    try:
        from telegram_notificador import alerta_duda_final
        return alerta_duda_final(decision, dry_run=not telegram)
    except Exception as exc:
        print(f"[decision] no se pudo notificar: {exc}")
        return False


# ------------------------------------------------------------------ CLI / prueba
def _ctx_para_prueba() -> Contexto:
    return Contexto()


def probar(rid: str, como_json: bool = False, telegram: bool = False) -> int:
    ctx = _ctx_para_prueba()
    if rid not in ctx.reportes:
        print(f"No encontré {rid}")
        return 1
    d = decidir(rid, ctx)
    if como_json:
        print(json.dumps(d.como_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Reporte {rid}")
        print(f"  seguro: {d.seguro}  certeza: {d.certeza:.0%}  intentos: {d.intentos}")
        print(f"  payload: {json.dumps(d.payload, ensure_ascii=False)}")
        print(f"  duda: {d.duda or '—'}")
        for e in d.evidencias:
            print(f"    · {e}")
        if not d.seguro:
            print("  -> se notificaría al admin (Aceptar / Dejar en cola)")
            notificar(d, telegram=telegram)
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Modelo de decisión autónoma 7_7")
    p.add_argument("--probar", help="Evalúa un reporte (no envía)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--telegram", action="store_true",
                   help="Envía la notificación de duda (solo si no es seguro)")
    p.add_argument("--envios", action="store_true",
                   help="Activa el envío real (también requiere PERMITIR_ENVIOS=1)")
    p.add_argument("--modelo", help="Cambia el modelo de IA para esta corrida")
    args = p.parse_args()
    if args.modelo:
        os.environ["OPENROUTER_MODELO_IA"] = args.modelo
    if args.envios:
        os.environ["PERMITIR_ENVIOS"] = "1"
    if args.probar:
        return probar(args.probar, args.json, args.telegram)
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
