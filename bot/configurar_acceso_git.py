"""
configurar_acceso_git.py — Da al servidor acceso de lectura al repositorio.

Estrategia (de más a menos segura):
  1. Deploy key SSH (solo lectura, revocable, sin caducidad ligada a una persona).
  2. Si no hay permisos de administración en el repo, cae a credential store
     con un token de GitHub guardado en ~/.git-credentials (chmod 600).

Ningún secreto entra al repositorio: todo queda en el servidor, fuera de git.

Uso:
    python bot/configurar_acceso_git.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import paramiko
import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")
sys.stdout.reconfigure(encoding="utf-8")

HOST = os.getenv("SSH_HOST")
PUERTO = int(os.getenv("SSH_PORT", 2202))
USUARIO = os.getenv("SSH_USER")
CLAVE = os.getenv("SSH_PASSWORD")
REPO = "marosorio08/Alerta_Plaga_Gusano"
KEY_PATH = "/home/equipo02/.ssh/deploy_alerta"


def token_github() -> str | None:
    """Recupera el token que ya usa Git en Windows (no se imprime)."""
    try:
        salida = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return None
    for linea in salida.splitlines():
        if linea.startswith("password="):
            return linea.split("=", 1)[1]
    return None


def correr(cliente, comando: str, titulo: str = "") -> str:
    if titulo:
        print(f"\n--- {titulo} ---")
    _, out, err = cliente.exec_command(comando, timeout=120)
    texto = out.read().decode(errors="replace")
    e = err.read().decode(errors="replace")
    if texto.strip():
        print(texto.strip()[:1200])
    if e.strip():
        print("stderr:", e.strip()[:400])
    return texto


def main() -> None:
    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cliente.connect(HOST, port=PUERTO, username=USUARIO, password=CLAVE, timeout=25)

    # 1) llave SSH en el servidor
    correr(cliente, f"test -f {KEY_PATH} || ssh-keygen -t ed25519 -N '' -C 'deploy-alerta-plaga' -f {KEY_PATH}",
           "Generando deploy key")
    publica = correr(cliente, f"cat {KEY_PATH}.pub").strip()
    print("  llave:", publica[:60] + "...")

    # 2) alta de la deploy key en GitHub
    token = token_github()
    agregada = False
    if token and publica:
        resp = requests.post(
            f"https://api.github.com/repos/{REPO}/keys",
            headers={"Authorization": f"token {token}", "User-Agent": "alerta-plaga",
                     "Accept": "application/vnd.github+json"},
            json={"title": "servidor equipo02 (solo lectura)", "key": publica, "read_only": True},
            timeout=30,
        )
        if resp.status_code in (201, 422):  # 422 = ya existe
            print(f"  deploy key registrada en GitHub ({resp.status_code})")
            agregada = True
        else:
            print(f"  no se pudo registrar la deploy key: {resp.status_code} {resp.text[:200]}")

    # 3) configuración de git en el servidor
    correr(cliente, "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                    "ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null; "
                    "sort -u ~/.ssh/known_hosts -o ~/.ssh/known_hosts; echo known_hosts listo",
           "known_hosts")
    correr(cliente, "ssh -o BatchMode=yes -i " + KEY_PATH + " -T git@github.com 2>&1 | head -2",
           "Prueba SSH contra GitHub")

    if agregada:
        correr(cliente, 'git config --global url."git@github.com:".insteadOf "https://github.com/" && '
                        'git config --global --get-regexp "url\\..*insteadof"',
               "git usará SSH para GitHub")

    # 4) respaldo: credential store con token (si la deploy key no bastara)
    if token and not agregada:
        with cliente.open_sftp() as sftp:
            with sftp.open("/home/equipo02/.git-credentials", "w") as fh:
                fh.write(f"https://x-access-token:{token}@github.com\n")
        correr(cliente, "chmod 600 ~/.git-credentials && git config --global credential.helper store && "
                        "echo 'credential store configurado'", "Respaldo con credential store")

    # 5) probar el fetch
    correr(cliente, "cd ~/app && git remote set-url origin https://github.com/marosorio08/Alerta_Plaga_Gusano.git && "
                    "git fetch origin main 2>&1 | tail -3", "Prueba de fetch")

    cliente.close()


if __name__ == "__main__":
    main()
