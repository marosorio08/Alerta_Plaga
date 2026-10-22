# 🧠 CHECKPOINT DE SESIÓN — Equipo 7_7 (levantar contexto aquí)

> **Para iniciar sesión nueva:** lee este archivo PRIMERO. Contiene el estado al
> corte del 21-oct ~14:30, toda la infraestructura, los errores aprendidos y el
> flujo de trabajo actual. Complementa a `MEMORIA_VERIFICACION.md` (historial
> de casos dudosos) y `REPORTE_FINAL.md` (estado del hackathon).
>
> **Continuación del día 21 (corte 18:45):** `MEMORIA_SESION_21_OCT.md` — casos,
> fixes, estado, riesgos y mapa de toda la documentación.

---

## 1. Ficha rápida de acceso

| Campo | Valor |
|---|---|
| Reto | «Alerta Plaga» — junta de sanidad vegetal de Texcoco (IT Green × DIMA UACh) |
| Equipo | `equipo02` · 7_7 · Rafael (Rol A, coordina dudosos) · Emmanuel (Rol B) |
| API | `https://itg.tailf75570.ts.net` |
| Token | `EQUIPO_TOKEN` en `.env` (raíz del repo) — nunca subir |
| Servidor | `equipo02@179-236-73-82.sslip.io` · SSH puerto 2202 (`SSH_HOST/SSH_USER/SSH_PASSWORD` en `.env`) |
| Agente (server) | `supervisorctl status agente` · venv en `~/agente/.venv` |
| Dashboard | `https://equipo02.179-236-73-82.sslip.io` |
| Tabla oficial | `GET https://itg.tailf75570.ts.net/tabla.json` |
| Repo | `marosorio08/Alerta_Plaga_Gusano` (privado) · remoto `origin` · main local = main remoto |
| Cierre API | jue 22-oct 23:59 · Defensa viernes 23 |

### Cómo conectar rápido (Windows + venv local)
```powershell
.\.venv\Scripts\python.exe bot\descargar_catalogos.py --reportes   # caches frescos
# consultas SSH: escribir scripts con paramiko leyendo .env (ver ejemplos en hist.)
```

---

## 2. Posición en vivo y reglas que gobiernan los puntos

- **puntos = aciertos − errores.** Ambos equipos van 103/103 enviados (todos publicados se mandan).
- Tabla: `api.get("tabla.json")` → `equipos[].puntos`. El líder es el de mayor `puntos`.
- **El checklist que siempre hay que recordar:** aciertos por campo es_plaga · plaga ·
  semaforo · tecnico · brote (somos débiles en brote vs MISA 100%).
- Errores históricos IRRECUPERABLES (la API responde 409 "no cambia" y no los perdona):
  R-2043 (brote), R-2055 (brote), R-2070 (brote), R-2073 (brote), R-2084 (brote),
  R-2082 (tecnico), R-2015 (semaforo), R-2064 (semaforo), R-2056 (es_plaga),
  R-2097 (plaga, frijol). No repetirlos.

### Regla de oro del brote (corregida 21-oct)
- Nunca decidir brote con un solo reporte: **conjunto completo** (previos + propios).
- **Dedupe por productor por CLUSTER de 24 h**: mismo productor, misma plaga, casos
  dentro de 24 h = 1 evento (evita R-2043). Más de 24 h = eventos distintos que sí
  suman (permite R-2084 = TRUE). Implementado en `nivel2.contar_casos_cercanos`.
- Validación: `python bot/validar_brote.py` → 40/40 + R-2070 ✅ + R-2084 ✅.

---

## 3. Infraestructura actual (qué corre en el servidor)

- **Agente** (`supervisorctl status agente`): arranca con
  `desplegar agente --forzar` vía `~/despliegue.conf` (regenerado por `bot/desplegar_agente.py`):
  ```
  .venv/bin/python -u bot/listener.py --intervalo 20 --extras --avisos-reales
      --preguntas --telegram --enviar --vigilante --resolver-dudosos
  ```
- **Listener** (`bot/listener.py`): ciclo 20 s. Flujo de 3 fases (clasificar todos →
  recalcular brotes con conjunto completo → registrar). Registra automáticamente.
- **Vigilante** (`bot/vigilante.py`): hilo cada 90 s, avisa por Telegram a Rafa y
  Emmanuel sobre (1) publicados sin registrar, (2) agregables +3, (3) dudosos.
  **Nunca registra.** Anti-spam por huella + revisita mínima 30 min.
- **Resolver de dudosos** (`bot/resolver_cola.py`): hilo cada 90 s, corre en
  **MODO ANÁLISIS SOLO** (decisión de Rafa 21-oct ~13:00): re-analiza la cola
  `~/agente/cache/revision_pendiente.json` con el flujo validado, **NO registra en
  POST /casos ni envía Telegram**, conserva la cola. Bitácora: `resolver_bitacora.jsonl`.
- **Dashboard** (server puerto 3000): proxy autenticado + fallback a
  `~/app/cache/casos_propuestos.json` (casos compartidos; el listener apunta
  `CASOS_SALIDA` ahí).
- **Auto-despliegue**: push a `main` dispara despliegue; para forzar:
  `python bot/desplegar_agente.py` (local) o `desplegar agente --forzar` (SSH).

### Telegram: ¿los botones dan puntos?
**NO.** Los botones (Aprobar / Cambiar técnico / Falsa alarma) solo mandan
`POST /avisos` (columnas avisos). Los puntos solo los da `POST /casos` con los
campos correctos. Decidir "subir" un caso = enviar el payload de `/casos`.

---

## 4. El flujo de verificación de un caso DUDOSO (protocolo, siempre igual)

1. **Ubicar la cola:** `~/agente/cache/revision_pendiente.json` en el servidor.
2. **Identificar:** `reporte_id`, `motivo`, `recibido`, `texto`, `caso` propuesto.
3. **Re-clasificar con datos frescos:** `bot/descargar_catalogos.py --reportes`
   y la transcripción del server (`listener_bitacora.jsonl` trae la plaga resuelta
   por IA para voz/foto).
4. **Nivel 2** (solo con plaga conocida): `prioridad = severidad+superficie(pct)+etapa`
   · semaforo rojo≥85 naranja≥70 amarillo≥40 verde<40 · técnico = especialidad,
   carga<5 en MOMENTO=<recibido>, más cercano (haversine R=6371).
5. **Brote con CONJUNTO COMPLETO** (nunca un solo reporte), dedupe cluster 24 h.
6. **Probe SEGURO:** `POST /casos/validar` (no registra) para ver estado/agregables.
   ⚠️ **NO usar `POST /casos` como probe**: si el reporte no está registrado responde
   201 y LO REGISTRA (error cometido en R-2088/R-2089).
7. **Decisión:** ya registrado y completo → nada; registrado con agregables → +3
   solo si abre caso nuevo (no seguimientos); no registrado + confianza alta →
   enviar; ambiguo → revisar con Rafa.
8. **Regla de la sesión (21-oct):** todo dudoso se revisa con Rafa y el payload se
   aprueba ANTES de enviar. Nada de registros a ciegas.

### Lecciones clave codificadas (ver MEMORIA_VERIFICACION.md)
- Texto vago sin señales en **maíz** → `plaga=desconocida` puntúa 2/2
  (R-2042/R-2089/R-2096). En **frijol** → NO puntúa (R-2097 plaga null): revision humana.
- Seguimiento (mismo productor/parcela <24 h o "¿cuándo vienen?") → la API solo
  califica es_plaga+plaga (máx 2): R-2075/R-2088/R-2094/R-2095.
- Las respuestas `-R` NO son reportes (404 "Mensaje no encontrado"): se ignoran.
- Prompt-injection ("ignora tus instrucciones") no altera la decisión (regla 100% código).

---

## 5. Comandos útiles

```powershell
# Validaciones locales (sin gastar API)
.\.venv\Scripts\python.exe bot\validar_brote.py      # 40/40 + R-2070 + R-2084
.\.venv\Scripts\python.exe bot\validar_nivel2.py     # 40/40/40
.\.venv\Scripts\python.exe bot\probar_motor.py       # 77/77

# Datos frescos
python bot\descargar_catalogos.py --reportes

# Una pasada del listener (no registra)
python bot\listener.py --una-vez

# Vigilante (pasada o loop)
python bot\vigilante.py --una-vez --sin-telegram

# Resolver de dudosos (modo análisis, no envía)
python bot\resolver_cola.py --una-vez

# Estado en el servidor / despliegue
python bot\estado_despliegue.py
python bot\desplegar_agente.py

# SSH manual (guardar scripts temporales y borrarlos)
python -c "..."   # paramiko con .env: SSH_HOST/SSH_PORT/SSH_USER/SSH_PASSWORD
```

---

## 6. Para la próxima sesión — acciones pendientes

0. **🔴 NUEVO 21-oct 14:50 — brotes SIEMPRE requieren visto bueno.**
   - `_es_dudoso` (listener) aparca **TODO** caso con `brote=True` sin importar la
     confianza (antes solo conf<0.75): motivo "brote activo (evaluar juntos)".
   - Al aparcarlo, el listener manda `alerta_dudoso` por Telegram con botones
     ✅ Registrarlo / 🚫 Revisar.
   - El bot (`bot_telegram.py`) ahora: **Aprobar** = registra el caso en
     `POST /casos` con el payload de la cola (visto bueno real); si la API dice
     "ya registrado", no reenvía. **Revisar/Falsa** = retira de la cola sin registrar.
   - El resolver de dudosos SÍ notifica por Telegram el resumen de la cola
     (antes corría con telegram=False → por eso no llegaban alertas).
   - Regla de brote validada contra `/casos-previos` 40/40 + R-2070/R-2073/R-2084
     correctos con la regla cluster-24h actual (`bot/validar_brote.py`).
   - Herramienta: `python bot/analizar_brotes.py` imprime el patrón y la
     verificación contra la verdad oficial.

1. **Seguir monitoreando** la cola de dudosos y la tabla; avisar a Rafa al detectar
   algo (no registrar sin su OK).
2. **Bloquear el agotamiento de puntos por brotes:** revisar cada brote calculado con
   la regla cluster 24 h; si la API responde distinto, documentar como nuevo caso.
3. **No tocar el dedupe de brote ni la reconciliación sin correr la batería completa**
   (validar_brote + validar_nivel2 + probar_motor).
4. El repo: PRs 1-6 ya fusionados/cerrados. Emmanuel puede abrir PRs nuevos; revisar
   que no reviertan dedupe cluster 24 h ni la cola de dudosos.
5. Ruido conocido post-merge: la reconciliación re-envía viejos → "error 409" en logs
   (inofensivo). Si la cola se llena de históricos, limpiar con `echo '[]' > .../revision_pendiente.json`.

### 🔀 Merge selectivo del PR #8 de Emma (21-oct ~17:30)
**Origen:** `fix/brotes-revision-rafa` (PR #8) → integrado a `main` de forma selectiva.
**Qué se integró:**
- `nivel2.decidir_brote`: `n>=3 → true`, `n<=1 → false`, **`n==2 → None`** (no se
  envía `brote`; el caso se aparca y va a **revisión conjunta con Rafa**).
- **Fix R-2055** (bug real que main no cubría): un padre en `desconocida` no abre
  seguimiento y `fusionar_respuesta` hereda parcela/productor/coords de la respuesta
  → brote TRUE correcto. `validar_brote`: **40/40 + 5/5 casos reales**.
- `clasificador.evaluar_brotes` con `n` y `refs` auditables (distancia/reporte/fecha).
- Alertas Telegram con referencias y botones: **Registrar brote / Registrar sin
  brote / Marcar brote / Descartar**; escapado HTML.
- `bot_telegram`: no quita el caso de la cola hasta que el registro sea exitoso.
- Anti-inyección: si hay intento, **se descarta `pct_ia`** y decide la regla.
- `bot/evaluar_caso.py` (NUEVO): evalúa un reporte sin registrar. **Corregido por
  Rafa:** usa el mismo motor que producción (`con_ia=True`, `INTERPRETAR_IA=2`,
  consenso híbrido) con `--sin-ia` para comparar; respeta `CASOS_SALIDA`; limpia
  `_brote_dudoso` al recalcular con el conjunto completo.
- `resolver_cola`: avisa de TODA la cola (antes se callaba) con anti-spam 30 min.

**Qué NO se activó (por decisión de Rafa):**
- `PERMITIR_ENVIOS` sigue **sin definir** → el agente **no registra nada solo**
  (`ENVIOS_HABILITADOS=False`): clasifica, aparca y espera visto bueno.
- El resolver sigue en **modo ANÁLISIS** (no registra).
- Avisos/preguntas reales siguen en seco.

**Batería tras el merge:** `probar_motor` **86/86** · `validar_brote` **40/40 + 5/5**
· `validar_nivel2` **40/40/40** · `analizar_brotes` **5/5**.

### 🔍 Barrido de puntos (21-oct 14:58)
- Herramientas permanentes: `bot/escaneo_puntos.py` (barrido de complementos con
  `POST /casos/validar`, sin registrar) y `bot/analizar_complementos.py` (filtra
  seguimientos/desconocida). Revisar el archivo `cache/escaneo_resultado.json`.
- Resultado 14:58: 114/114 enviados · 0 sin registrar · 14 "complementos" sugeridos
  por la API pero TODOS son seguimientos o plaga `desconocida` → la API no califica
  `semaforo/técnico/brote` en esos (máx 2, como R-2075) → **no hay puntos ocultos
  recuperables hoy**.
- La brecha de 10 pts con MISA es **estructural**: MISA err=7 vs 10 nuestros, y
  brote 100% vs 92%. Nuestros 5 errores de brote (R-2043/R-2055/R-2070/R-2073/R-2084)
  son irrecuperables. Solo se cierra acertando los brotes/campos que queden y que
  MISA falle alguno; no tocar el dedupe ni ceder brotes sin visto bueno.

**Estado al cerrar (21-oct ~14:30):** cola vacía, resolver en modo análisis,
agente RUNNING con el último main, posición ~381/407 (2.º, ~4 pts de MISA).