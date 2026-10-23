# Decisiones y propuestas — Alerta Plaga 7_7

> Registro de las decisiones importantes, el problema que resolvían y lo que
> sigue pendiente. Sirve para defender el diseño y para no repetir errores.

---

## 1. Decisiones de arquitectura

### 1.1 La IA interpreta; el código decide

**Problema:** el reglamento califica `semaforo`, `tecnico` y `brote`; si los
decidiera un LLM, dos ejecuciones podrían dar resultados distintos.

**Decisión:** la IA solo interpreta el mensaje (plaga y pct). Prioridad,
semáforo, técnico y brote se calculan en `nivel2.py`.

**Por qué:** cumplimiento del reglamento, reproducibilidad, testeabilidad y
defensa ante la junta.

**Evidencia:** R-2056; la IA decía “no plaga” y las reglas acertaban roya. Se
adoptó consenso híbrido y las reglas quedaron como autoridad final.

### 1.2 Consenso híbrido `INTERPRETAR_IA=2`

**Problema:** ni las reglas ni la IA son perfectas.

**Decisión:**

1. Reglas e IA evalúan.
2. Si coinciden, se acepta.
3. Si difieren, se busca precedente histórico de la parcela/cultivo.
4. Sin precedente, mandan las reglas.

**Por qué:** reduce errores de la IA sin perder su capacidad de leer lenguaje
natural.

### 1.3 `desconocida` antes que inventar

**Problema:** una plaga inventada resta; `desconocida` vale 0.

**Decisión:** si no hay señal suficiente o la plaga no es compatible con el
cultivo, se usa `desconocida`.

**Por qué:** no arriesgar puntos y no engañar al productor.

**Matiz:** en maíz, un texto vago con `desconocida` suele valer 2/2; en frijol no
siempre. Por eso hay revisión humana.

### 1.4 Preguntar en vez de inferir la parcela

**Problema:** la inferencia de parcela falló (R-2128: P-050 vs P-051 real).

**Decisión:** si falta parcela, se manda `POST /preguntas` y se espera la
respuesta `-R`. Si la parcela fue inferida, el caso se aparca.

**Por qué:** una parcela equivocada contamina semáforo, técnico y brote.

### 1.5 Cola de dudosos con visto bueno

**Problema:** registrar a ciegas cuesta puntos irrecuperables.

**Decisión:** todo brote, `n=2`, `desconocida`, baja confianza, voz sin
transcripción o parcela inferida se aparca.

**Por qué:** `POST /casos` es irreversible; una vez calificado, no se corrige.

### 1.6 `n=2` es zona gris

**Problema:** un `n=2` puede ser `true` o `false`.

**Decisión:** `n=2` no se envía; va a revisión. `n>=3` true; `n<=1` false.

**Evidencia:**

- R-2135, R-2138, R-2146: `n=2` con `false` correcto.
- R-2152: `n=2` con `true` correcto.

**Por qué:** asumir `false` o `true` por defecto cuesta un punto.

### 1.7 Dedupe por productor + parcela

**Problema:** el dedupe solo por productor colapsaba parcelas distintas
(R-2204) y el dedupe global causaba falsos negativos (R-2084).

**Decisión:** clúster de 24 h por **productor + parcela**.

**Evidencia:**

- R-2043: mismo productor/parcela en horas → 1 evento.
- R-2084: mismo productor/parcela 2 días después → 2 eventos.
- R-2204: mismo productor, otra parcela → evento distinto.

**Por qué:** refleja mejor la regla y evita falsos positivos/negativos.

### 1.8 Modelo de decisión autónoma de 4 intentos

**Problema:** la cola de dudosos podía quedarse dormida.

**Decisión:** `decision_autonoma.py` reanaliza hasta 4 veces:

1. app vs motor;
2. reglas vs IA;
3. antecedentes;
4. brote profundo y pct.

Si sigue dudoso, avisa al coordinador.

**Por qué:** automatizar lo seguro sin registrar a ciegas lo ambiguo.

**Riesgo:** el “brote profundo” puede convertir `n=2` en `true`; es una capa de
revisión, no la regla oficial.

### 1.9 `PERMITIR_ENVIOS` apagado por defecto

**Problema:** un error de configuración podía registrar casos sin revisión.

**Decisión:** sin `PERMITIR_ENVIOS=1`, el agente solo clasifica, guarda,
pregunta y deja cola.

**Por qué:** el costo de un registro equivocado es irreversible.

### 1.10 Dashboard con proxy y fallback

**Problema:** el token no debe llegar al navegador y la API puede fallar.

**Decisión:** Express hace de proxy; si la API falla, usa `cache/`.

**Por qué:** seguridad y continuidad operativa.

### 1.11 Caché local + Supabase

**Problema:** Supabase puede no estar configurado o fallar.

**Decisión:** siempre se escribe la caché local; Supabase es adicional.

**Por qué:** el flujo nunca se detiene por una dependencia externa.

---

## 2. Decisiones sobre reglas del reto

### 2.1 Seguimientos

- Mismo productor/parcela < 24 h.
- Tener visita no cierra el caso para esta regla.
- Solo califican `es_plaga` + `plaga` (máx. 2).
- En papa/tizón suele convenir `desconocida`.
- Si el mensaje no nombra la plaga, no heredar a ciegas.

**Por qué:** R-2126 mostró que heredar la plaga del padre puede fallar.

### 2.2 Puntos

- `desconocida` y campos omitidos valen 0.
- Campo errado resta 1.
- Una sola oportunidad por `reporte_id`.
- El desempate es por latencia.
- Complementos solo suman si el reporte abre caso nuevo.

**Por qué:** entender esto cambia la estrategia: mejor no inventar y registrar
pronto lo seguro.

### 2.3 Catálogo por cultivo

El filtro final es `GET /plagas`, no el documento de diagnóstico.

**Por qué:** el documento es guía agronómica general; el catálogo es lo que
califica la API.

---

## 3. Propuestas de la rama `Caso_Emmanuel` (PR #9)

### 3.1 Ledger de casos confirmados

**Problema:** `evaluar_brotes` en `main` cuenta todos los casos locales,
incluidos propuestas y aparcados. La API solo conoce los que recibió.

**Propuesta:**

- `cache/casos_confirmados.json`;
- guardar plaga/coordenadas congeladas al recibir `201`/`409`;
- contar previos + confirmados + caso actual;
- excluir falsas alarmas;
- recalcular al aprobar.

**Por qué:** evita inflar brotes con casos fantasma. No cambia la fórmula.

**Estado:** implementado en la rama; pendiente de revisión/merge.

### 3.2 Coherencia de hospedero

**Problema:** una plaga específica en un cultivo no hospedero sugiere mala
clasificación.

**Propuesta:**

- añadir `cultivo`, `hospedero_ok` y `hospedero_fuente` a las referencias;
- avisar en Telegram si una referencia es incoherente;
- no filtrar el conteo por cultivo.

**Por qué:** ayuda al revisor a detectar un brote falso por mala clasificación.

**Estado:** propuesta en revisión; no debe usarse como regla de puntos.

### 3.3 Replay de variantes

**Problema:** no había forma de comparar dedupe/fuentes sin tocar producción.

**Propuesta:** `bot/replay_brotes.py` con escenarios:

- propuestos vs confirmados;
- dedupe productor vs parcela vs sin dedupe;
- cola `n=2` sin confirmar.

**Por qué:** permite decidir con datos y no por intuición.

---

## 4. Propuestas descartadas o condicionadas

### 4.1 Filtrar el brote por cultivo

**Descartado.** La regla oficial no usa cultivo. El documento de hospederos
advierte que no se debe descartar una plaga solo por cultivo cuando su rango es
amplio.

### 4.2 Inferir la parcela y registrar

**Descartado.** Falló en R-2128. Se pregunta.

### 4.3 Dejar que la IA decida prioridad/semáforo

**Descartado.** Viola el reglamento y rompe la reproducibilidad.

### 4.4 Registrar todo automáticamente

**Condicionado.** Solo con `PERMITIR_ENVIOS=1` y después de validar la cola.

### 4.5 Confiar en `POST /casos/validar` como verdad

**Descartado.** Valida formato, no clasificación. No dice si la plaga es
correcta.

---

## 5. Riesgos abiertos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| `main` y `Caso_Emmanuel` divergen | merge complejo | reconciliar dedupe productor+parcela con ledger |
| Dos políticas `n=2` | decisiones distintas | documentar y revisar |
| Dos brotes (oficial y avisos) | alertas distintas | no confundir con puntos |
| Contar casos no confirmados | falsos positivos | ledger propuesto |
| Inferencia de parcela | caso mal ubicado | preguntar |
| Documentación histórica desfasada | confusión | docs vivos + estado de ramas |
| Secretos | filtración | `.env` ignorado |

---

## 6. Criterios para aceptar un cambio

1. No rompe `probar_motor`.
2. No rompe `validar_nivel2` (40/40/40).
3. No rompe `validar_brote` (40/40 + 5/5).
4. No cambia decisiones históricas sin evidencia.
5. No requiere `POST /casos` para probar.
6. No activa envíos por defecto.
7. Documenta el por qué y el caso real que lo motivó.

---

## 7. Documentos relacionados

- [`ARQUITECTURA.md`](ARQUITECTURA.md)
- [`NIVEL2.md`](NIVEL2.md)
- [`OPERACION.md`](OPERACION.md)
- [`ESTADO_Y_RAMAS.md`](ESTADO_Y_RAMAS.md)
