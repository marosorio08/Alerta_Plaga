"""inspeccionar_agente.py — Qué ejecuta el programa 'agente' de supervisor."""

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
    ("cmdline del proceso agente", "tr '\\0' ' ' < /proc/28/cmdline 2>/dev/null || echo 'sin acceso'"),
    ("detalle del proceso", "ps -o pid,ppid,user,args -p 28 2>/dev/null || echo 'sin acceso'"),
    ("carpeta ~/agente", "ls -la ~/agente 2>&1 | head -8"),
    ("log del agente", "tail -6 ~/logs/agente.log 2>/dev/null"),
    ("config de supervisor visible", "cat /etc/supervisor/supervisord.conf 2>/dev/null | tail -20"),
    ("sockets de supervisor", "ls -la /var/run/supervisor* /tmp/supervisor* 2>/dev/null"),
]
for titulo, cmd in comandos:
    _, out, err = cliente.exec_command(cmd, timeout=30)
    print(f"\n=== {titulo} ===")
    print(out.read().decode(errors="replace").strip()[:700])
    e = err.read().decode(errors="replace").strip()
    if e:
        print("ERR:", e[:200])

cliente.close()
