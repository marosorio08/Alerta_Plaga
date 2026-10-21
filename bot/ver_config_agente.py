"""ver_config_agente.py — Sección [program:agente] de supervisor."""

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

for comando in [
    "sed -n '/program:agente/,/^\\[/p' /etc/supervisor/supervisord.conf",
    "sed -n '/program:app/,/^\\[/p' /etc/supervisor/supervisord.conf",
    "ls -la /usr/local/bin/",
]:
    _, out, err = cliente.exec_command(comando, timeout=30)
    print("\n===", comando[:50], "===")
    print(out.read().decode(errors="replace").strip()[:900])
    e = err.read().decode(errors="replace").strip()
    if e:
        print("ERR:", e[:200])

cliente.close()
