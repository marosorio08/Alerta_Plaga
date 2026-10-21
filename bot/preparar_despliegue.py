"""preparar_despliegue.py — Revisa el servidor antes de desplegar (solo lectura)."""

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
    ("despliegue.conf", "cat ~/despliegue.conf"),
    ("quien escucha el 3000", "ss -ltnp 2>/dev/null | grep ':3000' || netstat -ltnp 2>/dev/null | grep ':3000'"),
    ("arbol de procesos node", "ps -eo pid,ppid,cmd | grep -E '[n]ode|[p]npm' | head -12"),
    ("servicios systemd de usuario", "systemctl --user list-units --type=service --no-pager 2>/dev/null | head -15"),
    ("versiones", "node -v; npm -v; python3 --version; which pm2 || echo 'sin pm2'"),
    ("espacio y memoria", "df -h ~ | tail -1; free -m | head -2"),
    ("puerto libre 3100", "ss -ltn 2>/dev/null | grep -c ':3100' || true"),
]
for titulo, cmd in comandos:
    _, out, err = cliente.exec_command(cmd, timeout=40)
    print(f"\n=== {titulo} ===")
    print(out.read().decode(errors="replace").strip()[:1200])
    e = err.read().decode(errors="replace").strip()
    if e:
        print("ERR:", e[:200])

cliente.close()
