# 🔎 Análisis de los 14 casos nuevos — 22-oct-2026 (tarde)

> Corte: 22-oct-2026, ~13:30 (centro). App abierta en
> `https://equipo02.179-236-73-82.sslip.io`.
> **Nada registrado**: los 14 siguen pendientes (`POST /casos/validar` = “Formato
> correcto. No se registró nada.”). Este documento espera el visto bueno de Rafa.

## 1. Estado en vivo al corte

| # | Equipo | Pts/máx | Env/pub | Err |
|---|---|---|---|---|
| 1 | xD | 579/662 | 167/167 | 15 |
| **2** | **7_7** | **576/662** | **158/167** | **14** |
| 3 | Los Artilleros | 567/662 | 165/167 | 15 |
| 4 | MISA | 557/662 | 158/167 | 15 |

**9 pendientes** (R-2156, R-2158, R-2159, R-2160, R-2161, R-2162, R-2163,
R-2164, R-2167) = hasta +41 pts. Estamos a **3 pts de xD**.

## 2. Método

1. Se abrió la app/dashboard y se leyeron sus 167 clasificaciones propuestas
   (`/api/casos`).
2. Los 14 reportes se pasaron por el **motor real** (`evaluar_caso`, mismo motor
   que el listener: consenso híbrido Reglas+IA, STT y visión).
3. Verificación independiente: transcripciones, fotos, respuestas `-R`,
   seguimientos (<24 h), nivel 2 con **carga de técnicos al momento del reporte**
   (`GET /tecnicos?momento=`) y brote con el **conjunto completo** (propios +
   `casos-previos`, radio 5 km, 168 h, dedupe cluster 24 h).
4. Probe seguro `POST /casos/validar` para los 14 payloads.

## 3. Comparativo App vs verificación

| Reporte | Tipo | Cultivo | App (plaga/pct/sem/téc/brote) | Verificación (plaga/pct/sem/téc/brote) | Veredicto |
|---|---|---|---|---|---|
| R-2154 | texto | — | pulgón/10/verde/T-03/false **← alucinó** | **NO plaga** | ✅ Seguro |
| R-2155 | texto | maíz | no plaga | **NO plaga** | ✅ Seguro |
| R-2156 | voz | maíz | desconocida | cogollero/100/naranja/T-06/false (n=1) | ⚠️ Dudoso audio |
| R-2157 | texto | haba | pulgón/**10**/verde/T-08/false | pulgón/**100**/amarillo/T-08/false (n=1) | ✅ Seguro (corregir pct) |
| R-2158 | foto | haba | desconocida | mancha_chocolate/100/naranja/T-07/**n=2** | 🟡 Brote dudoso |
| R-2159 | texto | avena | pulgón/30/verde/T-03/**true** | pulgón/30/verde/T-03/**true (n=9)** | 🦠 Brote confirmado |
| R-2160 | voz | haba | mancha_chocolate/10/amarillo/T-07/**dudoso** | mancha_chocolate/10/amarillo/T-07/**n=2** | 🟡 Brote dudoso |
| R-2161 | texto | maíz | gallina_ciega/30/amarillo/T-06/**true** | gallina_ciega/30/amarillo/T-06/**true (n=3)** | 🦠 Brote confirmado |
| R-2162 | texto | papa | tizón/25/naranja/T-09/**true** | tizón/25/naranja/T-09/**true (n=3)** | 🦠 Brote confirmado |
| R-2163 | voz | haba | desconocida | chapulín/50/amarillo/T-08/**true (n=6)** | 🦠 Brote confirmado |
| R-2164 | voz | frijol | desconocida | chapulín/100/amarillo/T-06/**true (n=4)** | 🦠 Brote confirmado |
| R-2165 | voz | maíz | desconocida | chapulín/75/naranja/T-10/false (n=1) | ✅ Seguro |
| R-2166 | foto | papa (P-054) | desconocida (seg. R-2162) | tizón — **seguimiento de R-2162** | ✅ Seguro 2/2 |
| R-2167 | foto | frijol | desconocida | chapulín/75/amarillo/T-11/**n=2** | 🟡 Brote dudoso |

## 4. Seguros para enviar (5)

| Reporte | Payload propuesto | Por qué |
|---|---|---|
| R-2154 | `{"reporte_id":"R-2154","es_plaga":false}` | Trámite de padrón; `-R`: “No, nomás era eso”. La app inventó pulgón. |
| R-2155 | `{"reporte_id":"R-2155","es_plaga":false}` | Consulta de apoyo de semilla. |
| R-2157 | `{"reporte_id":"R-2157","es_plaga":true,"plaga":"pulgon","semaforo":"amarillo","tecnico_id":"T-08","brote":false}` | Mielecilla + bichitos en haba. “Todas las plantas” = **100 %** (la app dejó 10 %). |
| R-2165 | `{"reporte_id":"R-2165","es_plaga":true,"plaga":"chapulin","semaforo":"naranja","tecnico_id":"T-10","brote":false}` | Audio claro; aislado, n=1. |
| R-2166 | `{"reporte_id":"R-2166","es_plaga":true,"plaga":"tizon_tardio"}` | Seguimiento de R-2162 (foto confirma tizón). Solo califican es_plaga+plaga. |

## 5. Brotes confirmados — requieren tu visto bueno (5)

| Reporte | Payload (brote) | Evidencia |
|---|---|---|
| R-2159 | `…"plaga":"pulgon","semaforo":"verde","tecnico_id":"T-03","brote":true` | **n=9**: 9 casos de pulgón <5 km en 168 h (R-2114, R-2145, R-2098, R-2086, R-2012, R-2078, R-2099, R-2148 + previo R-1042). |
| R-2161 | `…"plaga":"gallina_ciega","semaforo":"amarillo","tecnico_id":"T-06","brote":true` | **n=3**: R-2047 (misma parcela P-239, 45 h) + R-2152 (2.2 km, 1.5 h). |
| R-2162 | `…"plaga":"tizon_tardio","semaforo":"naranja","tecnico_id":"T-09","brote":true` | **n=3**: R-2140 (0.78 km) + R-2104 (2.06 km) + R-2077 (cluster 24 h con R-2140). |
| R-2163 | `…"plaga":"chapulin","semaforo":"amarillo","tecnico_id":"T-08","brote":true` | **n=6**: R-2005, R-2011, R-2100 + previos R-1039/R-1047. |
| R-2164 | `…"plaga":"chapulin","semaforo":"amarillo","tecnico_id":"T-06","brote":true` | **n=4**: R-2005 + previos R-1039/R-1047. |

## 6. Dudosos — requieren tu criterio (4)

| Reporte | Duda | Mi lectura | Riesgo |
|---|---|---|---|
| R-2156 | Audio: “hojas agujeradas, se lo están comiendo”. No dice “orilla”. | **cogollero**, 100 %, naranja, T-06, brote false (n=1) | Podría ser chapulín. Es el único diagnóstico inferido, no explícito. |
| R-2158 | Brote **n=2**: R-2142 (1.0 km, otro productor). | **brote=false**; plaga/foto sólidas (mancha_chocolate, 100 %, naranja, T-07). | Zona gris tipo R-2152. Sin tercer caso oculto (vecino de otro productor). |
| R-2160 | Brote **n=2**: R-2130 (1.75 km, otro productor). | **brote=false**; mancha_chocolate, 10 %, amarillo, T-07. | Igual: n=2 limpio, pero es zona gris. |
| R-2167 | Brote **n=2**: R-2021 (3.87 km, otro productor). | **brote=false**; chapulín, 75 %, amarillo, T-11. | Foto es maíz y la parcela dice frijol; chapulín es válido en ambos. |

> **Por qué los n=2 preocupan:** R-2152 (n=2) fue **true** en la API porque un
> caso del mismo productor sin parcela (R-2082) no lo contaba nuestro motor.
> Aquí los vecinos son de **otro productor** y no hay caso oculto, así que
> `false` es la lectura natural; aun así, es la decisión que más conviene que
> revises.

## 7. Errores de la app detectados en esta tanda

1. **R-2154:** inventó `pulgon` + parcela P-089 + 10 % en un trámite de padrón.
2. **R-2156, R-2158, R-2163, R-2164, R-2165, R-2166, R-2167:** quedaron en
   `desconocida` porque el STT/visión del servidor no resolvió (o el resultado
   se procesó antes de la transcripción). El motor local sí las resolvió.
3. **R-2157:** extrajo **10 %** de “están todas las plantas así”; el valor
   correcto es **100 %** (misma lección de R-2143/R-2152). Cambia el semáforo de
   verde a amarillo.
4. **R-2162:** la app sí acertó (tizón, 25 %, naranja, brote true) porque
   reprocesó con la respuesta `-R`.

## 8. Recomendación operativa

- Enviar primero los **5 seguros** (no requieren discusión).
- Aprobar/ajustar los **5 brotes confirmados** (n≥3): el brote es el campo que
  decide la competencia y la regla exige visto bueno.
- Decidir los **3 n=2** (R-2158, R-2160, R-2167): mi lectura es `brote:false`.
- R-2156: confirmar cogollero vs chapulín antes de enviar.

Payloads listos en `cache/_payloads_14.json` (formato validado, sin registrar).

---

# Segunda parte — envío de seguros y reanálisis de brotes

## 9. Enviados: 5 seguros → +14 pts, 0 errores

| Reporte | Puntos | Detalle |
|---|---|---|
| R-2154 | **1/1** | `es_plaga` correcto (no plaga) |
| R-2155 | **1/1** | `es_plaga` correcto (no plaga) |
| R-2157 | **5/5** | pulgón, semáforo amarillo, T-08, brote false — **el pct 100 era correcto** |
| R-2165 | **5/5** | chapulín, naranja, T-10, brote false |
| R-2166 | **2/2** | tizón; confirmado **seguimiento** de R-2162 (“no abre caso nuevo”) |

**Total +14.** Tabla: 576/662, **2.º**, a 3 pts de xD (579). Errores siguen en 14.

## 10. Reanálisis profundo de brotes

### Calibración contra la verdad oficial
Se recalcularon los **40 casos de `/casos-previos`** con la regla actual
(3+ casos, <5 km, 168 h, dedupe cluster 24 h): **40/40 aciertos**.
`n ≥ 3 → true`, `n = 2 → false`, `n ≤ 1 → false`. La única excepción histórica
(R-2152) fue por un caso del mismo productor sin parcela (R-2082); aquí se
revisaron todos los casos por productor para descartar ese patrón.

### Casos ocultos y seguimientos revisados
- **R-2053** (mismo productor/parcela que R-2158, 42.8 h antes, `desconocida`):
  la API confirma **“no abre un caso nuevo”** → es seguimiento y **no cuenta**.
- **R-2114** (PR-178, 21 h antes de R-2159): probable **seguimiento** por mismo
  productor. Si la API lo trata así, R-2159 vale 2 (es_plaga+plaga) y el brote
  no se califica; si lo trata como nuevo, n=9 → true. **Enviar completo no
  arriesga nada** en ambos escenarios.
- **R-2101** (PR-152, 23.8 h antes de R-2160): probable **seguimiento**. Igual:
  si es seguimiento, solo cuentan es_plaga+plaga (mancha de chocolate).
- **PR-140, PR-250**: no hay más casos de la misma plaga; los n=2 no esconden
  un tercer caso.
- **PR-273**: R-2047 (44.9 h) sí cuenta (>24 h); R-2082 es seguimiento.
- **PR-139**: R-2162 es el primer caso del día; R-2166 es su seguimiento.
- **PR-134 / PR-213**: padres >24 h (R-2061 y R-2046) → no son seguimiento.

### Resultado por reporte

| Reporte | Plaga | n | ¿Seguimiento? | Brote | Confianza |
|---|---|---|---|---|---|
| R-2158 | mancha_chocolate | 2 | No (R-2053 sí lo es) | **false** | Alta |
| R-2159 | pulgon | 9 | Probable (R-2114, 21 h) | **true** (o no se califica) | Alta |
| R-2160 | mancha_chocolate | 2 | Probable (R-2101, 23.8 h) | **false** (o no se califica) | Alta |
| R-2161 | gallina_ciega | 3 | No (R-2047, 44.9 h) | **true** | Alta |
| R-2162 | tizon_tardio | 3 | No | **true** | Alta |
| R-2163 | chapulin | 6 | No | **true** | Alta |
| R-2164 | chapulin | 4 | No | **true** | Alta |
| R-2167 | chapulin | 2 | No | **false** | Alta |

**Brote confirmado TRUE (5):** R-2159, R-2161, R-2162, R-2163, R-2164.
**Brote FALSE sólido (3):** R-2158, R-2160, R-2167 (n=2 limpio, vecinos de otro
productor, sin caso oculto; la calibración oficial respalda `false`).
**R-2156** sigue fuera de los brotes (n=1 → false); su duda es de clasificación
(cogollero vs chapulín).

## 11. Recomendación

1. Enviar los **5 brotes TRUE** con payload completo. R-2161/62/63/64 deberían
   dar 5/5; R-2159 dará 5/5 si es nuevo o 2/2 si es seguimiento.
2. Enviar los **3 n=2 con `brote:false`**. Deberían dar 5/5 (R-2160 2/2 si es
   seguimiento). Si se prefiere riesgo cero, se pueden enviar sin `brote`
   (4/4) y complementar después; pero la evidencia respalda `false`.
3. **R-2156**: confirmar cogollero antes de enviar (o mandar solo
   es_plaga+plaga, sin nivel 2).
4. Nada de esto se ha enviado: espera tu veredicto.
