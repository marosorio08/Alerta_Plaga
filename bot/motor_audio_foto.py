"""
motor_audio_foto.py — Reto extra multimodal (fotos .jpg y notas de voz .ogg).

Descarga el archivo de GET /media/{archivo} y lo procesa con OpenRouter:
  - voz (.ogg)  -> transcripción con STT (openai/whisper-large-v3).
  - foto (.jpg) -> análisis visual con modelo de visión vía chat completions.

Salida normalizada (para alimentar a clasificador.clasificar_reporte):
    {"texto": "...", "descripcion_visual": "...", "plaga_sugerida": "id|None",
     "es_plaga_sugerida": True|False|None, "fuente": "whisper|vision|local"}

Requiere OPENROUTER_API_KEY válida en .env. Sin ella, degrada a fallback local.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
MEDIA_CACHE = RAIZ / "cache" / "media"

API_BASE = (os.getenv("API_BASE_URL") or "https://itg.tailf75570.ts.net").rstrip("/")
API_KEY = os.getenv("OPENROUTER_API_KEY", "")

MODELO_STT = os.getenv("OPENROUTER_STT_MODEL", "openai/whisper-large-v3")
MODELO_VISION = os.getenv("OPENROUTER_VISION_MODEL", "openai/gpt-4o-mini")

# Prompts centralizados (se pueden afinar sin tocar código)
PROMPT_VISION = """Eres un fitopatólogo/entomólogo agrónomo mexicano. Te muestran la foto
de un cultivo de __CULTIVO__ (__ETAPA__). Usa el catálogo oficial de plagas para decidir.
Catálogo (id, síntomas visibles):
- gusano_cogollero: larvas en cogollo, hojas perforadas/raspadas, excremento como aserrín (maíz)
- roya_frijol: pústulas café rojizo en el envés, polvo color óxido (frijol)
- tizon_tardio: manchas café oscuro borde amarillo, moho blanco, follaje quemado (papa, jitomate)
- pulgon: colonias de insectos verdes/negros, mielecilla, hojas enrolladas
- gallina_ciega: plantas marchitas que se arrancan sin raíz, larvas blancas en C en el suelo
- mosquita_blanca: insectos blancos, huevecillos/ninfas en el envés, hojas amarillas pegajosas
- chapulin: chapulines visibles, hojas comidas del borde, plantas defoliadas
- mancha_chocolate: manchas redondas café rojizo en hojas (haba)
- hlb: moteado amarillo asimétrico, frutos deformes (solo limón)
- gorgojo_khapra: larvas peludas cafés, pellejos, granos huecos, polvo (grano almacenado)

Responde SOLO con JSON sin markdown:
{"es_plaga": true, "plaga": "id_catalogo_o_desconocida", "confianza": 0.8,
 "sintomas": "descripcion breve de lo que ves"}
IMPORTANTE: en un cultivo de __CULTIVO__ las UNICAS plagas posibles son: __CANDIDATAS__.
Si nada encaja con esas opciones usa "desconocida". Si la imagen no muestra cultivo
ni dano de plaga, responde es_plaga=false."""


def prompt_vision(cultivo: str, etapa: str, candidatas: list[str] | None = None) -> str:
    """Sustituye los marcadores sin usar str.format (el JSON de ejemplo lo rompería)."""
    lista = ", ".join(candidatas) if candidatas else "cualquiera del catalogo"
    return (
        PROMPT_VISION.replace("__CULTIVO__", cultivo or "cultivo")
        .replace("__ETAPA__", etapa or "etapa desconocida")
        .replace("__CANDIDATAS__", lista)
    )


def descargar_media(archivo_url: str) -> Path:
    """Descarga /media/{archivo} a cache/media y devuelve la ruta local."""
    nombre = archivo_url.rsplit("/", 1)[-1]
    MEDIA_CACHE.mkdir(parents=True, exist_ok=True)
    destino = MEDIA_CACHE / nombre
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    url = archivo_url if archivo_url.startswith("http") else f"{API_BASE}{archivo_url}"
    resp = requests.get(url, timeout=40)
    resp.raise_for_status()
    destino.write_bytes(resp.content)
    return destino


def transcribir_audio(archivo: Path | None, idioma: str = "es") -> str:
    """Transcribe un .ogg con la API STT de OpenRouter (multipart)."""
    if not archivo or not archivo.exists():
        return ""
    url = "https://openrouter.ai/api/v1/audio/transcriptions"
    with open(archivo, "rb") as fh:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"file": (archivo.name, fh, "audio/ogg")},
            data={"model": MODELO_STT, "language": idioma},
            timeout=120,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"STT falló {resp.status_code}: {resp.text[:200]}")
    datos = resp.json()
    return (datos.get("text") or datos.get("transcript")) or ""


def describir_foto(archivo: Path | None, cultivo: str = "cultivo", etapa: str = "",
                   candidatas: list[str] | None = None) -> dict:
    """Envía la foto a un modelo de visión (chat completions) y devuelve la decisión."""
    if not archivo or not archivo.exists():
        return {"es_plaga": None, "plaga": None, "confianza": 0.0, "sintomas": ""}
    b64 = base64.b64encode(archivo.read_bytes()).decode("utf-8")
    mime = "image/jpeg"
    mensaje = {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt_vision(cultivo, etapa, candidatas)},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            },
        ],
    }
    url = "https://openrouter.ai/api/v1/chat/completions"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/marosorio08/Alerta_Plaga_Gusano",
            "X-Title": "Alerta Plaga - equipo 7_7",
        },
        json={"model": MODELO_VISION, "messages": [mensaje]},
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Visión falló {resp.status_code}: {resp.text[:200]}")
    contenido = resp.json()["choices"][0]["message"]["content"]
    return _parsear_json_modelo(contenido)


def _parsear_json_modelo(texto: str) -> dict:
    """Extrae el JSON de una respuesta del modelo (aunque venga con markdown)."""
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio != -1 and fin > inicio:
        try:
            return json.loads(texto[inicio : fin + 1])
        except json.JSONDecodeError:
            pass
    return {"es_plaga": None, "plaga": None, "confianza": 0.0, "sintomas": texto[:200]}


def procesar_reporte_multimedia(reporte: dict, cultivo: str, etapa: str,
                                candidatas: list[str] | None = None) -> dict:
    """Orquesta voz/foto para un reporte. Devuelve datos para el clasificador."""
    audio_url = reporte.get("audio_url")
    foto_url = reporte.get("foto_url")
    resultado: dict = {
        "texto": "",
        "fuente": "ninguna",
        "es_plaga_sugerida": None,
        "plaga_sugerida": None,
        "confianza": 0.0,
    }

    if not API_KEY:
        return resultado  # sin key: el clasificador usará su fallback conservador

    try:
        if audio_url and reporte.get("tipo") == "voz":
            archivo = descargar_media(audio_url)
            texto = transcribir_audio(archivo)
            resultado["texto"] = texto
            resultado["fuente"] = "whisper"
        elif foto_url and reporte.get("tipo") == "foto":
            archivo = descargar_media(foto_url)
            vision = describir_foto(archivo, cultivo, etapa, candidatas)
            resultado.update(
                {
                    "fuente": "vision",
                    "es_plaga_sugerida": vision.get("es_plaga"),
                    "plaga_sugerida": vision.get("plaga"),
                    "confianza": float(vision.get("confianza", 0.0)),
                    "sintomas": vision.get("sintomas", ""),
                }
            )
    except Exception as exc:  # no rompe el pipeline
        resultado["error"] = str(exc)
    return resultado


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    # uso: python bot/motor_audio_foto.py R-2003
    rid = sys.argv[1] if len(sys.argv) > 1 else "R-2003"
    from clasificador import Clasificador

    clf = Clasificador()
    reportes = json.loads((RAIZ / "cache" / "reportes.json").read_text(encoding="utf-8"))
    rep = next((r for r in reportes if r["id"] == rid), None)
    if not rep:
        sys.exit(f"Reporte {rid} no encontrado")
    cultivo = clf.cultivo_de_parcela(rep.get("parcela_id")) or ""
    etapa = clf.parcelas.get(rep.get("parcela_id"), {}).get("etapa", "") or ""
    res = procesar_reporte_multimedia(rep, cultivo, etapa)
    print(json.dumps(res, ensure_ascii=False, indent=2))