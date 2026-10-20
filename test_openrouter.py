import os
import sys
from dotenv import load_dotenv
from openai import OpenAI

# Asegurar codificación UTF-8 en consola de Windows
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# Cargar variables del entorno desde .env
load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")

if not api_key:
    raise ValueError("Error: No se encontró OPENROUTER_API_KEY en el archivo .env")

# Configurar el cliente para OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key,
)

# Modelo por defecto (DeepSeek 4.1 Flash)
MODELO_DEEPSEEK = "deepseek/deepseek-v4.1-flash"

def consultar_deepseek(prompt: str, modelo: str = MODELO_DEEPSEEK) -> str:
    """Envía un mensaje al modelo DeepSeek a través de OpenRouter."""
    response = client.chat.completions.create(
        model=modelo,
        messages=[
            {"role": "system", "content": "Eres un asistente de IA para el proyecto IT Green."},
            {"role": "user", "content": prompt}
        ],
    )
    return response.choices[0].message.content

def main():
    print(f"Conectando con DeepSeek ({MODELO_DEEPSEEK}) a través de OpenRouter...")
    try:
        respuesta = consultar_deepseek("Hola DeepSeek, confirma tu funcionamiento para el proyecto IT Green.")
        print("\n--- Respuesta de DeepSeek ---")
        print(respuesta)
        print("-----------------------------")
        print("¡Conexión exitosa con DeepSeek 4.1!")
    except Exception as e:
        print(f"\nOcurrió un error al conectar: {e}")

if __name__ == "__main__":
    main()
