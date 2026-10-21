"""inspeccionar_supervisor.py — Configuración de supervisor para app y agente."""

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
    ("supervisorctl status", "supervisorctl status"),
    ("configs de supervisor", "ls -la /etc/supervisor/conf.d/ 2>/dev/null; ls -la ~/.config/supervisor 2>/dev/null"),
    ("config app", "cat /etc/supervisor/conf.d/*app*.conf 2>/dev/null || sudo -n cat /etc/supervisor/conf.d/*app*.conf 2>/dev/null || echo 'sin permiso de lectura'"),
    ("config agente", "cat /etc/supervisor/conf.d/*agente*.conf 2>/dev/null || echo 'sin permiso'"),
    ("ENV_FILE de server.js", "grep -n 'ENV_FILE\\|loadEnvFile\\|CACHE_DIR' ~/app/server.js"),
    ("supervisorctl disponible", "which supervisorctl; supervisorctl --version 2>&1 | head -2"),
]
for titulo, cmd in comandos:
    _, out, err = cliente.exec_command(cmd, timeout=40)
    print(f"\n=== {titulo} ===")
    print(out.read().decode(errors="replace").strip()[:1500])
    e = err.read().decode(errors="replace").strip()
    if e:
        print("ERR:", e[:300])

cliente.close()
