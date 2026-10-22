"""registrar_generico.py — Registra un payload JSON y limpia su fila de la cola.

Uso:
    python bot/registrar_generico.py '{"reporte_id":"R-2126", ...}'
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))
from api_cliente import ApiCliente  # noqa: E402


def limpiar_cola(rid: str) -> None:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(os.getenv("SSH_HOST"), port=int(os.getenv("SSH_PORT", "2202")),
                username=os.getenv("SSH_USER"), password=os.getenv("SSH_PASSWORD"), timeout=25)

    def run(c):
        _i, o, e = cli.exec_command(c)
        return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")

    PEND = "/home/equipo02/agente/cache/revision_pendiente.json"
    out = run(f"cat {PEND}")
    cola = json.loads(out) if out.strip() else []
    restante = [p for p in cola if p.get("reporte_id") != rid]
    if len(restante) != len(cola):
        sftp = cli.open_sftp()
        with sftp.file("/home/equipo02/agente/_cola_tmp.json", "w") as f:
            f.write(json.dumps(restante, ensure_ascii=False))
        sftp.close()
        run(f"mv /home/equipo02/agente/_cola_tmp.json {PEND}")
        time.sleep(1)
        out2 = run(f"cat {PEND}")
        cola2 = json.loads(out2) if out2.strip() else []
        print(f"cola: quitado {rid} -> quedan {[p.get('reporte_id') for p in cola2]}")
    cli.close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(sys.argv[1])
    api = ApiCliente()
    print("payload:", json.dumps(payload, ensure_ascii=False))
    st = api.validar_caso(payload)
    print("validar:", json.dumps(st, ensure_ascii=False)[:200])
    if bool(st.get("ya_registrado_antes")):
        print(">> ya registrado; no se reenvía")
    else:
        resp = api.registrar_caso(payload)
        print("respuesta:", json.dumps(resp, ensure_ascii=False)[:400])
    limpiar_cola(str(payload.get("reporte_id")))

    tabla = api.get("tabla.json")
    eqs = {e["equipo_id"]: e for e in tabla.get("equipos", [])}
    eq, misa = eqs.get("equipo02") or {}, eqs.get("equipo07") or {}
    print(f">> 7_7={eq.get('puntos')}/{eq.get('maximo_posible')} "
          f"({eq.get('enviados')}/{eq.get('publicados')}) err={eq.get('errores_total')} "
          f"| MISA={misa.get('puntos')} err={misa.get('errores_total')} "
          f"| dif={misa.get('puntos') - eq.get('puntos')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())