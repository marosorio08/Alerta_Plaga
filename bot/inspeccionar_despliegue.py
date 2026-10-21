"""inspeccionar_despliegue.py — Cómo funciona el despliegue automático del servidor."""

import os
import sys
from pathlib import Path

import paramiko
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8")

cliente = paramiko.SSHClient()
cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cliente.connect(os.getenv("SSH_HOST"), port=int(os.getenv("SSH_PORT", 2202)),
                username=os.getenv("SSH_USER"), password=os.getenv("SSH_PASSWORD"), timeout=25)

comandos = [
    ("ubicacion del comando desplegar", "which desplegar; readlink -f $(which desplegar)"),
    ("script desplegar", "cat $(readlink -f $(which desplegar)) 2>/dev/null | head -80"),
    ("carpeta ~/agente", "ls -la ~/agente 2>/dev/null || echo 'no existe ~/agente'"),
    ("logs", "ls -la ~/logs | head; tail -12 ~/logs/*.log 2>/dev/null | head -40"),
    ("cron o timer", "crontab -l 2>/dev/null; systemctl --user list-timers --no-pager 2>/dev/null | head"),
    ("estado del despliegue", "estado 2>/dev/null | head -30 || echo 'sin comando estado'"),
]
for titulo, cmd in comandos:
    _, out, err = cliente.exec_command(cmd, timeout=40)
    print(f"\n=== {titulo} ===")
    print(out.read().decode(errors="replace").strip()[:2500])
    e = err.read().decode(errors="replace").strip()
    if e:
        print("ERR:", e[:200])

cliente.close()
