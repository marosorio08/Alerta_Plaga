# 🧠 MEMORIA DE VERIFICACIÓN — Equipo 7_7 (Actualización 21-oct 09:30)

> **Propósito de este archivo:** memoria del historial y **guía operativa** para verificar
> los casos dudosos. El próximo agente/sesión debe leerlo ANTES de tocar cualquier cosa
> relacionada con brotes, dudosos o el vigilante. Complementa a `REPORTE_FINAL.md`
> (estado del hackathon) y `docs/NIVEL2.md` (reglas del nivel 2).

---

## 1. Ficha rápida

| Campo | Valor |
|---|---|
| Reto | «Alerta Plaga» — junta de sanidad vegetal de Texcoco (IT Green × DIMA UACh) |
| Equipo | `equipo02` · **7_7** · Rafael (Rol A) · Emmanuel (Rol B) |
| API | `https://itg.tailf75570.ts.net` · Token `EQUIPO_TOKEN` en `.env` |
| Servidor | `equipo02@179-236-73-82.sslip.io` (SSH puerto 2202) — agente bajo supervisor |
| Dashboard | https://equipo02.179-236-73-82.sslip.io |
| Tabla oficial | `GET https://itg.tailf75570.ts.net/tabla.json` |
| Cierre API | jue 22-oct 23:59 · Defensa viernes 23 |

### Posición en vivo (corte 10:07)
| # | Equipo | Pts/máx | % | Enviados | Brote | Preguntas | Avisos |
|---|---|---|---|---|---|---|---|
| 1 | MISA | 322/341 | 94.4 | 86/86 | 100 | 4 | 138 |
| **2** | **7_7** | **316/341** | **92.7** | **86/86** | 92 | **13** | 133 |
| 3 | string | 290/341 | 85.0 | 84/86 | 87 | 7 | 49 |

**Resumen:** 2.º lugar, **6 pts** de diferencia con MISA. **86/86 publicados → enviados (al día).**
Aciertos por campo: es_plaga 99 · plaga 100 · semaforo 97 · tecnico 98 · **brote 92**.
Errores (9): 7 históricos + R-2082 técnico + R-2084 brote (ambos fijados por la API, irrecuperables).

---

## 2. Los 4 bugs corregidos (lecciones → código)

| # | Fallo real | Causa raíz | Fix (commit) |
|---|---|---|---|
| 1 | R-2043 brote ❌ | **Falso positivo**: el mismo productor (PR-191) reportó 3 veces en horas (R-2032/35/43) y sus propios casos disparaban brote | **Dedupe por productor** (`43e5495`): los casos propios del mismo productor cuentan una vez por brote; los previos NUNCA se deduplican |
| 2 | R-2056 es_plaga ❌ | **La IA sola** dijo "no plaga" en un texto de roya; las reglas acertaban | **Consenso Híbrido** (`d1a2202`): reglas+IA; si difieren → histórico; sin histórico → **mandan las REGLAS** |
| 3 | R-2070/R-2073 brote ❌ | **Falso negativo (bug de orden)**: el listener calculaba brote con `resultados_a_casos([reporte])` — UN SOLO reporte — y `_recalcular_brotes` corría DESPUÉS del registro | **3 fases** (`8e486d5`): 1-clasificar todos → 2-recalcular brotes con el **conjunto COMPLETO** (previos + todos los casos propios) → 3-validar y registrar. **El brote NUNCA se decide con un solo reporte.** |
| 4 | R-2071 sem/tec/brote +0 | Caso registrado solo con es_plaga+plaga; la API decía "todavía le pueden agregar: brote, semaforo, tecnico_id" | **Complemento** (`0744595`): reenviar POST /casos con los campos faltantes SUMA los puntos (+3 en R-2071 → 5/5) |

**Validación:** `probar_motor.py` 77/77 · `validar_brote.py` 40/40 + casos reales R-2043/R-2070 · `validar_nivel2.py` 40/40/40.

---

## 3. CÓMO VERIFICAR UN CASO DUDOSO (protocolo paso a paso)

> Este es el flujo que debemos seguir SIEMPRE que el vigilante avise de un dudoso.
> **NUNCA registrar a ciegas**: primero verificar, luego (si da puntos y es seguro) registrar.

### Paso 0 — Dónde está la cola de dudosos
- En el servidor: `~/agente/cache/revision_pendiente.json`
- Bajarlo a local con las herramientas de sesión (SFTP por SSH) y leerlo.
- El **vigilante** (`bot/vigilante.py`) avisa por Telegram (Rafa **y** Emmanuel) cada ~90 s cuando hay novedades. NUNCA registra nada solo.

### Paso 1 — Identificar el reporte y su motivo
Leer del pendiente: `reporte_id`, `motivo` (plaga desconocida / confianza baja / brote con confianza media), `recibido`, `texto` y el `caso` propuesto.

### Paso 2 — Re-clasificar con datos frescos
```
python bot/descargar_catalogos.py --reportes     # actualiza cache/ con los reportes al día
```
- Si es texto: revisar la señal determinista (ej. "chahuixtle" en frijol → roya_frijol).
- Si es voz/foto: usar la bitácora del servidor (`listener_bitacora_servidor.jsonl`) que ya tiene la plaga resuelta por IA (consenso STT/visión).
- Cruzar con la parcela/cultivo real del reporte.

### Paso 3 — Calcular el Nivel 2 (solo si hay plaga conocida)
```
prioridad = severidad + superficie(pct) + etapa   # 0..100
semaforo  = rojo≥85 · naranja≥70 · amarillo≥40 · verde<40
tecnico   = especialidad + carga<5 en MOMENTO=<recibido> + más cercano (haversine R=6371)
```
- **El pct**: mirar la sensibilidad (un semáforo que no cambia ante 10-75 % es "blindado").

### Paso 4 — Calcular el BROTE con el CONJUNTO COMPLETO ⚠️
- **NUNCA** con un solo reporte (regresión R-2070).
- Contar: previos + todos los casos propios, misma plaga, **<5 km**, ventana **168 h**, con dedupe por productor.
- Si el resultado difiere del que tenía el pendiente, anotarlo.

### Paso 5 — Consultar el estado real en la API (probe SEGURO)
- `POST /casos` con el payload → si responde **409**, ya está registrado y devuelve `puntos` + `detalle` por campo (acertar/fallar). **No puntúa dos veces.**
- Si responde **201** → se registró en ese momento (usar solo cuando ya decidimos enviar).

### Paso 6 — Decisión
| Resultado | Acción |
|---|---|
| Ya está registrado y completo (5/5 o 2/2 seguimiento) | ✅ Nada que hacer; avisar "resuelto" |
| Ya registrado con "todavía le pueden agregar: ..." | 💰 **Complemento** → enviar los campos calculados (potencial +3) |
| No registrado y campos con confianza alta | ✅ Enviar el payload completo |
| No registrado, plaga desconocida o brote ambiguo | ⚠️ Avanzarlo con Rafa/Emmanuel, no enviar a ciegas |

### Paso 7 — Limpiar la cola
El vigilante marca como `ok` los dudosos que ya se registraron (no los vuelve a avisar).

---

## 4. Casos dudosos resueltos (ejemplos de referencia)

| Reporte | Motivo | Verificación | Resultado |
|---|---|---|---|
| **R-2071** (mosquita blanca) | sin semaforo/tecnico/brote al registrar | respuesta del productor aportó parcela P-092 + "la mitad" (50 %). Semaforo amarillo (invariante al pct 10-75), técnico T-03 (carga 2, entomología, más cercano), brote false (1 caso <5 km) | **Complemento +3 → 5/5** ✅ |
| **R-2075** (seguimiento tizón) | plaga desconocida en cola | es seguimiento → la API solo califica es_plaga+plaga (máx 2); el probe registró 2/2 | **2/2** ✅ (seguimiento). **Re-verificado 21-oct 09:30:** el 409 dice "todavía le pueden agregar brote/semaforo/tecnico", PERO al enviar el complemento la API responde "Este mensaje no abre un caso nuevo: el semáforo, el técnico y el brote no se califican" (máx 2). El complemento fue inofensivo (0 pts, sin pérdida). |
| **R-2079** (roya del frijol) | "brote con confianza media" | "chahuixtle" en frijol → roya; **6 casos de roya <5 km en 168 h** → brote TRUE; semaforo amarillo, técnico T-09 | **5/5 automático** ✅ (el fix del conjunto completo lo salvó) |
| R-2043, R-2070, R-2073 | errores históricos de brote | ver sección 2 | irrecuperables, no repetir |

**Las respuestas `-R` (sufijo) NO son reportes**: la API responde 404 "Mensaje no encontrado". Ignorarlas (no dan puntos ni restan).

---

## 5. Infraestructura actual (qué corre en el servidor)

- **Agente** (`supervisorctl status agente`): `.venv/bin/python -u bot/listener.py --intervalo 20 --extras --avisos-reales --preguntas --telegram --enviar --vigilante`
  - Registra reportes nuevos automáticamente (en 3 fases, brote con conjunto completo).
  - Aparca dudosos en `~/agente/cache/revision_pendiente.json`.
  - Avisa por Telegram al coordinador (Rafa `1472274235`) **y a Emmanuel (`1483221634`)** vía `TELEGRAM_CHATS_EXTRA`.
- **Vigilante** (`bot/vigilante.py`): corre como hilo, cada 90 s revisa la API y avisa si hay (1) publicados sin registrar, (2) agregables que suman +3, (3) dudosos. **Nunca registra.** Anti-spam: huella de mensaje + revisita mínima 30 min.
- **Dashboard** (puerto 3000): proxy autenticado + fallback a cache compartida `~/app/cache/casos_propuestos.json`.
- **Auto-despliegue**: los pushes a `main` se despliegan solos; el comando de arranque vive en `~/despliegue.conf` (se regenera con `python bot/desplegar_agente.py`).

### Telegram: ¿los botones dan puntos?
**NO.** Los botones (✅ Aprobar / 🔁 Cambiar técnico / 🚫 Falsa alarma) solo mandan `POST /avisos`
(columnas "avisos"/retos extra). Los puntos reales solo los da `POST /casos` con los campos
correctos. Decidir "subir" un caso dudoso = enviar el payload de `/casos`, no el botón.

---

## 6. Comandos útiles

```powershell
# Validar el motor (sin gastar API)
python bot/probar_motor.py                 # 77 pruebas
python bot/validar_brote.py                # 40/40 + casos reales R-2043/R-2070
python bot/validar_nivel2.py               # 40/40/40 prioridad/semáforo/técnico

# Datos frescos
python bot/descargar_catalogos.py --reportes

# Una pasada del listener (no registra)
python bot/listener.py --una-vez

# Vigilante (loop o una pasada)
python bot/vigilante.py --una-vez --sin-telegram
python bot/vigilante.py                    # loop (avisa por Telegram)

# Complemento/registro puntual (la API responde 409 con detalle o 201)
python bot/enviar_casos.py --solo R-XXXX   # dry-run
python bot/enviar_casos.py --solo R-XXXX --enviar

# Despliegue del agente (regenera despliegue.conf y reinicia)
python bot/desplegar_agente.py

# Estado en el servidor
python bot/estado_despliegue.py
```

---

## 7. Notas para el próximo agente

0. **⚠️ REGLA DE ORO DE LA SESIÓN (21-oct 10:30): NUNCA registrar a ciegas en dudosos.** Para cualquier caso en `revision_pendiente.json` o aviso del vigilante: usar **SOLO `POST /casos/validar`** (devuelve estado/agregables **sin registrar nunca**) y **presentar el payload propuesto a Rafa en el chat antes de cualquier `POST /casos` real**. El `POST /casos` en un reporte NO registrado responde **201 y registra en ese momento** (error cometido en R-2088/R-2089: se registraron durante un "probe" — ambos salieron bien, pero la regla es mostrar primero). Excepción: el listener automático sigue enviando lo que ya valida solo (flujo de 3 fases + brote con conjunto completo).

1. **Todo OK al corte 09:26** (292/314, 2.º, 3 pts de diferencia). La cola de dudosos está VACÍA (se limpió en el servidor el 21-oct 09:26: R-2075 y R-2079 estaban residuales ya marcados `ok`).
2. El flujo de verificación de la sección 3 es el que se usó para resolver R-2071/R-2075/R-2079 sin fallar.
3. **Regla de oro del brote**: SIEMPRE conjunto completo (previos + propios, dedupe por productor). Un caso con "brote" en la cola y muchos casos cercanos de la misma plaga normalmente es un brote real: verificar, no descartar.
4. **⚠️ NUEVO 21-oct 09:30 — El mensaje "todavía le pueden agregar..." del 409 NO es garantía de +3 en seguimientos.** En R-2075 la API anunció que faltaban brote/semaforo/tecnico, pero al enviar el complemento respondió "no abre un caso nuevo: no se califican" (máx 2, puntos 0). **El complemento solo suma si el reporte ABRE un caso nuevo** (R-2071 = caso nuevo → +3). Regla práctica: complementar solo cuando el reporte NO es seguimiento (usa la llama 409 → si el 409 de `validar_caso` o el POST devuelve esa frase, complementar es inofensivo pero no suma).
5. El repo: `marosorio08/Alerta_Plaga_Gusano` (privado). PRs 1-5 fusionados. La rama de Emmanuel (Caso_Emmanuel) quedó 33 commits atrás de main: necesita `git pull origin main` antes de cualquier PR nuevo (ya avisado por Telegram).
6. **⚠️ NUEVO 21-oct 09:45 — PR #6 de Emmanuel cerrado sin merge.** Proponía: refresco de `/casos-previos`+`/visitas`, respuestas con id original + complemento, reconciliación y persistencia; PERO también (a) quitaba el dedupe por productor del brote (reviviría el riesgo del falso positivo R-2043: verificado, el cambio no le afectaba a R-2070 ni a los 40 previos, pero quedaba sin red de seguridad si falla `visitas` o la detección de seguimiento) y (b) eliminaba el parkeo de dudosos y registraba `desconocida` a ciegas (contra el protocolo §3 Paso 6). Se le pidió reabrir con solo las mejoras de infraestructura (manteniendo dedupe=True y la cola de dudosos). No fusionar hasta que él valide brote sin dedupe contra 40/R-2043/R-2070.
7. **✅ NUEVO 21-oct 09:52 — aviso del vigilante verificado y cerrado.** El aviso era por `R-2080-R` y `R-2081-R` ("No, nomás era eso, gracias.") marcados "plaga desconocida". Resultado: **son respuestas `-R` a consultas administrativas** (R-2080 = "¿curso de injertos?", R-2081 = "¿teléfono oficina Texcoco?"), ya registradas 1/1 como NO plaga. Al probe, ambas respuestas devuelven **404 "Mensaje no encontrado"** → no son reportes (caso de la nota de la §4), no puntúan ni restan. Se vació `revision_pendiente.json` y se marcaron `ok` en `vigilante_estado`. Sin cambios de posición (292/314).
8. **⚠️ NUEVO 21-oct 09:55 — últimos 4 reportes (corte 09:42-09:55): 306 pts, 84/84, errores 9.** | **R-2080** y **R-2081**: 1/1 cada uno ✅ (no plaga). | **R-2083** (foto maíz P-186, gusano_cogollero): **5/5** ✅. | **R-2082** (gallina ciega, PR-273=P-239): arrancó 2/2; **SE COMPLEMENTÓ** (abría caso nuevo, máx 5): `brote=false ✅` + `semaforo=amarillo ✅` (subió a 4 pts), pero el `tecnico_id` que se envió **T-08 ❌** era INCORRECTO y la API **congeló el campo** ("Ya tiene todos los campos, no cambia"). El correcto era **T-06** (12.73 km vs 16.47 de T-08 al momento 09:39:29) → **+1 de tecnico perdido y 1 error contabilizado** (err 7→8). **Lección: en caso NUEVO el complemento puntúa/erra en vivo (no como R-2075 que era seguimiento); calcular técnico con el momento y parcela del reporte ANTES de enviar, nunca con el valor de la respuesta `-R`.** | **R-2084** (voz papa P-263, tizon_tardio): el listener lo registró con `brote=false`, pero **la API esperaba TRUE** (`brote: false` en detalle = campo errado; err 8→9). Causa raíz: R-2084 tiene a R-2014 (mismo productor PR-291, misma parcela, hace 2 días) + R-2007 (PR-283) → la API los cuenta como 3 casos legítimos (no son seguimientos), pero el **dedupe por productor** de nuestro motor los colapsaba a 2 → brote false. El punto quedó fijado e irrecuperable. **Lección: el dedupe por productor solo debe aplicar a seguimientos de horas (caso R-2043), NO a reportes de brote separados por días.**
9. **✅ NUEVO 21-oct 09:55 — escaneo de complementos (75 reportes con plaga) → 1 recuperable.** Barrido con probe a todos los enviados: **R-2016** (roya_frijol, P-088) tenía `brote` pendiente → complemento `brote=true` **+1 ✅** (ahora 4/5). R-2056 único otro candidato pero queda en `es_plaga:false` con -1 y brote=false en nuestro cómputo → **no vale el riesgo** (ya registrado con error, probe no cambia). Resto de reportes: 5/5 o seguimientos (2/2). **Posición tras todo: 306/331 (92.4%), 2.º, 6 pts de diferencia con MISA (312).**
10. **🔥 NUEVO 21-oct 10:00 — FIX DE BROTE (commit `01f39f4`): dedupe por CLUSTER 24 h.** Diagnóstico de todos los errores de brote: R-2043 (falso positivo: mismo productor en horas) ordenó el dedupe por productor; pero ese dedupe GLOBAL causó el nuevo falso negativo R-2084 (mismo productor, misma parcela, 2 días después + R-2007 = 3 casos legítimos que la API exige TRUE). **Nueva regla en `nivel2.contar_casos_cercanos`**: los casos propios del mismo productor cuentan **1 si caen dentro de 24 h** y **por separado si hay >24 h** entre eventos (misma ventana que la detección de seguimientos). Validación: 40/40 previos + R-2070=True + R-2084=True + motor 77/77 + nivel2 40/40/40. `validar_brote.py` incluye ahora R-2084 como caso canónico. **No tocar este dedupe sin volver a correr la batería.**
11. **✅ NUEVO 21-oct 10:25 — R-2088 y R-2089 (textos vagos).** **R-2088** (voz, PR-190, *"¿Ya se está pasando a las matas? ¿Cuándo vienen?"*): seguimiento de R-2079 (roya_frijol, 1h09 antes) → **2/2** (máx 2, nivel2 no se califica; la API respondió 201 con `maximo:2`). **R-2089** (texto, PR-174, P-103 maíz R3 Atenco, *"Algo le está pasando a mi siembra, se ve fea."*): sin señales → **2/2** (es_plaga+plaga correctos, plaga="desconocida" puntúa; la API respondió 201 con `maximo:2`, "no abre un caso nuevo"). Precedente que lo confirma: R-2042 (*"Se me está echando a perder la milpa."*) = 2/2. **Lección: un texto vago SIN señales de plaga identificable puntúa 2/2 enviando `es_plaga=true, plaga=desconocida` — mandar `desconocida` NO resta; no mandar el caso sí pierde los 2 puntos.** Cola limpiada (ambos `ok`).
12. **🔀 NUEVO 21-oct 10:24 — el PR #6 de Emmanuel SÍ se fusionó al main** (commit de merge `eb877cf`, hecho por el dueño del repo, encima del histórico). Efectos verificados con batería: **NO rompió nada** — `validar_brote` 40/40 + R-2070 ✅ + R-2084 ✅, `validar_nivel2` 40/40/40, `probar_motor` 77/77. Conservó: dedupe cluster 24 h, parkeo de dudosos (`_es_dudoso`/`_parkear_dudoso`), consenso híbrido. Sumó: respuestas con id original (`_fusionar_respuesta`), refresco de `/casos-previos`+`/visitas`, reconciliación idempotente `_reconciliar`. **⚠️ Efecto colateral operativo:** la reconciliación reprocesa reportes VIEJOS ya registrados → ruido en el log (`error registrando R-20xx: 409`) y repone la cola de pendientes con reportes históricos. No pierde puntos (409 no puntúa doble) pero ensucia; limpiar la cola de viejos con `echo '[]'` + marcarlos `ok` en vigilante_estado cuando aparezcan.
13. **✅ NUEVO 21-oct 10:30 — R-2090 (voz, PR-289, P-260 haba, *"manchas cafés como de chocolate... tres cuartas partes"*): 5/5 PERFECTO** (mancha_chocolate ✅ semáforo amarillo ✅ T-12 ✅ brote false ✅), registrado automáticamente por el listener post-merge. Tabla 10:30: **7_7 = 333/355 (93.8%) = MISA (333/355), EMPATE en cabeza** — 90/90 enviados, err 9 (los 2 extra irrecuperables R-2082 técnico + R-2084 brote). Los reportes brote se están acertando tras el fix (R-2084 era el último falso negativo).
14. **✅ NUEVO 21-oct 10:55 — monitoreo al día: 343/365 (94.0%), EMPATE con MISA (343/365), 92/92 enviados.** Últimos casos verificado: **R-2091** (voz, PR-230, P-183 jitomate, mosquita_blanca, amarillo T-11, brote false) → **5/5** ✅ y **R-2092** (texto, PR-258, P-218 maíz, gusano_cogollero, amarillo T-11, brote false) → **5/5** ✅, ambos registrados automáticamente por el listener (bitácora las muestra con entrada/respuesta/plaga correctos). Cola de pendientes VACÍA. Ruido persistente post-merge: reconciliación re-envía viejos → "error 409" en log (inofensivo, la API no puntúa doble) y a veces repone la cola con históricos; limpiar con `echo '[]' > ~/agente/cache/revision_pendiente.json` + marcar `ok` cuando aparezcan.
15. **✅ NUEVO 21-oct 11:45 — R-2096 (voz, PR-136, P-049 maíz R3 Texcoco, *"Se me está echando a perder mi maicito."*): 2/2** (es_plaga ✅ + plaga ✅, maxio 2, "no abre caso nuevo"). Enviado tras aprobación de Rafa con payload `{es_plaga:true, plaga:desconocida}` — precedente gemelo R-2042 (*"Se me está echando a perder la milpa"*) = 2/2. Cola limpiada y marcado ok.
16. **⚠️ NUEVO 21-oct 12:00 — R-2097 (frijol): −1 punto perdido → FIX aplicado.** Texto vago *"Algo le está pasando a mi siembra, se ve fea."* (PR-195, P-133 frijol). El listener **lo auto-registró a ciegas via la reconciliación del PR #6** con `plaga=desconocida` → la API dio **1 pt (`plaga: null`)**; en maíz el mismo texto (R-2089) sí puntúa `desconocida` (2/2). **Causa raíz: `_reconciliar` NO pasaba por `_es_dudoso`/`_parkear_dudoso`.** **Fix `0ab3233`:** la reconciliación ahora respeta la cola de dudosos (igual que FASE 3) — textos vagos/desconocida se aparcan para revisión en vez de auto-enviarse. Validado 40/40 + motor 77/77 + nivel2 40/40/40, desplegado 11:57. **Lección: un texto vago en FRIJOL no puntúa `desconocida` (en maíz sí) — revisar antes; y la reconciliación jamás debe saltarse el filtro de dudosos.** Posición 11:50: **361/387 vs MISA 362 (1 pt abajo)** — la diferencia son los 2 errores fijos de la mañana (R-2082 técnico, R-2084 brote) + R-2097.
17. **🔧 NUEVO 21-oct 12:01 — Fix colateral del fix:** al hacer que la reconciliación aparque dudosos, **empezó a re-aparcar TODOS los reportes viejos** (R-2001..R-2090, "confianza baja 0.00") porque al reprocesarlos sin confianza los veía como dudosos aunque **ya estaban registrados**. **Fix `c1f324c`:** la reconciliación ahora **consulta `validar_caso` a la API primero**; si `ya_registrado_antes` → lo marca enviado y no toca nada (sin aparcar ni reenviar). Solo aparca lo que NO está registrado y es dudoso. Cola verificada vacía tras un ciclo. Importa la batería: 40/40 + 77/77.
18. **🚀 NUEVO 21-oct 12:55 — RESOLVER AUTOMÁTICO DE DUDOSOS (`bot/resolver_cola.py`, commit `8a914e6`).** El listener ahora corre con `--resolver-dudosos`: cada 90 s procesa `revision_pendiente.json` con el **flujo validado caso a caso** (contexto → precedentes → reanálisis → decisión → registro). Reglas codificadas: (a) **maíz** texto vago → `desconocida` puntúa 2/2 (R-2042/R-2089/R-2096); (b) **frijol** texto vago → NO auto-enviar (R-2097 plaga null, requiere humano); (c) seguimiento (mismo productor/parcela <24 h o texto "¿cuándo vienen?") → es_plaga+plaga máx 2; (d) plaga con señales → nivel2 completo + brote con conjunto completo (cluster 24 h) → 5/5. **Solo registra cuando hay decisión segura con precedente**; lo ambiguo se queda en la cola. Al resolver avisa a **Telegram**: qué se hizo, qué se estimó, resultado API, puntos de 7_7 y del líder actual. Probado en seco contra los casos reales (5/5 decisiones correctas). Validado 40/40 + motor 77/77.