"""
clasificador.py — Motor de clasificación Alerta Plaga (equipo 7_7).

Capas, en orden:
  1. Pre-filtro: mensajes que NO son de plaga (saludos, trámites, horarios,
     cursos, juntas, etc.) -> es_plaga=False.
  2. Anti prompt-injection: detecta intentos ("ignora tus instrucciones",
     "prioridad máxima", ...) y los neutraliza (no cambia la decisión).
  3. Cruce determinista parcela->cultivo: restringe candidatas según el
     cultivo de la parcela (catálogo oficial).
  4. Motores de contenido: texto (reglas por sinonimias/síntomas), fotos
     (visión por llamada al modelo, si hay OPENROUTER key válida),
     voz (transcripción + texto). Si no hay datos suficientes o la
     confianza es baja -> plaga "desconocida" (nunca resta puntos).
  5. Regla de urgencia 100% en código (sin IA).

La API del hackathon está en api_cliente.ApiCliente.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from api_cliente import ApiCliente

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache"

# ---- catálogo de plagas (ids oficiales) ----
PLAGAS_URGENTES = {
    "gusano_cogollero",
    "roya_frijol",
    "tizon_tardio",
    "chapulin",
    "hlb",
    "gorgojo_khapra",
}
# Urgente si es_plaga y su id está en el conjunto (regla 100% determinista)

# ---- mensajes que NO son de plaga: patrones fuertes (trámites, saludos, precios) ----
PATRONES_NO_PLAGA = [
    "para saludar", "nomás para saludar", "nomas para saludar", "solo para saludar",
    "platica", "plática", "curso", "capacitacion", "capacitación", "taller",
    "junta", "ejidatario", "asamblea", "reunion", "reunión",
    "que hora abren", "hora abren", "abren la oficina", "oficina", "horario",
    "precio", "precios", "pagando", "kilo", "vender", "compra", "cuanto cuesta",
    "apoyo", "gobierno", "semilla", "programa", "subsidio", "solicitud", "papeles",
    "tramite", "trámite", "credito", "crédito", "prestamo", "préstamo",
    "inscripcion", "inscripción", "constancia",
    "que pidieron", "llegaron los", "cuando llega el fertilizante", "es cierto",
    "feliz dia", "feliz día", "felicidades", "bendiciones",
]

# ---- señales de plaga ponderadas (incluye variantes ruidosas de Whisper) ----
SENALES_PLAGA: dict[str, dict[str, float]] = {
    "gusano_cogollero": {
        "cogollero": 3, "cogollo": 3, "cojo ": 2, "cohollo": 3, "corollo": 3,
        "gusano del cogollo": 3, "gusano soldado": 2, "gusano verde": 3,
        "gusanos verdes": 3, "gusanito": 1.5, "gusano": 1.2,
        "excremento": 2.5, "aserrin": 2.5, "acerrin": 2.5, "acerin": 2.5,
        "cernin": 2.5, "serrin": 2.5, "como acerrin": 2.5,
        "rayitas": 2, "hojas rotas": 2, "raspadas": 1.5, "agujer": 2, "perforad": 2,
    },
    "roya_frijol": {
        "chahuixtle": 3, "roya": 3, "roy a": 3, "polvillo": 3, "polvito": 2,
        "polvo color oxido": 3, "color oxido": 2.5, "herrumbre": 2.5,
        "granitos cafes": 2.5, "puntitos cafes": 2.5, "se le pega a uno en los dedos": 2.5,
    },
    "tizon_tardio": {
        "tizon": 3, "hielo": 2.5, "quemazon": 2.5, "quemad": 2.5,
        "huele a podrido": 3, "podrido": 2.5, "moho blanco": 2.5,
        "manchas cafes": 2, "manchas cafe": 2, "mancha negra": 2,
        "negra la planta": 2, "se puso negra": 2,
    },
    "pulgon": {
        "pulgon": 3, "piojillo": 3, "piojo": 2.5, "piojito": 2.5,
        "animalitos verdes": 2.5, "bichitos": 2, "mielecilla": 2.5,
        "fumagina": 2.5, "hollin": 2.5, "cobojin": 2.5,
        "pegajos": 1.5, "como con miel": 2, "tapizada": 1.5, "tapizadas": 1.5,
    },
    "gallina_ciega": {
        "gallina ciega": 3, "nixticuil": 3, "gusano blanco": 3,
        "raices comidas": 3, "sin raiz": 3, "salen sin raiz": 3,
        "arrancan facil": 2.5, "se arrancan": 2, "marchita": 1.5,
        "larvas blancas": 2.5, "acamadas": 2,
    },
    "mosquita_blanca": {
        "mosquita blanca": 3, "mosquitas blancas": 3, "mosquilla": 3, "mosquita": 2.5,
        "mosquitas": 2.5, "palomilla blanca": 3,
        "amarillas y pegajosas": 2.5, "hojas pegajosas": 1.5,
    },
    "chapulin": {
        "chapulin": 3, "chapulines": 3, "chapulina": 3, "chapulinada": 3,
        "langosta": 2.5, "saltamontes": 3, "brincan": 2,
        "matas peladas": 2.5, "defoliada": 2,
    },
    "mancha_chocolate": {
        "mancha de chocolate": 3, "chocolate": 2.5, "manchita cafe": 2,
        "manchas cafe rojizo": 2.5, "manchas redondas": 2,
    },
    "hlb": {
        "dragon amarillo": 3, "hlb": 3, "enverdecimiento": 3,
        "moteado amarillo": 2.5, "psilido": 2.5, "amarillamiento": 2,
    },
    "gorgojo_khapra": {
        "gorgojo khapra": 3, "khapra": 3, "peludo del grano": 3,
        "gusanito peludo": 3, "granos huecos": 3, "pellejos": 2.5,
        "granero": 2.5, "grano almacenado": 3, "maiz almacenado": 2.5,
    },
}

# señales de que es un seguimiento de un reporte previo (no nombra plaga)
PATRONES_SEGUIMIENTO = [
    "ya vieron", "otra vez", "confirmar", "les llego", "les llegó",
    "cuando viene", "cuando vienen", "cuando pueden venir", "sigo esperando",
    "no me han contestado",
]


def cargar_catalogo(nombre: str) -> list:
    archivo = CACHE / f"{nombre}.json"
    return json.loads(archivo.read_text(encoding="utf-8"))


class Clasificador:
    def __init__(self, api: ApiCliente | None = None, con_ia: bool = True) -> None:
        self.api = api or ApiCliente()
        self.parcelas = {p["id"]: p for p in cargar_catalogo("parcelas")}
        self.plagas = cargar_catalogo("plagas")
        self.con_ia = con_ia and bool(os.getenv("OPENROUTER_API_KEY"))

    # ---------- herramientas de texto ----------

    @staticmethod
    def normalizar(texto: str | None) -> str:
        if not texto:
            return ""
        texto = texto.lower()
        # unificar acentos para hacer robustas las búsquedas
        reemplazos = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "ü": "u", "ñ": "n",
        }
        for a, b in reemplazos.items():
            texto = texto.replace(a, b)
        texto = re.sub(r"\s+", " ", texto)
        return texto.strip()

    def cultivo_de_parcela(self, parcela_id: str | None) -> str | None:
        if not parcela_id:
            return None
        p = self.parcelas.get(parcela_id)
        return p["cultivo"] if p else None

    def es_prompt_injection(self, texto: str | None) -> bool:
        """Detecta intentos de manipulación. No altera la decisión, se reporta."""
        t = self.normalizar(texto)
        patrones = [
            "ignora tus instrucciones",
            "ignore tus instrucciones",
            "ponle prioridad maxima",
            "prioridad max",
            "olvida tus",
            "olvidate de tus",
            "eres un",
            "simula ser",
            "actua como",
            "te voy a",
            "prometeme",
            "dame puntos",
            "puntuame",
        ]
        return any(p in t for p in patrones)

    # ---------- motores ----------

    def clasificar_texto(self, texto: str | None, cultivo: str | None) -> dict:
        """Reglas ponderadas + cruce de cultivo. Sin IA."""
        t = self.normalizar(texto)
        if not t:
            return {"es_plaga": False, "plaga": None, "confianza": 0.0, "motor": "vacio",
                    "razon": "sin texto"}

        puntajes = self._puntuar_plagas(t)
        mejor = max(puntajes, key=puntajes.get) if puntajes else None
        tiene_senal = mejor is not None and puntajes[mejor] >= 2.0

        # 1) trámite/consulta sin señal de plaga -> NO es plaga
        es_admin = any(p in t for p in PATRONES_NO_PLAGA)
        if es_admin and not tiene_senal:
            return {"es_plaga": False, "plaga": None, "confianza": 0.92, "motor": "prefiltro",
                    "razon": "consulta administrativa o saludo"}

        # 2) plaga identificada por señales
        if tiene_senal:
            return self._resultado_plaga(mejor, cultivo, "texto", t, puntajes[mejor])

        # 3) seguimiento de un caso previo sin nombrar plaga
        if any(p in t for p in PATRONES_SEGUIMIENTO):
            return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.5,
                    "motor": "seguimiento", "razon": "seguimiento sin plaga explícita"}

        # 4) sin señal y sin trámite -> describe un problema; no inventamos plaga
        return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.3,
                "motor": "texto_desconocida",
                "razon": "describe problema sin plaga identificable"}

    def _puntuar_plagas(self, t: str) -> dict[str, float]:
        """Suma pesos de las señales encontradas por plaga."""
        puntajes: dict[str, float] = {}
        for plaga_id, senales in SENALES_PLAGA.items():
            total = sum(peso for patron, peso in senales.items() if patron in t)
            if total:
                puntajes[plaga_id] = total
        return puntajes

    def cultivares_compatibles(self, cultivo: str | None) -> set[str]:
        """IDs de plaga posibles para un cultivo según el catálogo."""
        if not cultivo:
            return {p["id"] for p in self.plagas}
        return {p["id"] for p in self.plagas if cultivo in set(p.get("cultivos", []))}

    def _resultado_plaga(self, plaga_id: str, cultivo: str | None, motor: str,
                         texto_norm: str, puntaje: float = 0.0) -> dict:
        """Cruza la plaga detectada con el cultivo de la parcela."""
        compatibles = self.cultivares_compatibles(cultivo)
        if cultivo and plaga_id not in compatibles:
            # La señal no encaja con el cultivo: buscamos la mejor alternativa válida
            puntajes = self._puntuar_plagas(texto_norm)
            alternativas = {k: v for k, v in puntajes.items()
                            if k in compatibles and v >= 2.0 and k != plaga_id}
            if alternativas:
                alt = max(alternativas, key=alternativas.get)
                return {"es_plaga": True, "plaga": alt, "confianza": 0.55, "motor": motor,
                        "razon": f"señal reasignada al cultivo {cultivo}"}
            return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.2, "motor": motor,
                    "razon": f"señal incompatible con cultivo {cultivo}"}

        confianza = 0.9 if cultivo and plaga_id in compatibles else 0.75
        if puntaje >= 5:
            confianza = min(0.97, confianza + 0.05)
        return {"es_plaga": True, "plaga": plaga_id, "confianza": confianza, "motor": motor,
                "razon": f"señal compatible con {cultivo or 'cultivo desconocido'} (score {puntaje:.1f})"}

    # ---------- orquestación por reporte ----------

    def clasificar_reporte(self, reporte: dict) -> dict:
        tipo = reporte.get("tipo")
        parcela_id = reporte.get("parcela_id")
        cultivo = self.cultivo_de_parcela(parcela_id)
        texto = reporte.get("texto")
        audio = reporte.get("audio_url")
        foto = reporte.get("foto_url")

        etapa = self.parcelas.get(parcela_id, {}).get("etapa", "") if parcela_id else ""
        resultado: dict
        if tipo == "texto" or (tipo == "foto" and texto and self._texto_tiene_senal(texto)):
            resultado = self.clasificar_texto(texto, cultivo)
        else:
            # voz y fotos: motor multimodal (whisper/visión) con caché
            resultado = self._motor_multimedia(tipo, texto, audio, foto, cultivo, etapa, rid=reporte.get("id"))

        # anti prompt-injection: NO cambia la decisión, solo se anota
        resultado["injection"] = self.es_prompt_injection(texto or resultado.get("texto"))

        # regla de urgencia (código puro)
        es_plaga = bool(resultado["es_plaga"])
        plaga = resultado.get("plaga")
        resultado["urgente"] = es_plaga and plaga in PLAGAS_URGENTES
        return resultado

    def _texto_tiene_senal(self, texto: str | None) -> bool:
        """Evita mandar a visión captions vacíos o puramente descriptivos."""
        t = self.normalizar(texto)
        return bool(t) and not any(
            w in t for w in ["mándo", "mando", "mire", "mira", "asi", "como esta", "que sera"]
        )

    def _motor_multimedia(self, tipo, texto, audio, foto, cultivo, etapa="", rid=None) -> dict:
        """Usa transcripción/visión (caché primero) y valida contra el cultivo."""
        # Reglas de cultivo exclusivo (deterministas, alta señal):
        # limón -> solo hlb ; grano almacenado -> solo gorgojo_khapra
        cultivo_exclusivo = {"limón": "hlb", "grano almacenado": "gorgojo_khapra"}
        if cultivo in cultivo_exclusivo and (foto or audio):
            return {"es_plaga": True, "plaga": cultivo_exclusivo[cultivo],
                    "confianza": 0.6, "motor": "cultivo_exclusivo",
                    "razon": f"parcela de {cultivo}, único candidato {cultivo_exclusivo[cultivo]}"}

        res = self._multimedia(rid, tipo, audio, foto, cultivo, etapa)
        fuente = res.get("fuente")

        if fuente == "whisper" and res.get("texto"):
            base = self.clasificar_texto(res["texto"], cultivo)
            base["motor"] = "whisper+" + base.get("motor", "texto")
            base["texto"] = res["texto"]
            base["razon"] = "transcripción: " + base.get("razon", "")
            return base

        if fuente == "vision" and res.get("es_plaga_sugerida") is not None:
            es = bool(res["es_plaga_sugerida"])
            if not es:
                return {"es_plaga": False, "plaga": None,
                        "confianza": float(res.get("confianza", 0.7)), "motor": "vision",
                        "razon": f"visión: no es plaga ({str(res.get('sintomas'))[:80]})"}
            plaga = res.get("plaga_sugerida") or "desconocida"
            # validación contra el cultivo (evita alucinaciones imposibles)
            compatibles = self.cultivares_compatibles(cultivo)
            if cultivo and plaga != "desconocida" and plaga not in compatibles:
                return {"es_plaga": True, "plaga": "desconocida",
                        "confianza": 0.3, "motor": "vision",
                        "razon": f"visión propuso {plaga}, imposible en {cultivo}"}
            return {"es_plaga": True, "plaga": plaga,
                    "confianza": float(res.get("confianza", 0.5)), "motor": "vision",
                    "razon": f"visión: {str(res.get('sintomas'))[:100]}"}

        # Sin datos de IA: fallback conservador
        return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.4,
                "motor": f"{tipo}_desconocido",
                "razon": "medio sin clasificar, plaga desconocida"}

    def _multimedia(self, rid, tipo, audio, foto, cultivo, etapa) -> dict:
        """Lee el resultado multimodal de caché o llama a la IA (una sola vez)."""
        cache_file = CACHE / "multimedia.json"
        cache: dict = {}
        if cache_file.exists():
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        if rid and rid in cache and not cache[rid].get("error"):
            return cache[rid]
        if not self.con_ia:
            return {"fuente": "ninguna"}
        try:
            from motor_audio_foto import procesar_reporte_multimedia

            res = procesar_reporte_multimedia(
                {"tipo": tipo, "audio_url": audio, "foto_url": foto}, cultivo or "", etapa or "",
                candidatas=sorted(self.cultivares_compatibles(cultivo)),
            )
        except Exception as exc:  # pragma: no cover
            return {"fuente": "ninguna", "error": str(exc)}
        if rid and not res.get("error"):
            cache[rid] = res
            cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        return res


def resultados_a_casos(reportes: list, clasif: Clasificador) -> list[dict]:
    """Convierte la clasificación al formato de POST /casos."""
    casos = []
    for r in reportes:
        res = clasif.clasificar_reporte(r)
        caso = {
            "reporte_id": r["id"],
            "es_plaga": bool(res["es_plaga"]),
            "plaga": res.get("plaga") if res.get("es_plaga") else None,
            "urgente": bool(res.get("urgente", False)),
        }
        if not caso["es_plaga"]:
            caso["plaga"] = None
        casos.append(caso)
    return casos


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    api = ApiCliente()
    clf = Clasificador(api, con_ia=False)
    reportes = cargar_catalogo("reportes")
    for r in reportes:
        res = clf.clasificar_reporte(r)
        caso = resultados_a_casos([r], clf)[0]
        print(f"{r['id']:<7} {r['tipo']:<6} plaga={str(caso['plaga']):<18} urg={str(caso['urgente']):<5} "
              f"conf={res['confianza']:.2f} inj={res['injection']} | {res['razon'][:70]}")
