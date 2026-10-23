# Estado y ramas — Alerta Plaga 7_7

> Foto del repositorio al **22-oct-2026**. Para el estado en vivo, consultar
> `GET /tabla.json` y `GET /equipo`; este documento no reemplaza a la API.

---

## 1. Último corte documentado

| Dato | Valor |
|---|---|
| Fecha | 22-oct-2026, 13:30 |
| Puntos | 576/662 |
| Lugar | 2.º |
| Enviados | 158/167 |
| Pendientes | 9 |
| Errores | 14 |
| Cierre | 22-oct-2026, 23:59 |

Después de ese corte se agregaron commits de fixes y del modelo autónomo, pero
no hay un nuevo corte documentado en el repo.

---

## 2. Ramas

| Rama | Head de código | Vs `main` | Aportación única | Estado |
|---|---|---|---|---|
| `main` | `5a434f0` | — | Integración actual | Rama principal |
| `Caso_Emmanuel` | `6178e44` + docs | 8 atrás / 1 adelante | Ledger de confirmados + replay | PR #9 abierto a `main` |
| `fix/brotes-revision-rafa` | `1768656` | 23 atrás / 1 adelante | Brote conservador + alertas | PR #8 abierto a `Caso_Emmanuel` |
| `Rafa` | `5cf0e93` | 58 atrás / 0 adelante | `REPORTE_FINAL` | PRs #1–#4 mergeados; rama vieja |
| `fix/supabase-persistencia` | `252a498` | 71 atrás / 0 adelante | Persistencia Supabase | PR #5 mergeado; rama vieja |

> “Head de código” es el commit de código analizado. El commit que actualiza
> esta documentación es posterior y no cambia la comparación de código.

### `main`

Rama de integración. Incluye:

- motor de texto, voz y foto;
- consenso híbrido;
- nivel 2;
- brote con dedupe productor + parcela;
- `n=2` conservador;
- cola de dudosos;
- preguntas automáticas;
- `decision_autonoma`;
- vigilante;
- dashboard y Supabase.

Los últimos 8 commits sobre la base de `Caso_Emmanuel` son:

```
5a434f0 vigilante sin avisos de confirmación
ef63a1c decisión autónoma de 4 intentos
d89ea01 cierres/agradecimientos no son plaga
f3ffb2c dedupe productor + parcela (R-2204)
2413597 señales de cogollero
fd100f1 hojas agujeradas no es 100 %
f2c2132 saludo/junta no tapa mancha chocolate
d84ab60 “todas las plantas” = 100 %
```

### `Caso_Emmanuel` (PR #9)

Aporta:

- `bot/confirmados.py`;
- ledger de casos confirmados por la API;
- exclusión de falsas alarmas;
- recálculo de brote al aprobar;
- `bot/probar_brotes.py`;
- `bot/replay_brotes.py`;
- documentación de brotes.

Propuesta adicional en revisión:

- coherencia de hospedero como evidencia para la revisión;
- no usarla como filtro del conteo.

**Riesgo:** la rama está basada en `2de5318`, 8 commits atrás de `main`. Antes de
mergear hay que reconciliar:

- el dedupe productor + parcela de `main` con el ledger de la rama;
- la política `n=2` de `decidir_brote` con el “brote profundo” de
  `decision_autonoma`;
- los cambios de documentación.

### `fix/brotes-revision-rafa` (PR #8)

Aporta:

- brote conservador;
- `evaluar_caso.py`;
- referencias auditables;
- alertas de revisión con botones;
- parte del flujo de dudosos.

Parte de esta rama se integró de forma selectiva a `main` con `aedafb3`, pero la
rama sigue abierta y apunta a `Caso_Emmanuel`, no a `main`.

**Riesgo:** solapamiento con PR #9 y con lo ya integrado en `main`. Revisar antes
de mergear.

### `Rafa`

Rama de documentación/reporte final. Sin commits únicos frente a `main`; sus PRs
#1–#4 ya están mergeados. Se conserva como referencia histórica.

### `fix/supabase-persistencia`

Rama de persistencia Supabase. Sin commits únicos frente a `main`; PR #5 ya está
mergeado. Se conserva como referencia histórica.

---

## 3. PRs

| PR | Título | Base | Estado |
|---|---|---|---|
| #1 | listener, STT y fusión multimodal | `main` | mergeado |
| #2 | prioridad, semáforo y técnico | `main` | mergeado |
| #3 | `CASOS_SALIDA` | `main` | mergeado |
| #4 | importar `os` | `main` | mergeado |
| #5 | persistencia Supabase | `main` | mergeado |
| #6 | respuestas, previos/visitas y reconciliación | `main` | mergeado |
| #8 | brote conservador y alertas | `Caso_Emmanuel` | abierto |
| #9 | ledger de confirmados y replay | `main` | abierto |

---

## 4. Divergencia principal

`main` tiene features que **no** están en `Caso_Emmanuel`:

- `decision_autonoma.py`;
- dedupe productor + parcela;
- fixes de pct/prefiltro/cogollero;
- vigilante sin avisos de confirmación.

`Caso_Emmanuel` tiene features que **no** están en `main`:

- ledger de confirmados;
- recálculo al aprobar;
- replay de variantes;
- propuesta de coherencia de hospedero.

### Recomendación de integración

1. Actualizar `Caso_Emmanuel` con `main`.
2. Resolver el conflicto de `nivel2.py` conservando **productor + parcela**.
3. Revisar que el ledger no rompa el dedupe.
4. Correr:
   - `probar_motor`
   - `validar_nivel2`
   - `validar_brote`
   - `probar_brotes`
   - `replay_brotes`
5. Actualizar PR #9.
6. Decidir qué parte de PR #8 ya está en `main` y cerrar la rama si ya no aporta.
7. No activar `PERMITIR_ENVIOS=1` sin revisar la cola.

---

## 5. Riesgos de las ramas

| Riesgo | Detalle |
|---|---|
| Merge con conflictos | `nivel2.py`, `clasificador.py`, `listener.py` cambiaron en ambos lados |
| Regresión de dedupe | Si gana la versión de la rama, se pierde R-2204 |
| Doble política `n=2` | `decidir_brote` vs `decision_autonoma` |
| PR #8 duplicado | Parte ya está en `main` por `aedafb3` |
| Docs desfasados | `CHECKPOINT_SESION` y `REPORTE_FINAL` son de cortes anteriores |
| Envíos accidentales | `PERMITIR_ENVIOS` debe seguir apagado hasta validar |

---

## 6. Próximos pasos

1. Reconciliar `Caso_Emmanuel` con `main`.
2. Evaluar el ledger contra los 40 previos y los 5 casos reales.
3. Revisar la coherencia de hospedero como evidencia, no como filtro.
4. Cerrar o actualizar PR #8.
5. Actualizar el corte final del reto en la documentación.
6. Si se activa el envío automático, hacerlo con la cola vacía y monitoreo.

---

## 7. Documentos relacionados

- [`ARQUITECTURA.md`](ARQUITECTURA.md)
- [`NIVEL2.md`](NIVEL2.md)
- [`OPERACION.md`](OPERACION.md)
- [`DECISIONES_Y_PROPUESTAS.md`](DECISIONES_Y_PROPUESTAS.md)
- [`../REPORTE_BROTES_CASO_EMMANUEL.md`](../REPORTE_BROTES_CASO_EMMANUEL.md)
