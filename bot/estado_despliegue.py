"""estado_despliegue.py — Resumen del despliegue en el servidor (sin secretos)."""

import os
import sys

import paramiko
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(".env")

cliente = paramiko.SSHClient()
cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cliente.connect(os.getenv("SSH_HOST"), port=int(os.getenv("SSH_PORT", 2202)),
                username=os.getenv("SSH_USER"), password=os.getenv("SSH_PASSWORD"), timeout=25)

comandos = [
    ("despliegue.conf (sin secretos)", r"grep -vE 'TOKEN|KEY|PASSWORD' ~/despliegue.conf"),
    ("variables app_web (solo nombres)", r"grep -oE '^[A-Za-z_]+=' ~/app/app_web/.env"),
    ("variables agente (solo nombres)", r"grep -oE '^[A-Za-z_]+=' ~/agente/.env"),
    ("programa app", r"sed -n '/program:app/,/^\[/p' /etc/supervisor/supervisord.conf"),
    ("programa agente", r"sed -n '/program:agente/,/^\[/p' /etc/supervisor/supervisord.conf"),
    ("carpetas", "ls -d ~/app ~/agente ~/app/cache ~/app/app_web"),
    ("git app", "git -C ~/app log --oneline -1; git -C ~/agente log --oneline -1"),
]

for titulo, comando in comandos:
    _, out, err = cliente.exec_command(comando, timeout=40)
    print(f"\n=== {titulo} ===")
    print(out.read().decode(errors="replace").strip()[:1400])
    e = err.read().decode(errors="replace").strip()
    if e:
        print("ERR:", e[:200])

cliente.close()
