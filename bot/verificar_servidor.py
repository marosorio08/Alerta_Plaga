"""verificar_servidor.py — Estado final de app y agente tras el despliegue."""

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
    ("supervisor", "supervisorctl status"),
    ("ultimas lineas del agente", "tail -6 ~/logs/agente.log"),
    ("ultimas lineas de la app", "tail -4 ~/logs/app.log"),
    ("estado de la cache compartida", "ls -la ~/app/cache/casos_propuestos.json; "
                                      "python3 -c \"import json;d=json.load(open('/home/equipo02/app/cache/casos_propuestos.json'));"
                                      "print('casos:',len(d));print('con semaforo:',sum(1 for x in d if x.get('semaforo')));"
                                      "print('muestra:',d[1] if len(d)>1 else d[0])\""),
    ("procesos", "ps -eo pid,etime,cmd | grep -E '[l]istener|[s]erver.js'"),
]
for titulo, cmd in comandos:
    _, out, err = cliente.exec_command(cmd, timeout=60)
    print(f"\n=== {titulo} ===")
    print(out.read().decode(errors="replace").strip()[:1200])
    e = err.read().decode(errors="replace").strip()
    if e:
        print("ERR:", e[:300])

cliente.close()
