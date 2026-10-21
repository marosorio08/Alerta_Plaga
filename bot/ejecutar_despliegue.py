"""ejecutar_despliegue.py — Fuerza el despliegue y verifica el resultado."""

import os
import sys
import time
from pathlib import Path

import paramiko
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")

VERIFICAR = (
    "curl -s -o /dev/null -w 'local:%{http_code}\\n' http://localhost:3000/ ; "
    "curl -s -o /dev/null -w 'resumen:%{http_code}\\n' http://localhost:3000/api/resumen ; "
    "curl -s -o /dev/null -w 'publica:%{http_code}\\n' https://equipo02.179-236-73-82.sslip.io/ ; "
    "echo ; curl -s http://localhost:3000/api/resumen | head -c 500"
)

cliente = paramiko.SSHClient()
cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cliente.connect(os.getenv("SSH_HOST"), port=int(os.getenv("SSH_PORT", 2202)),
                username=os.getenv("SSH_USER"), password=os.getenv("SSH_PASSWORD"), timeout=25)


def correr(comando: str, titulo: str = "", timeout: int = 900) -> str:
    if titulo:
        print(f"\n--- {titulo} ---")
    _, salida, error = cliente.exec_command(comando, timeout=timeout)
    texto = salida.read().decode(errors="replace")
    err = error.read().decode(errors="replace")
    if texto.strip():
        print(texto.strip()[:2500])
    if err.strip():
        print("stderr:", err.strip()[:600])
    return texto


correr("desplegar app --forzar 2>&1", "Desplegando", 900)
time.sleep(5)
correr("supervisorctl status app; echo; tail -14 ~/logs/app.log", "Estado del servicio")
correr(VERIFICAR, "Verificación HTTP")
cliente.close()
