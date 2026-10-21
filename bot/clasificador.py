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
from datetime import timedelta
from pathlib import Path

from api_cliente import ApiCliente
from nivel2 import _a_datetime, contar_casos_cercanos, resolver as resolver_nivel2
from nivel2 import MINIMO_CASOS_BROTE  # noqa: E402 (mismo módulo, import explícito)

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


def cargar_previos() -> list:
    """Casos de la semana pasada con respuesta correcta (GET /casos-previos)."""
    archivo = CACHE / "cache_casos_previos.json"
    if not archivo.exists():
        return []
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


class Clasificador:
    def __init__(self, api: ApiCliente | None = None, con_ia: bool = True) -> None:
        self.api = api or ApiCliente()
        self.parcelas = {p["id"]: p for p in cargar_catalogo("parcelas")}
        self.plagas = cargar_catalogo("plagas")
        self.con_ia = con_ia and bool(os.getenv("OPENROUTER_API_KEY"))
        self.ia_texto = self.con_ia and os.getenv("INTERPRETAR_IA", "0") == "1"
        self._interpretador = None
        self._tecnicos_cache: dict[str, list] = {}
        self._visitas: set[str] | None = None

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

    # ---------- paso 2: INTERPRETAR con IA (JSON estricto + respaldo) ----------
    def _interpretar_con_ia(self, texto: str | None, cultivo: str | None) -> dict | None:
        """Interpreta el mensaje con la IA (OpenRouter, JSON estricto).

        Solo se usa si INTERPRETAR_IA=1 (viene del flujo oficial del reto).
        Si no hay API, timeout o JSON inválido, devuelve None y el llamador
        usa las reglas deterministas (nunca se arriesga un punto por un fallo).
        """
        if not self.ia_texto or not texto:
            return None
        try:
            if self._interpretador is None:
                from interpretar import InterpretadorIA

                self._interpretador = InterpretadorIA()
            if not self._interpretador.disponible():
                return None
            candidatas = self.cultivares_compatibles(cultivo) if cultivo else None
            resultado = self._interpretador.interpretar(texto, cultivo, candidatas or None)
            if resultado and "pct" in resultado:
                resultado["pct_ia"] = resultado.pop("pct")
            return resultado
        except Exception as exc:
            print(f"[ia_texto] falló, uso reglas: {exc}")
            return None

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
            # Paso 2 del reto: IA estricta si está activada; si no, reglas.
            resultado = self._interpretar_con_ia(texto, cultivo)
            if resultado is None:
                resultado = self.clasificar_texto(texto, cultivo)
        else:
            # voz y fotos sin pie: motor multimodal (STT/visión) con caché
            resultado = self._motor_multimedia(tipo, texto, audio, foto, cultivo, etapa, rid=reporte.get("id"))

        # 2.7 seguimientos: si responde a otro reporte, o hay un caso abierto
        # del mismo productor/parcela hace <24 h sin visita, se usa como contexto
        padre = self._reporte_padre(reporte)
        if not padre:
            padre = self._reporte_padre_por_ventana(reporte)
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

    # ---------- Nivel 2: prioridad, semáforo y técnico ----------

    def tecnicos_en(self, momento: str | None) -> list:
        """GET /tecnicos?momento=<recibido>, con caché por momento.

        La carga cambia con el tiempo, así que la consulta se hace con la hora
        del mensaje y no con la hora de procesamiento (regla del reto).
        """
        clave = momento or "ahora"
        if clave in self._tecnicos_cache:
            return self._tecnicos_cache[clave]
        try:
            datos = self.api.get("tecnicos", {"momento": momento}) or []
        except Exception:
            datos = []
        self._tecnicos_cache[clave] = datos
        return datos

    def resolver_nivel2(self, reporte: dict, plaga_id: str, resultado: dict) -> dict:
        """Calcula pct, prioridad, semáforo y técnico para un caso nuevo."""
        if not plaga_id or plaga_id == "desconocida":
            return {}
        parcela = self.parcelas.get(reporte.get("parcela_id") or "")
        plaga = next((p for p in self.plagas if p["id"] == plaga_id), None)
        if not parcela or not plaga:
            return {}

        texto = resultado.get("texto") or reporte.get("texto") or ""
        tecnicos = self.tecnicos_en(reporte.get("recibido"))
        n2 = resolver_nivel2(plaga, parcela, texto, tecnicos,
                             pct_ia=resultado.get("pct_ia"))
        datos = n2.como_dict()
        datos["detalle_nivel2"] = n2.detalle
        return datos

    # ---------- 9. Brote (regla global, sin IA) ----------
    def brotes_de_casos(self, casos: list[dict], reportes_por_id: dict,
                        previos: list | None = None) -> dict[str, bool]:
        """Evalúa la regla de brote para cada caso y devuelve {reporte_id: bool}.

        Regla (sección 9 del reto): hay brote si, contando el caso actual, hay
        3+ casos de la misma plaga a menos de 5 km recibidos en los últimos
        7 días (168 h, incluido el momento del mensaje). Cuentan los casos de
        GET /casos-previos y los casos propios encontrados por el sistema.
        No cuentan los seguimientos, los mensajes que no son reportes ni los
        que quedaron como "desconocida". La hora es la `recibido` del mensaje.

        Si un caso no tiene parcela con coordenadas o plaga aclarada, queda
        fuera del resultado (no se manda el campo, no se califica).
        """
        if previos is None:
            previos = cargar_previos()
        referencias: list[dict] = [
            {"plaga": p["plaga"], "lat": p["lat"], "lon": p["lon"],
             "recibido": p.get("recibido")}
            for p in previos
            if p.get("plaga") and p.get("plaga") != "desconocida"
            and p.get("lat") is not None and p.get("lon") is not None
        ]

        elegibles: list[dict] = []
        for c in casos:
            if not (c.get("es_plaga") and c.get("plaga")
                    and c.get("plaga") != "desconocida"):
                continue
            if c.get("seguimiento_de"):
                continue  # los seguimientos no cuentan para el brote
            r = reportes_por_id.get(c["reporte_id"]) or {}
            if r.get("respuesta_a"):
                continue
            parcela = self.parcelas.get(r.get("parcela_id") or "")
            if not parcela:
                continue
            try:
                lat, lon = float(parcela["lat"]), float(parcela["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            referencia = {"plaga": c["plaga"], "lat": lat, "lon": lon,
                          "recibido": r.get("recibido")}
            referencias.append(referencia)
            elegibles.append({"rid": c["reporte_id"], **referencia})

        resultado: dict[str, bool] = {}
        for e in elegibles:
            n = contar_casos_cercanos(e["plaga"], e["lat"], e["lon"],
                                      e["recibido"], referencias)
            resultado[e["rid"]] = n >= MINIMO_CASOS_BROTE
        return resultado

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

    def _reporte_padre_por_ventana(self, reporte: dict) -> dict | None:
        """Seguimiento por regla del reto: mismo productor o parcela con un
        caso abierto hace menos de 24 h y sin visita registrada (GET /visitas).

        Solo cuenta mensajes recibidos ANTES que el actual. Si el caso abierto
        más reciente ya tiene visita, no es seguimiento (ya fue atendido).
        """
        t_actual = _a_datetime(reporte.get("recibido"))
        if t_actual is None:
            return None
        parcela_id = reporte.get("parcela_id")
        productor_id = reporte.get("productor_id")
        if not (parcela_id or productor_id):
            return None

        if self._visitas is None:
            try:
                self._visitas = {str(v.get("reporte_id")) for v in cargar_catalogo("visitas")}
            except Exception:
                self._visitas = set()
        try:
            todos = cargar_catalogo("reportes")
        except Exception:
            todos = []

        limite = t_actual - timedelta(hours=24)
        candidatos = []
        for r in todos:
            if r.get("id") == reporte.get("id"):
                continue
            mismo = ((parcela_id and r.get("parcela_id") == parcela_id)
                     or (productor_id and r.get("productor_id") == productor_id))
            if not mismo:
                continue
            t_r = _a_datetime(r.get("recibido"))
            if t_r is None or not (limite <= t_r <= t_actual):
                continue
            candidatos.append((t_r, r))
        if not candidatos:
            return None
        candidatos.sort(key=lambda x: x[0], reverse=True)
        mas_reciente = candidatos[0][1]
        if mas_reciente["id"] in self._visitas:
            return None
        return mas_reciente

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
    """Convierte la clasificación al formato de POST /casos (Nivel 2 incluido)."""
    casos = []
    for r in reportes:
        res = clasif.clasificar_reporte(r)
        es_plaga = bool(res["es_plaga"])
        plaga = res.get("plaga") if es_plaga else None
        caso = {
            "reporte_id": r["id"],
            "es_plaga": es_plaga,
            "plaga": plaga,
            "seguimiento_de": res.get("seguimiento_de"),
        }

        # un seguimiento NO abre caso nuevo: la plaga se hereda pero no lleva
        # semáforo, técnico ni brote (tabla de puntos de la sección 4 del reto)
        if (es_plaga and plaga and plaga != "desconocida"
                and not res.get("seguimiento_de")):
            nivel2 = clasif.resolver_nivel2(r, plaga, res)
            if nivel2:
                caso["semaforo"] = nivel2["semaforo"]
                caso["tecnico_id"] = nivel2["tecnico_id"]
                caso["prioridad"] = nivel2["prioridad"]
                caso["_nivel2"] = nivel2["detalle_nivel2"]
                caso["_pct"] = nivel2["pct"]

        # compatibilidad con el dashboard (el campo urgente ya no se califica)
        caso["urgente"] = caso.get("semaforo") in ("rojo", "naranja")
        casos.append(caso)

    # Brote: regla global (previos + casos propios), se decide con el conjunto
    # completo para no depender del orden en que llegaron los reportes.
    try:
        brotes = clasif.brotes_de_casos(casos, {r["id"]: r for r in reportes})
    except Exception:
        brotes = {}
    for c in casos:
        if c["reporte_id"] in brotes:
            c["brote"] = brotes[c["reporte_id"]]
    return casos


# campos que acepta POST /casos (flujo oficial del reto, paso 5);
# `prioridad` es opcional (no da puntos, solo retroalimentación).
CAMPOS_API = ("reporte_id", "es_plaga", "plaga", "semaforo", "tecnico_id",
              "prioridad", "brote")


def caso_para_api(caso: dict) -> dict:
    """Deja solo lo que la API entiende (descarta claves internas como _pct)."""
    return {k: v for k, v in caso.items() if k in CAMPOS_API}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    api = ApiCliente()
    clf = Clasificador(api, con_ia=False)
    reportes = cargar_catalogo("reportes")
    for r in reportes:
        res = clf.clasificar_reporte(r)
        caso = resultados_a_casos([r], clf)[0]
        print(f"{r['id']:<7} {r['tipo']:<6} plaga={str(caso['plaga']):<18} "
              f"sem={str(caso.get('semaforo')):<8} tec={str(caso.get('tecnico_id')):<5} "
              f"pri={caso.get('prioridad')} conf={res['confianza']:.2f} inj={res['injection']}")
