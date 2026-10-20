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

# ---- mensajes que NO son de plaga (pre-filtro) ----
SINONIMOS_NO_PLAGA = [
    "saludar", "saludo", "hola", "buenas noches", "buenos días",
    "plática", "platica", "fertilización", "fertilizacion", "curso",
    "junta", "ejidatarios", "ejido", "horario", "hora abren", "abren la",
    "oficina", "trámite", "tramite", "precio", "precios", "vender", "comprar",
    "préstamo", "prestamo", "crédito", "credito", "inscripción", "inscripcion",
    "sábado", "sabado", "mañana abren", "amanecer", "feliz día", "gracias", "saludos",
]

# ---- sinonimias locales -> id plaga (del catálogo GET /plagas) ----
PLAGA_POR_SINONIMO: dict[str, str] = {}
_PLAGA_ALIASES = {
    "gusano_cogollero": [
        "cogollero", "cogollo", "gusano del cogollo", "gusano soldado",
        "gusano verde", "gusanos verdes", "gusanito", "aguijón", "perfor", "agujer",
    ],
    "roya_frijol": [
        "chahuixtle", "roya", "polvillo", "polvo color óxido", "polvito",
        "puntitos cafés", "puntitos cafés", "herrumbre", "oxido",
    ],
    "tizon_tardio": [
        "tizón", "tizon", "quema", "quemazón", "hielo", "podrido", "huele a podrido",
        "manchas cafés", "manchas café", "mancha negra", "papa negra", "chahuixtle de la papa",
    ],
    "pulgon": [
        "pulgón", "pulgon", "piojillo", "piojo", "animalitos verdes",
        "animalitos", "bichitos", "tapizada", "mielecilla", "fumagina",
    ],
    "gallina_ciega": [
        "gallina ciega", "nixticuil", "gusano blanco", "raíces comidas", "raices comidas",
        "salir sin raíz", "sin raiz", "arrancan fácil", "marchita aunque hay humedad",
        "larvas blancas", "plantas acamadas",
    ],
    "mosquita_blanca": [
        "mosquita", "mosquilla", "palomilla blanca", "mosquitas", "amarillas y pegajosas",
        "hojas pegajosas", "amarillas y",
    ],
    "chapulin": [
        "chapulín", "chapulin", "chapulines", "langosta", "saltamontes", "brincan",
        "matas peladas", "defoliada", "chapulinada",
    ],
    "mancha_chocolate": [
        "mancha de chocolate", "chocolate", "manchita café", "manchas café rojizo",
    ],
    "hlb": [
        "dragón amarillo", "dragon amarillo", "enverdecimiento", "moteado amarillo",
        "psílidos", "psilidos", "amarillamiento", "limón amarillo",
    ],
    "gorgojo_khapra": [
        "gorgojo khapra", "peludo del grano", "gusanito peludo", "grano almacenado",
        "pellejos", "mudas", "granos huecos", "costales",
    ],
}
for _id, alis in _PLAGA_ALIASES.items():
    for _a in alis:
        PLAGA_POR_SINONIMO[_a] = _id


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
        """Reglas por sinonimias + cruce de cultivo. Sin IA."""
        t = self.normalizar(texto)
        if not t:
            return {"es_plaga": False, "plaga": None, "confianza": 0.0, "motor": "vacio",
                    "razon": "sin texto"}

        # 1) mensajes sin contenido de plaga (pre-filtro)
        if any(no in t for no in SINONIMOS_NO_PLAGA):
            # contra-evidencia: si también menciona una plaga, manda la plaga
            plaga = self._plaga_por_sinonimos(t)
            if plaga:
                return self._resultado_plaga(plaga, cultivo, "texto", t)
            return {"es_plaga": False, "plaga": None, "confianza": 0.95, "motor": "prefiltro",
                    "razon": "mensaje no agrícola"}

        # 2) búsqueda de plaga por sinonimias del catálogo
        plaga = self._plaga_por_sinonimos(t)
        if plaga:
            return self._resultado_plaga(plaga, cultivo, "texto", t)

        # 3) si no hay señal clara -> desconocida (nunca resta)
        return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.3, "motor": "texto_desconocida",
                "razon": "describe problema sin plaga identificable"}

    def _plaga_por_sinonimos(self, t: str) -> str | None:
        for sinonimo, plaga_id in PLAGA_POR_SINONIMO.items():
            if sinonimo in t:
                return plaga_id
        return None

    def _resultado_plaga(self, plaga_id: str, cultivo: str | None, motor: str, texto_norm: str) -> dict:
        """Cruza la plaga detectada con el cultivo de la parcela (descarte)."""
        plaga = next((p for p in self.plagas if p["id"] == plaga_id), None)
        if plaga is None:
            return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.2, "motor": motor,
                    "razon": "plaga inválida"}

        cultivos_validos = set(plaga.get("cultivos", []))
        if cultivo and cultivos_validos and cultivo not in cultivos_validos:
            # La plaga detectada no corresponde al cultivo de la parcela:
            # por seguridad "desconocida" no resta; o intentamos otra.
            # Intentamos re-buscar otra plaga compatible con ese cultivo.
            alt = self._plaga_en_cultivo(texto_norm, cultivo)
            if alt:
                return {"es_plaga": True, "plaga": alt, "confianza": 0.6, "motor": motor,
                        "razon": f"sinónimo en parcela de {cultivo}"}
            return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.2, "motor": motor,
                    "razon": f"sinónimo fuera de cultivo {cultivo}"}

        confianza = 0.9 if cultivo and cultivo in cultivos_validos else 0.75
        return {"es_plaga": True, "plaga": plaga_id, "confianza": confianza, "motor": motor,
                "razon": f"sinónimo en parcela de {cultivo or 'desconocido'}"}

    def _plaga_en_cultivo(self, texto_norm: str, cultivo: str) -> str | None:
        """Busca cualquier sinonimia compatible con el cultivo."""
        candidatas = [p for p in self.plagas if cultivo in set(p.get("cultivos", []))]
        for p in candidatas:
            for sinonimo, plaga_id in PLAGA_POR_SINONIMO.items():
                if plaga_id == p["id"] and sinonimo in texto_norm:
                    return plaga_id
        return None

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
            # voz y fotos sin caption: motor multimodal (whisper/visión) si hay key
            resultado = self._motor_multimedia(tipo, texto, audio, foto, cultivo, etapa)

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

    def _motor_multimedia(self, tipo, texto, audio, foto, cultivo, etapa="") -> dict:
        """Intenta transcripción/visión con OpenRouter; degrada conservadoramente."""
        # Reglas de cultivo exclusivo (deterministas, alta señal):
        # limón -> solo hlb ; grano almacenado -> solo gorgojo_khapra
        cultivo_exclusivo = {"limón": "hlb", "grano almacenado": "gorgojo_khapra"}
        if cultivo in cultivo_exclusivo and (foto or audio):
            return {"es_plaga": True, "plaga": cultivo_exclusivo[cultivo],
                    "confianza": 0.6, "motor": "cultivo_exclusivo",
                    "razon": f"parcela de {cultivo}, único candidato {cultivo_exclusivo[cultivo]}"}
        # Pre-filtro: fotos/audios que acompañan a un texto no-agrícola
        if texto and not self._plaga_por_sinonimos(self.normalizar(texto)):
            if any(no in self.normalizar(texto) for no in SINONIMOS_NO_PLAGA):
                return {"es_plaga": False, "plaga": None, "confianza": 0.8, "motor": "multimedia_prefiltro",
                        "razon": "medio con mensaje no agrícola"}
        if self.con_ia:
            try:
                from motor_audio_foto import procesar_reporte_multimedia

                res = procesar_reporte_multimedia(
                    {"tipo": tipo, "audio_url": audio, "foto_url": foto}, cultivo or "", etapa or ""
                )
                fuente = res.get("fuente")
                if fuente == "whisper" and res.get("texto"):
                    return self.clasificar_texto(res["texto"], cultivo) | {
                        "motor": "whisper+texto", "razon": "transcripción de voz"
                    }
                if fuente == "vision" and res.get("es_plaga_sugerida") is not None:
                    es = bool(res["es_plaga_sugerida"])
                    p = res.get("plaga_sugerida") if es else None
                    return {
                        "es_plaga": es,
                        "plaga": p or ("desconocida" if es else None),
                        "confianza": res.get("confianza", 0.5),
                        "motor": "vision",
                        "razon": f"visión: {res.get('sintomas', '')[:100]}",
                    }
            except Exception as exc:  # pragma: no cover - degrada
                return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.4,
                        "motor": f"{tipo}_fallo_ia", "razon": f"IA falló: {exc}"}
        # Fallback conservador: reporte con foto/audio -> plausible plaga desconocida
        return {"es_plaga": True, "plaga": "desconocida", "confianza": 0.5, "motor": f"{tipo}_desconocido",
                "razon": "medio sin clasificar, plaga desconocida"}


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
