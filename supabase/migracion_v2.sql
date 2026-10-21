-- ============================================================================
-- Alerta Plaga · Migración v2 (cambios aditivos sobre schema.sql)
-- ----------------------------------------------------------------------------
-- Pensada para aplicarse sobre una base que ya tiene las 15 tablas creadas.
-- No borra ni reescribe datos: solo agrega columnas e índices que el bot ya
-- produce (casos.seguimiento_de) o que el dashboard consulta (municipio,
-- visitas por reporte, eventos por tipo).
--
-- Es idempotente: se puede ejecutar varias veces sin error.
-- Aplicar en Supabase → SQL Editor.
-- ============================================================================

begin;

-- ---------------------------------------------------------------------------
-- 1. Cadena de seguimiento de casos
--    El clasificador devuelve `seguimiento_de` (id del reporte padre) y el
--    listener lo guarda en `casos.raw`, pero no había columna para consultarlo.
--    Sin FK a propósito: el reporte padre puede no estar en `casos` (p. ej. si
--    el listener arrancó a mitad del reto) y un fallo de FK perdería el caso.
-- ---------------------------------------------------------------------------
alter table public.casos
  add column if not exists seguimiento_de text;

create index if not exists idx_casos_seguimiento
  on public.casos (seguimiento_de)
  where seguimiento_de is not null;

-- ---------------------------------------------------------------------------
-- 2. Índices de consulta que faltaban
-- ---------------------------------------------------------------------------
-- Visitas: solo existía el índice por técnico, no por reporte.
create index if not exists idx_visitas_reporte
  on public.visitas (reporte_id);

-- Bitácora: el bot y el dashboard filtran por tipo además de fecha.
create index if not exists idx_eventos_tipo
  on public.eventos (tipo, creado_en desc);

-- Dashboard: agrupa parcelas por municipio.
create index if not exists idx_parcelas_municipio
  on public.parcelas (municipio);

-- ---------------------------------------------------------------------------
-- 3. Estado de sincronización con detalle del fallo
--    `sincronizar_catalogos()` ya escribe ok/detalle; estas columnas permiten
--    guardar el error y el número de intentos sin tocar el código actual.
-- ---------------------------------------------------------------------------
alter table public.catalogos_sync
  add column if not exists error text;

alter table public.catalogos_sync
  add column if not exists intentos integer not null default 0;

alter table public.catalogos_sync
  drop constraint if exists catalogos_sync_intentos_check;

alter table public.catalogos_sync
  add constraint catalogos_sync_intentos_check check (intentos >= 0);

-- ---------------------------------------------------------------------------
-- 4. Trigger de marca de tiempo para las columnas nuevas
--    (casos ya lo tiene; se recrea por si la base venía de una versión previa)
-- ---------------------------------------------------------------------------
drop trigger if exists trg_casos_actualizado on public.casos;
create trigger trg_casos_actualizado before update on public.casos
  for each row execute function public.actualizar_marca_tiempo();

-- ---------------------------------------------------------------------------
-- 5. Permisos: las columnas nuevas heredan los grants de la tabla,
--    pero se reafirman para service_role.
-- ---------------------------------------------------------------------------
grant all on table public.casos to service_role;
grant all on table public.catalogos_sync to service_role;
grant all on table public.visitas to service_role;
grant all on table public.eventos to service_role;
grant all on table public.parcelas to service_role;

commit;
