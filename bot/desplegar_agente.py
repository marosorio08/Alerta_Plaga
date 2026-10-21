"""
desplegar_agente.py — Publica el bot (listener) en el servidor del equipo.

Usa el mismo mecanismo oficial que la app:
  1. Apunta AGENTE_REPO/AGENTE_INICIAR en ~/despliegue.conf.
  2. `desplegar agente --forzar` clona, crea venv e instala requirements.
  3. Sube ~/agente/.env (secretos) y la caché de catálogos.
  4. Reinicia el servicio y muestra el log.

El agente comparte los casos con el dashboard mediante CASOS_SALIDA.
Por defecto NO registra casos en la API (el listener solo registra con --enviar).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import paramiko
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")
sys.stdout.reconfigure(encoding="utf-8")

CONF = """# Despliegue automático del equipo 7_7 — Alerta Plaga
APP_REPO="https://github.com/marosorio08/Alerta_Plaga_Gusano.git"
APP_RAMA="main"
APP_INSTALAR="npm --prefix app_web install --omit=dev"
APP_CONSTRUIR=""
APP_INICIAR="node app_web/server.js"

AGENTE_REPO="https://github.com/marosorio08/Alerta_Plaga_Gusano.git"
AGENTE_RAMA="main"
AGENTE_INSTALAR="python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt"
AGENTE_CONSTRUIR=""
AGENTE_INICIAR=".venv/bin/python -u bot/listener.py --intervalo 20 --extras --avisos-reales --preguntas --telegram --enviar --vigilante"
"""

ENV_AGENTE = f"""# Agente Alerta Plaga — generado en el despliegue (NO subir a git)
API_BASE_URL={os.getenv('API_BASE_URL')}
EQUIPO_TOKEN={os.getenv('EQUIPO_TOKEN')}
OPENROUTER_API_KEY={os.getenv('OPENROUTER_API_KEY')}
INTERPRETAR_IA={os.getenv('INTERPRETAR_IA', '2')}
SUPABASE_URL={os.getenv('SUPABASE_URL', '')}
SUPABASE_SERVICE_ROLE_KEY={os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')}
TELEGRAM_BOT_TOKEN={os.getenv('TELEGRAM_BOT_TOKEN', '')}
TELEGRAM_CHAT_ID={os.getenv('TELEGRAM_CHAT_ID', '')}
TELEGRAM_CHATS_EXTRA={os.getenv('TELEGRAM_CHATS_EXTRA', '')}
# el agente escribe los casos donde los lee el dashboard
CASOS_SALIDA=/home/equipo02/app/cache/casos_propuestos.json
"""

ARCHIVOS = ["plagas.json", "parcelas.json", "productores.json", "tecnicos.json",
            "reportes.json", "multimedia.json", "cache_casos_previos.json"]

cliente = paramiko.SSHClient()
cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cliente.connect(os.getenv("SSH_HOST"), port=int(os.getenv("SSH_PORT", 2202)),
                username=os.getenv("SSH_USER"), password=os.getenv("SSH_PASSWORD"), timeout=25)
sftp = cliente.open_sftp()


def correr(comando: str, titulo: str = "", timeout: int = 900) -> str:
    if titulo:
        print(f"\n--- {titulo} ---")
    _, salida, error = cliente.exec_command(comando, timeout=timeout)
    texto = salida.read().decode(errors="replace")
    err = error.read().decode(errors="replace")
    if texto.strip():
        print(texto.strip()[:2200])
    if err.strip():
        print("stderr:", err.strip()[:500])
    return texto


# 1) configuración con el agente apuntando al repo
with sftp.open("/home/equipo02/despliegue.conf", "w") as fh:
    fh.write(CONF)
print("despliegue.conf actualizado (app + agente)")

# 2) desplegar el agente (clona, venv, dependencias)
correr("desplegar agente --forzar 2>&1", "Desplegando agente", 1200)

# 3) .env y caché del agente
correr("mkdir -p ~/agente/cache", "Preparando ~/agente")
with sftp.open("/home/equipo02/agente/.env", "w") as fh:
    fh.write(ENV_AGENTE)
correr("chmod 600 ~/agente/.env && echo '.env del agente listo'")

print("\n--- Subiendo caché del agente ---")
for nombre in ARCHIVOS:
    origen = RAIZ / "cache" / nombre
    if origen.exists():
        sftp.put(str(origen), f"/home/equipo02/agente/cache/{nombre}")
        print(f"  {nombre} ({origen.stat().st_size // 1024} KB)")

# 4) reiniciar y ver
correr("supervisorctl restart agente; sleep 6; supervisorctl status agente; echo; "
       "tail -20 ~/logs/agente.log", "Estado del agente")
correr("ls -la ~/app/cache/casos_propuestos.json; "
       "curl -s -o /dev/null -w 'dashboard:%{http_code}\\n' http://localhost:3000/api/resumen",
       "Caché compartida y dashboard")

sftp.close()
cliente.close()
print("\nDespliegue del agente terminado.")
