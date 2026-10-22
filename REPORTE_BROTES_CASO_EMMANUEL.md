# Reporte de brotes — rama Caso_Emmanuel

> Fecha: 2026-10-22. Rama: `Caso_Emmanuel`, sincronizada con `main` (`2de5318`).
> Este trabajo **no** modifica `main`, no despliega y no activa envíos
> automáticos. Los cambios están solo en esta rama.

## 1. Qué se cambió

### 1.1 Fuente de verdad: solo casos confirmados

Antes, `evaluar_brotes` contaba **todos** los casos locales: propuestas,
aparcados para revisión y falsas alarmas descartadas. La API solo puede contar
lo que realmente recibió por `POST /casos`; por eso un caso aparcado podía
inflar el brote de los siguientes aunque nunca se registrara.

Ahora:

- `bot/confirmados.py` mantiene `cache/casos_confirmados.json` con la plaga y
  coordenadas **congeladas** del momento en que la API aceptó el caso
  (`201` o `409`).
- `Clasificador.evaluar_brotes(..., confirmados=...)` usa como referencias:
  **previos + confirmados + el caso/lote que se está evaluando**.
- Los casos aparcados, propuestos o descartados no cuentan.
- `cache/casos_descartados.json` excluye las falsas alarmas retiradas de la
  cola, incluso si alguna vez estuvieron en el ledger.
- Al aprobar desde Telegram se **recalcula** el brote con el ledger actual; ya
  no se reenvía el payload viejo de la cola.
- `/añadir`, `evaluar_caso.py` y `resolver_cola.py` usan la misma fuente.

### 1.2 Datos congelados

El ledger guarda la plaga y coordenadas que se enviaron. Si el motor
reclasifica un caso después, el conteo histórico no cambia. Esto también evita
que `_reconstruir_enviados` altere el pasado con la clasificación actual.

### 1.3 Dedupe comparable

`contar_casos_cercanos` ahora permite tres variantes:

| Variante | Uso |
|---|---|
| `dedupe_productor_propios=True` (default) | productor + 24 h, comportamiento actual |
| `dedupe_por_parcela=True` | mismo productor **y misma parcela** en 24 h |
| `dedupe_productor_propios=False` | regla pura, sin dedupe |

No se cambió el default de producción: sigue siendo productor + 24 h.

### 1.4 Observabilidad

Cada caso guarda:

- `_brote_n`
- `_brote_refs` (con `fuente`, `horas`, `distancia_km`, `parcela_id`)
- `_brote_modo`
- `_brote_confirmados`

Telegram muestra las referencias con su fuente y antigüedad en horas.

### 1.5 Archivos tocados

```
bot/confirmados.py          (nuevo) ledger y casos descartados
bot/nivel2.py               variante dedupe por parcela
bot/clasificador.py         evaluar_brotes con confirmados/descartados
bot/listener.py             siembra y actualiza ledger, 409, lote confirmado
bot/bot_telegram.py         recálculo al aprobar, descarte de falsas alarmas
bot/evaluar_caso.py         brote con ledger
bot/resolver_cola.py        brote con ledger
bot/telegram_notificador.py refs con fuente/horas
bot/probar_brotes.py        (nuevo) pruebas de invariantes
bot/replay_brotes.py        (nuevo) replay offline de variantes
```

## 2. Metodología de evaluación

No había token disponible en el entorno local, así que la evaluación se hizo
**offline**, sin llamar a la API y sin registrar nada:

- **40 casos previos** de `cache/cache_casos_previos.json` con respuesta oficial.
- **120 casos únicos** de la bitácora real del servidor
  (`listener_bitacora_servidor.jsonl`; 127 entradas, las respuestas `-R` se
  fusionaron con su padre).
- **5 casos reales documentados** con resultado oficial:
  R-2043, R-2055, R-2070, R-2073 y R-2084.

Cobertura de la bitácora:

- 120 casos únicos.
- 86 con plaga concreta y parcela con coordenadas.
- 5 seguimientos.
- 82 referencias utilizables para el ledger (plaga + coordenadas).

Limitación importante: para los casos propios **no existe una etiqueta oficial
por caso** en los datos locales. El replay mide cambios de decisión y verifica
los 5 casos documentados; no inventa una exactitud sobre los 120.

## 3. Resultados

### 3.1 Casos previos (verdad oficial)

| Variante | Aciertos |
|---|---:|
| Regla oficial | 40/40 |
| Sin dedupe | 40/40 |
| Dedupe por parcela | 40/40 |

La regla base sigue intacta. Como los previos nunca pasan por el dedupe, esta
prueba no valida el dedupe; solo la fórmula.

### 3.2 Casos reales documentados

| Caso | Esperado | n nuevo | Decisión nueva |
|---|---:|---:|---|
| R-2043 | False | 1 | False (seguimiento) |
| R-2055 | True | 3 | True |
| R-2070 | True | 5 | True |
| R-2073 | True | 6 | True |
| R-2084 | True | 3 | True |

**5/5** con el modelo nuevo.

### 3.3 Escenario A: todos los casos reales ya confirmados

Simula que los 120 casos de la bitácora fueron aceptados por la API. Mide si el
modelo nuevo cambia alguna decisión histórica (regresión).

| Variante | Cambios vs histórico |
|---|---:|
| Propuestos (histórico) | 0 |
| Confirmados + dedupe productor | **0** |
| Confirmados + dedupe parcela | 1 |
| Confirmados sin dedupe | 5 |

- **Confirmados + dedupe productor reproduce exactamente el pasado**: 0 cambios.
  Es un reemplazo seguro para el flujo actual.
- Dedupe por parcela cambia 1 caso (R-2043 pasa a zona gris).
- Sin dedupe cambia 5 casos y **reintroduce el falso positivo R-2043**
  (`False -> True`). Por eso no conviene quitar el dedupe por productor.

### 3.4 Escenario B: cola conservadora (n=2 no confirmado)

Simula el peor caso: los casos con `n=2` se aparcan y **no se confirman** para
los siguientes. Es el escenario donde el ledger realmente demuestra su valor.

| Variante | Cambios vs histórico |
|---|---:|
| Confirmados + dedupe productor | 8 |
| Confirmados + dedupe parcela | 9 |
| Confirmados sin dedupe | 11 |

Los 8 cambios de la variante recomendada son todos `True -> None`:

```
R-2031, R-2045, R-2066, R-2070, R-2073, R-2084, R-2102, R-2109
```

Es decir: si un caso `n=2` queda aparcado y no se aprueba, los siguientes ya no
inflan el brote con un caso que la API no conoce. El modelo se vuelve
**conservador**, no optimista. Eso evita falsos positivos (que restan) a costa
de no marcar algunos brotes hasta que se apruebe la cola.

### 3.5 Comparación de dedupe

El escenario A confirma la decisión de diseño:

- Dedupe productor: 0 cambios.
- Dedupe parcela: 1 cambio.
- Sin dedupe: 5 cambios y R-2043 vuelve a fallar.

**Recomendación:** mantener `dedupe_productor_propios=True` (24 h).

## 4. Pruebas de invariantes

`python bot/probar_brotes.py` → **11/11 OK**:

- mismo productor en 3 parcelas se colapsa con dedupe por productor;
- no se colapsa con dedupe por parcela;
- 2 confirmados + caso actual = n=3;
- un no confirmado no cuenta (n=2);
- un descartado no cuenta;
- n=2 queda en zona gris (`None`);
- la plaga congelada manda sobre la clasificación local;
- seguimientos y plaga desconocida no se evalúan.

## 5. Batería existente

- `python bot/probar_motor.py` → **96 pruebas, 1 fallo preexistente**:
  “el seguimiento calcula semáforo/técnico”.
  Verificado también en un worktree limpio de `origin/main` (`2de5318`):
  **el mismo fallo aparece sin estos cambios**. No es una regresión de esta rama.
- `python bot/validar_brote.py` (offline, con caché) → **40/40 + 5/5**.
- `python bot/replay_brotes.py` → resultados de la sección 3.
- `python -m py_compile` sobre todos los módulos tocados → OK.

`validar_nivel2.py` no se pudo ejecutar sin token porque consulta
`/casos-previos` y `/tecnicos` en vivo. No se tocaron las fórmulas de
prioridad, semáforo ni técnico.

## 6. Cómo se comporta en producción

1. Al arrancar, el listener siembra el ledger con los casos que ya están en
   `listener_estado.enviados` y `casos_propuestos.json`. No reenvía nada.
2. Cada `POST /casos` exitoso (`201` o `409`) congela la referencia.
3. El brote del lote nuevo se calcula con previos + ledger + lote actual.
4. Todo `brote=True` sigue yendo a revisión manual (no se cambió esa política).
5. Al aprobar, el bot recalcula con el ledger actual; si el resultado es n=2,
   no envía `brote` y el caso queda en zona gris.
6. Una falsa alarma retirada de la cola se excluye de brotes posteriores.

## 7. Riesgos y límites

- **Carrera entre procesos:** listener y bot escriben el ledger. Se mitigó
  fusionando con el disco antes de guardar; aun así, es un archivo local, no una
  base transaccional.
- **Cobertura de coordenadas:** 34 de 120 casos de la bitácora no tienen
  plaga/parcela utilizables; no pueden contar. Esto ya era así en la regla, pero
  ahora es visible.
- **Cola:** si los `n=2` no se revisan, el modelo no los cuenta. Es correcto
  frente a la API, pero puede dejar brotes sin marcar. Conviene vaciar la cola.
- **Sin etiqueta oficial por caso:** el replay no puede afirmar una exactitud
  sobre los 120; solo cambios de decisión y los 5 casos documentados.
- **Primer arranque:** si `cache/casos_confirmados.json` no existe, se crea desde
  los enviados. Si un caso viejo no está en `casos_propuestos.json`, no se puede
  reconstruir.
- **No se modificó** ningún flag de envío (`--enviar`, `PERMITIR_ENVIOS`), ni
  tareas de despliegue, ni `main`.

## 8. Comandos para reproducir

```powershell
python bot/probar_brotes.py
python bot/replay_brotes.py --detalle
python bot/replay_brotes.py --json | Out-File -Encoding utf8 cache/replay_brotes.json

# Requiere .env con EQUIPO_TOKEN/API_BASE_URL:
python bot/probar_motor.py
python bot/validar_brote.py
```

## 9. Recomendación operativa

- Mantener el dedupe por productor 24 h.
- Mantener el ledger y la política `n=2` en zona gris.
- Revisar y aprobar la cola con frecuencia: cada `n=2` pendiente es un caso que
  la API no conoce y que el modelo nuevo, correctamente, no cuenta.
- No quitar el dedupe sin volver a correr `probar_brotes`, `replay_brotes` y
  los 5 casos documentados.
