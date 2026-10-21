"""
revisar_servidor.py — Inventario del servidor asignado (sin exponer secretos).

Lee las credenciales de .env (SSH_HOST, SSH_PORT, SSH_USER, SSH_PASSWORD) y
muestra qué hay corriendo: app desplegada, procesos y variables definidas
(solo nombres, nunca valores).

Uso:
    python bot/revisar_servidor.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

COMANDOS = [
    ("contenido de ~/app", "ls -la ~/app 2>/dev/null | head -20"),
    ("variables definidas en ~/app/.env (solo nombres)", r"grep -oE '^[A-Za-z_]+=' ~/app/.env 2>/dev/null"),
    ("package.json del servidor", "cat ~/app/package.json 2>/dev/null"),
    ("procesos node", "ps -eo pid,etime,cmd | grep '[n]ode' | head"),
    ("pm2", "pm2 list 2>/dev/null || echo 'pm2 no instalado'"),
    ("puerto 3000 local", "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000"),
    ("app pública", "curl -s -o /dev/null -w '%{http_code}' https://equipo02.179-236-73-82.sslip.io"),
    ("git del servidor", "git -C ~/app remote -v 2>/dev/null; git -C ~/app log --oneline -2 2>/dev/null"),
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    host = os.getenv("SSH_HOST")
    puerto = int(os.getenv("SSH_PORT") or 22)
    usuario = os.getenv("SSH_USER")
    clave = os.getenv("SSH_PASSWORD")
    if not (host and usuario and clave):
        sys.exit("Faltan SSH_HOST, SSH_USER o SSH_PASSWORD en .env")

    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cliente.connect(host, port=puerto, username=usuario, password=clave, timeout=25)

    for titulo, comando in COMANDOS:
        _, salida, error = cliente.exec_command(comando, timeout=40)
        print(f"\n=== {titulo} ===")
        print(salida.read().decode(errors="replace").strip()[:900])
        e = error.read().decode(errors="replace").strip()
        if e:
            print("ERR:", e[:200])

    cliente.close()


if __name__ == "__main__":
    main()
