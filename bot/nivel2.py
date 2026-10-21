"""
nivel2.py — Reglas del Nivel 2: prioridad, semáforo y asignación de técnico.

Todo lo que decide puntos aquí son fórmulas deterministas (código, sin IA),
tal como pide el reto. La única parte interpretativa es extraer el porcentaje
afectado del mensaje del productor, que se resuelve con reglas de lenguaje
("tres cuartas partes" = 75) y, si no hay pista, con el valor por omisión 10.

Fórmulas (sección 7 y 8 de /reglas):

    prioridad = severidad + superficie + etapa        (0..100)
      severidad: baja 15 · media 25 · alta 40 · crítica 50   (máx 50)
      superficie: ha_afectadas = superficie_ha * pct/100
                  puntos = min(25, redondeo_comercial(ha_afectadas / 4 * 25))
      etapa: crítica 25 · susceptible 15 · otra 5           (máx 25)
      plaga cuarentenaria -> 100 (rojo) sin cálculo

    semáforo: rojo 85-100 · naranja 70-84 · amarillo 40-69 · verde 0-39

    técnico: misma especialidad que la plaga, carga < 5 en el momento del
             mensaje, el más cercano a la parcela (haversine, R = 6371 km);
             empates: menor carga y luego menor id; si nadie cumple -> null.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

SEVERIDAD_PUNTOS = {"baja": 15, "media": 25, "alta": 40, "critica": 50, "crítica": 50}
CARGA_MAXIMA = 5
RADIO_TIERRA_KM = 6371.0

# límites del semáforo (incluidos)
UMBRALES_SEMAFORO = [(85, "rojo"), (70, "naranja"), (40, "amarillo"), (0, "verde")]


def redondeo_comercial(valor: float) -> int:
    """Redondeo comercial: 14.06 -> 14 ; 14.5 -> 15."""
    return int(math.floor(valor + 0.5))


# ---------------------------------------------------------------- porcentaje

# porcentajes explícitos: "75%", "75 por ciento", "setenta y cinco por ciento"
_NUMERO_PCT = re.compile(r"(\d{1,3})\s*(?:%|por\s*ciento)")
_PALABRA_PCT = re.compile(r"([a-z]+(?:\s+y\s+[a-z]+)?)\s*(?:%|por\s*ciento)")

_UNIDADES = {"uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
             "seis": 6, "siete": 7, "ocho": 8, "nueve": 9}
_DIECES = {"diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
           "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
           "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintidos": 22,
           "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
           "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
_DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
            "setenta": 70, "ochenta": 80, "noventa": 90}


def _numero_en_palabras(frase: str) -> int | None:
    """Convierte 'setenta y cinco' -> 75, 'veinticinco' -> 25, 'cien' -> 100."""
    frase = frase.strip()
    if frase in ("cien", "ciento"):
        return 100
    if frase in _DIECES:
        return _DIECES[frase]
    if frase in _UNIDADES:
        return _UNIDADES[frase]
    partes = [p.strip() for p in frase.split(" y ")]
    if partes[0] in _DECENAS:
        total = _DECENAS[partes[0]]
        if len(partes) == 2 and partes[1] in _UNIDADES:
            total += _UNIDADES[partes[1]]
        return total
    return None
# fracciones dichas como en el campo
_FRACCIONES = [
    (r"tres\s+cuartas?\s+partes?", 75),
    (r"dos\s+terceras?\s+partes?", 66),
    (r"una\s+tercera\s+parte", 33),
    (r"una\s+cuarta\s+parte|un\s+cuarto", 25),
    (r"una\s+quinta\s+parte", 20),
    (r"una\s+sexta\s+parte", 17),
    (r"\bla\s+mitad\b|\bmedias?\b", 50),
    (r"casi\s+todo|casi\s+toda", 90),
    (r"toda\s+la\s+parcela|todo\s+el\s+terreno|toda\s+la\s+milpa", 100),
]
# "una de cada cuatro matas" -> 25 %
_DE_CADA = re.compile(r"una\s+de\s+cada\s+(\w+)")
_DE_CADA_NUM = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
                "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}

PCT_POR_OMISION = 10


def extraer_pct(texto: str | None) -> int:
    """Porcentaje de parcela afectada según lo que dijo el productor.

    Devuelve 10 cuando el mensaje no lo dice (mismo criterio que /casos-previos).
    """
    if not texto:
        return PCT_POR_OMISION
    t = texto.lower().replace("á", "a").replace("é", "e").replace("í", "i")
    t = t.replace("ó", "o").replace("ú", "u").replace("ñ", "n")

    # 1) porcentaje numérico explícito
    if (m := _NUMERO_PCT.search(t)):
        return max(1, min(100, int(m.group(1))))
    # 2) porcentaje escrito con palabras
    if (m := _PALABRA_PCT.search(t)):
        valor = _numero_en_palabras(m.group(1))
        if valor:
            return max(1, min(100, valor))
    # 3) fracciones típicas del habla
    for patron, valor in _FRACCIONES:
        if re.search(patron, t):
            return valor
    # 4) "una de cada N matas"
    if (m := _DE_CADA.search(t)):
        palabra = m.group(1)
        n = _DE_CADA_NUM.get(palabra) or (int(palabra) if palabra.isdigit() else None)
        if n and n > 0:
            return max(1, min(100, round(100 / n)))
    return PCT_POR_OMISION


# ---------------------------------------------------------------- prioridad

def calcular_prioridad(plaga: dict, parcela: dict, pct: float) -> int:
    """Prioridad 0-100 = severidad + superficie + etapa."""
    if plaga.get("cuarentenaria"):
        return 100

    severidad = SEVERIDAD_PUNTOS.get(str(plaga.get("severidad", "")).lower(), 15)

    superficie_ha = float(parcela.get("superficie_ha") or 0)
    ha_afectadas = superficie_ha * float(pct) / 100
    puntos_superficie = min(25, redondeo_comercial(ha_afectadas / 4 * 25))

    cultivo = parcela.get("cultivo")
    etapa = parcela.get("etapa")
    criticas = (plaga.get("etapas_criticas") or {}).get(cultivo) or []
    susceptibles = (plaga.get("etapas_susceptibles") or {}).get(cultivo) or []
    if etapa in criticas:
        puntos_etapa = 25
    elif etapa in susceptibles:
        puntos_etapa = 15
    else:
        puntos_etapa = 5

    return max(0, min(100, severidad + puntos_superficie + puntos_etapa))


def calcular_semaforo(prioridad: int) -> str:
    for umbral, color in UMBRALES_SEMAFORO:
        if prioridad >= umbral:
            return color
    return "verde"


# ---------------------------------------------------------------- técnicos

def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine con radio terrestre de 6371 km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(a))


def elegir_tecnico(tecnicos: list[dict], plaga: dict, parcela: dict) -> str | None:
    """Técnico de la especialidad, con carga < 5, el más cercano a la parcela."""
    if not tecnicos or not parcela:
        return None
    especialidad = plaga.get("especialidad")
    try:
        lat, lon = float(parcela["lat"]), float(parcela["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    candidatos = [
        t for t in tecnicos
        if t.get("especialidad") == especialidad
        and (t.get("carga") or 0) < CARGA_MAXIMA
        and t.get("lat") is not None and t.get("lon") is not None
    ]
    if not candidatos:
        return None

    candidatos.sort(key=lambda t: (
        distancia_km(float(t["lat"]), float(t["lon"]), lat, lon),
        t.get("carga") or 0,
        t.get("id") or "",
    ))
    return candidatos[0]["id"]


@dataclass
class ResultadoNivel2:
    pct: int
    prioridad: int
    semaforo: str
    tecnico_id: str | None
    detalle: str

    def como_dict(self) -> dict:
        return {
            "pct": self.pct,
            "prioridad": self.prioridad,
            "semaforo": self.semaforo,
            "tecnico_id": self.tecnico_id,
        }


def resolver(plaga: dict, parcela: dict, texto: str | None, tecnicos: list[dict],
             pct_ia: int | None = None) -> ResultadoNivel2:
    """Aplica las tres reglas en orden y devuelve el bloque del caso.

    `pct_ia` es el porcentaje que interpretó la IA (paso 2); si viene, se usa
    en la prioridad; si no, se extrae del texto (o 10 por omisión).
    """
    pct = extraer_pct(texto) if pct_ia is None else max(0, min(100, int(pct_ia)))
    prioridad = calcular_prioridad(plaga, parcela, pct)
    semaforo = calcular_semaforo(prioridad)
    tecnico = elegir_tecnico(tecnicos, plaga, parcela)
    detalle = (f"pct={pct}% · sev={plaga.get('severidad')} · "
               f"{parcela.get('superficie_ha')}ha/{parcela.get('etapa')} · "
               f"prioridad={prioridad} ({semaforo}) · tecnico={tecnico}")
    return ResultadoNivel2(pct=pct, prioridad=prioridad, semaforo=semaforo,
                           tecnico_id=tecnico, detalle=detalle)


# ---------------------------------------------------------------- brote

# Regla de la sección 9 del reto: 3+ casos (contando el actual) de la misma
# plaga, a menos de 5 km, recibidos en los últimos 7 días (168 h).
RADIO_BROTE_KM = 5.0
VENTANA_BROTE_HORAS = 168
MINIMO_CASOS_BROTE = 3
# La hora oficial del reto es la del centro de México (UTC-6).
ZONA_HORARIA_RETO = timezone(timedelta(hours=-6))


def _a_datetime(valor) -> datetime | None:
    """Devuelve un datetime con zona horaria (acepta ISO 8601 o datetime)."""
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=ZONA_HORARIA_RETO)
    if not isinstance(valor, str):
        return None
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Sin zona: se asume la hora del reto (UTC-6), como /casos-previos.
        dt = dt.replace(tzinfo=ZONA_HORARIA_RETO)
    return dt


def contar_casos_cercanos(plaga: str, lat, lon, recibido, referencias: list[dict],
                          radio_km: float = RADIO_BROTE_KM,
                          ventana_horas: float = VENTANA_BROTE_HORAS) -> int:
    """Cuenta los casos de la misma plaga a menos de `radio_km` que llegaron
    entre `recibido - ventana_horas` y `recibido` (inclusive).

    `referencias` es una lista de dicts con ``plaga``, ``lat``, ``lon`` y
    ``recibido``. Si el propio caso está en la lista (distancia 0, misma
    hora), se cuenta a sí mismo, tal como pide el reglamento.
    """
    t_ref = _a_datetime(recibido)
    if t_ref is None or lat is None or lon is None:
        return 0
    limite = t_ref - timedelta(hours=ventana_horas)
    total = 0
    for ref in referencias:
        if ref.get("plaga") != plaga:
            continue
        try:
            rlat, rlon = float(ref["lat"]), float(ref["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            if distancia_km(float(lat), float(lon), rlat, rlon) >= radio_km:
                continue
        except (TypeError, ValueError):
            continue
        t_otro = _a_datetime(ref.get("recibido"))
        if t_otro is None:
            continue
        if limite <= t_otro <= t_ref:
            total += 1
    return total


def es_brote(plaga: str, lat, lon, recibido, referencias: list[dict],
             minimo: int = MINIMO_CASOS_BROTE, **otras) -> bool:
    """Verdadero si hay al menos `minimo` casos (contando este) de la misma
    plaga a menos de 5 km en los últimos 7 días."""
    return contar_casos_cercanos(plaga, lat, lon, recibido, referencias, **otras) >= minimo
