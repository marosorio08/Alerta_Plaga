"""
desplegar_dashboard.py — Publica el dashboard en el servidor del equipo.

Usa el mecanismo oficial del servidor (despliegue.conf + desplegar + supervisor),
en vez de levantar procesos a mano:

  1. Respalda ~/despliegue.conf.
  2. Apunta APP_REPO a nuestro repositorio (rama main).
  3. Deja ~/app/app_web/.env con PORT y EQUIPO_TOKEN (sin secretos en git).
  4. Sube la caché de catálogos y casos propuestos (para el dashboard).
  5. Ejecuta `desplegar app --forzar` y muestra el resultado.
  6. Verifica localhost:3000 y la URL pública.

Uso:
    python bot/desplegar_dashboard.py
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

HOST = os.getenv("SSH_HOST")
PUERTO = int(os.getenv("SSH_PORT", 2202))
USUARIO = os.getenv("SSH_USER")
CLAVE = os.getenv("SSH_PASSWORD")
TOKEN = os.getenv("EQUIPO_TOKEN")
API = os.getenv("API_BASE_URL", "https://itg.tailf75570.ts.net")
REPO = "https://github.com/marosorio08/Alerta_Plaga_Gusano.git"

CONF = f"""# Despliegue automático del equipo 7_7 — Alerta Plaga
# Revisa GitHub cada 30 s; si hay commits nuevos, instala y reinicia.
# Comandos: estado · desplegar · bitacora app · bitacora despliegue

# ── Aplicación web (se publica en $URL_APP; debe escuchar en 0.0.0.0:3000) ──
APP_REPO="{REPO}"
APP_RAMA="main"
APP_INSTALAR="npm --prefix app_web install --omit=dev"
APP_CONSTRUIR=""
APP_INICIAR="node app_web/server.js"

# ── Agente de Telegram (se configura en la siguiente etapa) ──
AGENTE_REPO=""
AGENTE_RAMA="main"
AGENTE_INSTALAR="python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt"
AGENTE_CONSTRUIR=""
AGENTE_INICIAR=".venv/bin/python bot/listener.py"

# Las llaves van en el .env de cada carpeta (~/app/app_web/.env y ~/agente/.env),
# nunca en el repositorio.
"""

ENV_APP = f"""# Dashboard Alerta Plaga — generado en el despliegue
PORT=3000
HOST=0.0.0.0
EQUIPO_TOKEN={TOKEN}
API_BASE={API}
CACHE_DIR=/home/equipo02/app/cache
"""

ARCHIVOS_CACHE = ["plagas.json", "parcelas.json", "productores.json", "tecnicos.json",
                  "reportes.json", "casos_propuestos.json"]


def ejecutar(cliente, comando: str, titulo: str = "", timeout: int = 300) -> str:
    if titulo:
        print(f"\n--- {titulo} ---")
    _, salida, error = cliente.exec_command(comando, timeout=timeout)
    texto = salida.read().decode(errors="replace")
    err = error.read().decode(errors="replace")
    if texto.strip():
        print(texto.strip()[:2500])
    if err.strip():
        print("stderr:", err.strip()[:800])
    return texto + err


def main() -> None:
    if not all([HOST, USUARIO, CLAVE, TOKEN]):
        sys.exit("Faltan SSH_HOST, SSH_USER, SSH_PASSWORD o EQUIPO_TOKEN en .env")

    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cliente.connect(HOST, port=PUERTO, username=USUARIO, password=CLAVE, timeout=25)
    sftp = cliente.open_sftp()

    # 1) respaldo de la configuración anterior
    ejecutar(cliente, "cp -n ~/despliegue.conf ~/despliegue.conf.bak && echo 'respaldo en ~/despliegue.conf.bak'",
             "Respaldo de despliegue.conf")

    # 2) .env de la app (antes del despliegue, para que sobreviva al reset --hard)
    ejecutar(cliente, "mkdir -p ~/app/app_web ~/app/cache", "Preparando carpetas")
    with sftp.open("/home/equipo02/app/app_web/.env", "w") as fh:
        fh.write(ENV_APP)
    ejecutar(cliente, "chmod 600 ~/app/app_web/.env && echo '.env escrito'", "Variables de entorno")

    # 3) caché de catálogos y casos
    print("\n--- Subiendo caché ---")
    for nombre in ARCHIVOS_CACHE:
        origen = RAIZ / "cache" / nombre
        if origen.exists():
            sftp.put(str(origen), f"/home/equipo02/app/cache/{nombre}")
            print(f"  {nombre} ({origen.stat().st_size // 1024} KB)")
        else:
            print(f"  {nombre}: no existe localmente, se omite")

    # 4) nueva configuración de despliegue
    with sftp.open("/home/equipo02/despliegue.conf", "w") as fh:
        fh.write(CONF)
    ejecutar(cliente, "cat ~/despliegue.conf", "despliegue.conf actualizado")

    # 5) desplegar
    ejecutar(cliente, "desplegar app --forzar 2>&1", "Desplegando (git + npm + supervisor)", timeout=900)

    # 6) verificar
    time.sleep(3)
    ejecutar(cliente, "supervisorctl status app; echo; tail -20 ~/logs/app.log", "Estado del servicio")
    ejecutar(cliente, "curl -s -o /dev/null -w 'local:%{http_code}\\n' http://localhost:3000/; "
                      "curl -s -o /dev/null -w 'resumen:%{http_code}\\n' http://localhost:3000/api/resumen; "
                      "curl -s -o /dev/null -w 'publica:%{http_code}\\n' https://equipo02.179-236-73-82.sslip.io/",
             "Verificación HTTP")
    ejecutar(cliente, "curl -s http://localhost:3000/api/resumen | head -c 420", "Muestra de /api/resumen")

    sftp.close()
    cliente.close()
    print("\nDespliegue terminado.")


if __name__ == "__main__":
    main()
