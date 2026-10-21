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

# si el reporte no trae parcela, se infiere el cultivo por cómo habla el productor
CULTIVO_POR_MENCION = {
    "maíz": ["milpa", "maicito", "maizal", "maiz", "maíz", "elotes", "olote"],
    "frijol": ["frijol", "frijolera", "frijolito", "frijolar"],
    "avena": ["avena", "avenita"],
    "haba": ["haba", "habas", "habita"],
    "papa": ["papa", "papita", "papa blanca"],
    "jitomate": ["jitomate", "tomate", "jitomatera", "invernadero"],
    "limón": ["limón", "limon", "limonero", "cítricos", "citricos"],
    "grano almacenado": ["grano almacenado", "bodega", "almacén", "almacen", "troje"],
    "trigo": ["trigo"],
    "calabacita": ["calabacita", "calabaza"],
}


def cargar_catalogo(nombre: str) -> list:
    archivo = CACHE / f"{nombre}.json"
    return json.loads(archivo.read_text(encoding="utf-8"))


class Clasificador:
    def __init__(self, api: ApiCliente | None = None, con_ia: bool = True) -> None:
        self.api = api or ApiCliente()
        self.parcelas = {p["id"]: p for p in cargar_catalogo("parcelas")}
        self.plagas = cargar_catalogo("plagas")
        self.con_ia = con_ia and bool(os.getenv("OPENROUTER_API_KEY"))

    def recargar_catalogo(self) -> None:
        """Vuelve a bajar /plagas y /parcelas de la API.

        Si los organizadores agregan plagas, cultivos o cambian severidades,
        el motor los adopta sin reiniciarse ni tocar código.
        """
        plagas = self.api.get_plagas()
        parcelas = self.api.get_parcelas()
        if plagas:
            self.plagas = plagas
            (CACHE / "plagas.json").write_text(json.dumps(plagas, ensure_ascii=False, indent=2), encoding="utf-8")
        if parcelas:
            self.parcelas = {p["id"]: p for p in parcelas}
            (CACHE / "parcelas.json").write_text(
                json.dumps(parcelas, ensure_ascii=False, indent=2), encoding="utf-8"
            )

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
        cultivo_ctx = cultivo or self.inferir_cultivo(t)

        # 1) trámite/consulta sin señal de plaga -> NO es plaga
        es_admin = any(p in t for p in PATRONES_NO_PLAGA)
        if es_admin and not tiene_senal:
            return {"es_plaga": False, "plaga": None, "confianza": 0.92, "motor": "prefiltro",
                    "razon": "consulta administrativa o saludo"}

        # 2) plaga identificada por señales
        if tiene_senal:
            return self._resultado_plaga(mejor, cultivo_ctx, "texto", t, puntajes[mejor])

        # 2b) señal débil pero con un único candidato posible para el cultivo
        if puntajes and cultivo_ctx:
            compatibles = self.cultivares_compatibles(cultivo_ctx)
            debiles = {k: v for k, v in puntajes.items() if k in compatibles and v >= 1.0}
            if len(debiles) == 1:
                plaga_unica = next(iter(debiles))
                return {"es_plaga": True, "plaga": plaga_unica, "confianza": 0.6,
                        "motor": "senal_debil+cultivo",
                        "razon": f"«{mejor}» es la única opción en {cultivo_ctx}"}

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

    def inferir_cultivo(self, texto_norm: str) -> str | None:
        """Deduce el cultivo cuando el reporte no trae parcela (ej. 'mi milpa')."""
        for cultivo, menciones in CULTIVO_POR_MENCION.items():
            if any(m in texto_norm for m in menciones):
                return cultivo
        return None

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

        if tipo == "foto" and foto and texto:
            # 3.4 Fusión multimodal: pie de foto + análisis visual
            resultado = self._fusion_foto_texto(texto, rid=reporte.get("id"), cultivo=cultivo, audio=audio,
                                               foto=foto, etapa=etapa)
        elif tipo == "texto":
            resultado = self.clasificar_texto(texto, cultivo)
        else:
            # voz y fotos sin pie: motor multimodal (STT/visión) con caché
            resultado = self._motor_multimedia(tipo, texto, audio, foto, cultivo, etapa, rid=reporte.get("id"))

        # 2.7 seguimientos: si responde a otro reporte, se usa como contexto
        padre = self._reporte_padre(reporte)
        if padre:
            resultado = self._aplicar_seguimiento(resultado, padre, cultivo, reporte)

        # anti prompt-injection: NO cambia la decisión, solo se anota
        resultado["injection"] = self.es_prompt_injection(texto or resultado.get("texto"))

        # regla de urgencia (código puro, derivada del catálogo)
        es_plaga = bool(resultado["es_plaga"])
        plaga = resultado.get("plaga")
        resultado["urgente"] = bool(es_plaga and self.es_urgente(plaga))
        return resultado

    def es_urgente(self, plaga_id: str | None) -> bool:
        """Urgencia por catálogo: severidad alta/crítica o cuarentenaria.

        Se deriva de GET /plagas para no romperse si los organizadores cambian
        el catálogo o agregan plagas nuevas. PLAGAS_URGENTES queda de respaldo.
        """
        if not plaga_id:
            return False
        plaga = next((p for p in self.plagas if p["id"] == plaga_id), None)
        if plaga:
            severidad = str(plaga.get("severidad", "")).lower()
            return bool(plaga.get("cuarentenaria")) or severidad in ("alta", "critica", "crítica")
        return plaga_id in PLAGAS_URGENTES

    def _fusion_foto_texto(self, texto, rid, cultivo, audio, foto, etapa) -> dict:
        """Combina lo que dice el productor con lo que ve el modelo de visión."""
        del_texto = self.clasificar_texto(texto, cultivo)
        res = self._multimedia(rid, "foto", audio, foto, cultivo, etapa)
        if res.get("fuente") != "vision" or res.get("es_plaga_sugerida") is None:
            del_texto["motor"] = "texto (sin visión)"
            return del_texto

        vision = self._resultado_vision(res, cultivo)
        t_plaga, v_plaga = del_texto.get("plaga"), vision.get("plaga")
        t_ok = del_texto.get("es_plaga") and t_plaga != "desconocida"
        v_ok = vision.get("es_plaga") and v_plaga != "desconocida"

        # Ambos coinciden -> máxima confianza
        if t_ok and v_ok and t_plaga == v_plaga:
            return {"es_plaga": True, "plaga": t_plaga, "confianza": 0.97, "motor": "fusion",
                    "razon": f"texto y visión coinciden en {t_plaga}"}
        # Solo la imagen identifica -> manda la imagen
        if v_ok and not t_ok:
            vision["motor"] = "fusion (visión)"
            return vision
        # Solo el texto identifica -> manda el texto
        if t_ok and not v_ok:
            del_texto["motor"] = "fusion (texto)"
            return del_texto
        # Conflicto: si el texto es muy específico se respeta, si no, se duda
        if t_ok and v_ok:
            puntaje_texto = self._puntuar_plagas(self.normalizar(texto)).get(t_plaga, 0)
            if puntaje_texto >= 5:
                return {"es_plaga": True, "plaga": t_plaga, "confianza": 0.7, "motor": "fusion (texto fuerte)",
                        "razon": f"texto describe {t_plaga}; visión propuso {v_plaga}"}
            return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.4, "motor": "fusion (conflicto)",
                    "razon": f"texto dice {t_plaga}, visión dice {v_plaga}"}
        # Ninguno identifica: si alguno dice que sí es plaga, no inventamos especie
        if vision.get("es_plaga") or del_texto.get("es_plaga"):
            return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.45, "motor": "fusion",
                    "razon": "es plaga, especie no identificada"}
        return {"es_plaga": False, "plaga": None, "confianza": 0.8, "motor": "fusion",
                "razon": "ni texto ni imagen muestran plaga"}

    def _resultado_vision(self, res: dict, cultivo: str | None) -> dict:
        """Normaliza la salida de visión y la valida contra el cultivo."""
        es = bool(res.get("es_plaga_sugerida"))
        if not es:
            return {"es_plaga": False, "plaga": None, "confianza": float(res.get("confianza", 0.7)),
                    "motor": "vision", "razon": f"visión: no es plaga ({str(res.get('sintomas'))[:80]})"}
        plaga = res.get("plaga_sugerida") or "desconocida"
        compatibles = self.cultivares_compatibles(cultivo)
        if cultivo and plaga != "desconocida" and plaga not in compatibles:
            return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.3, "motor": "vision",
                    "razon": f"visión propuso {plaga}, imposible en {cultivo}"}
        return {"es_plaga": True, "plaga": plaga, "confianza": float(res.get("confianza", 0.5)),
                "motor": "vision", "razon": f"visión: {str(res.get('sintomas'))[:100]}"}

    # ---------- 2.7 seguimientos (respuesta_a) ----------

    def _reporte_padre(self, reporte: dict) -> dict | None:
        """Devuelve el reporte al que éste responde, si existe."""
        padre_id = reporte.get("respuesta_a")
        if not padre_id:
            return None
        archivo = CACHE / "reportes.json"
        if not archivo.exists():
            return None
        try:
            todos = json.loads(archivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return next((r for r in todos if r["id"] == padre_id), None)

    def _aplicar_seguimiento(self, resultado: dict, padre: dict, cultivo: str | None,
                             reporte: dict) -> dict:
        """Usa el caso previo como contexto sin arriesgar una especie inventada.

        - Si el seguimiento identifica plaga propia, se respeta.
        - Si no la identifica pero el padre sí, hereda la plaga del padre
          (solo si es compatible con el cultivo).
        - Si el padre tampoco la tenía, queda "desconocida".
        """
        resultado["seguimiento_de"] = padre.get("id")
        if resultado.get("es_plaga") and resultado.get("plaga") not in (None, "desconocida"):
            resultado["razon"] = f"seguimiento con plaga propia; {resultado.get('razon', '')}"
            return resultado

        plaga_padre = self.clasificar_texto(padre.get("texto"), cultivo).get("plaga") if padre.get("texto") else None
        if not plaga_padre:
            plaga_padre = self._multimedia(padre.get("id"), padre.get("tipo"), padre.get("audio_url"),
                                           padre.get("foto_url"), cultivo, "").get("plaga_sugerida")
        if not plaga_padre or plaga_padre == "desconocida":
            return resultado
        if cultivo and plaga_padre not in self.cultivares_compatibles(cultivo):
            return resultado

        resultado["es_plaga"] = True
        resultado["plaga"] = plaga_padre
        resultado["confianza"] = 0.7
        resultado["motor"] = "seguimiento+padre"
        resultado["razon"] = f"hereda {plaga_padre} del caso {padre.get('id')}"
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

        if fuente in ("stt", "whisper") and (res.get("texto") or res.get("texto_respaldo")):
            return self._clasificar_transcripciones(res, cultivo)

        if fuente == "vision" and res.get("es_plaga_sugerida") is not None:
            return self._resultado_vision(res, cultivo)

        # Sin datos de IA: fallback conservador
        return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.4,
                "motor": f"{tipo}_desconocido",
                "razon": "medio sin clasificar, plaga desconocida"}

    def _clasificar_transcripciones(self, res: dict, cultivo: str | None) -> dict:
        """Consenso entre las dos transcripciones (modelo principal y respaldo).

        Si ambos modelos producen la misma plaga, se acepta con alta confianza.
        Si difieren, gana la transcripción con señal agronómica más fuerte; si
        ninguna tiene señal suficiente, queda "desconocida".
        """
        principal = res.get("texto") or ""
        respaldo = res.get("texto_respaldo") or ""
        mejor = self.clasificar_texto(principal, cultivo)
        mejor["texto"] = principal
        if not respaldo or self.normalizar(respaldo) == self.normalizar(principal):
            mejor["motor"] = "stt+" + mejor.get("motor", "texto")
            mejor["razon"] = "transcripción: " + mejor.get("razon", "")
            return mejor

        alterno = self.clasificar_texto(respaldo, cultivo)
        p1 = mejor.get("plaga") if mejor.get("es_plaga") else None
        p2 = alterno.get("plaga") if alterno.get("es_plaga") else None

        if p1 and p2 and p1 == p2:
            mejor["confianza"] = min(0.97, float(mejor.get("confianza", 0.8)) + 0.03)
            mejor["motor"] = "stt consenso"
            mejor["razon"] = f"los dos modelos coinciden en {p1}"
            mejor["texto_respaldo"] = respaldo
            return mejor

        # eligen la versión con más señal (o la que identifica plaga)
        puntos = lambda r: self._puntuar_plagas(self.normalizar(r.get("texto", "")))
        s1 = max(puntos(mejor).values(), default=0)
        s2 = max(puntos({"texto": respaldo}).values(), default=0)

        if p2 and p2 != p1 and s2 > s1:
            alterno["motor"] = "stt respaldo"
            alterno["razon"] = f"respaldo con más señal ({s2:.1f} vs {s1:.1f})"
            alterno["texto"] = respaldo
            alterno["texto_respaldo"] = principal
            return alterno

        mejor["motor"] = "stt+" + mejor.get("motor", "texto")
        mejor["razon"] = "transcripción: " + mejor.get("razon", "")
        mejor["texto_respaldo"] = respaldo
        return mejor

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
