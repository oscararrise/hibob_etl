# HiBob ETL

Servicio ETL para extraer empleados y metadatos desde HiBob, generar archivos de respaldo y cargar la tabla consolidada en PostgreSQL mediante upsert.

## Flujo

1. Consulta metadatos y empleados con una o varias credenciales de HiBob.
2. Consolida los registros por `HiBob Root ID`.
3. Genera Excel y JSON en `output/`.
4. Cuando `POSTGRES_ENABLED=true`, crea el esquema y la tabla si no existen.
5. Agrega columnas nuevas sin eliminar las existentes.
6. Ejecuta un upsert por lotes y guarda auditoría en `etl_run_history`.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## PostgreSQL

Configuración recomendada cuando el ETL y PostgreSQL corren en la misma VM:

```env
POSTGRES_ENABLED=true
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=arrise_vm_db
POSTGRES_USER=hibob_etl
POSTGRES_PASSWORD=replace_me
POSTGRES_SCHEMA=hibob_etl_daily_scheduled_report
POSTGRES_TABLE=hibob_employees
POSTGRES_UPSERT_KEY=HiBob Root ID
POSTGRES_BATCH_SIZE=1000
```

El usuario de PostgreSQL necesita permisos para conectarse a la base, crear el esquema y crear o modificar tablas dentro de ese esquema. En producción es preferible crear el esquema previamente y otorgar permisos únicamente sobre ese esquema.

## Diseño de la tabla

Las columnas dinámicas de HiBob se almacenan como `TEXT`. Esto es intencional: una tabla de aterrizaje no debe romperse porque HiBob entregue un campo como número en una corrida y como texto en otra.

Los nombres de columnas se normalizan de forma estable:

- `HiBob Root ID` → `hibob_root_id`
- `RAW | Root | Email | root.email` → `raw_root_email`
- `HR | Work | Department | work.department` → `hr_work_department`

La tabla incluye además:

- `created_at`: fecha de creación del registro.
- `updated_at`: fecha de la última actualización por upsert.

El upsert usa un índice único sobre la columna configurada en `POSTGRES_UPSERT_KEY`. Los registros sin clave se descartan y los duplicados de la misma corrida conservan la última versión.

## Auditoría

Cada carga PostgreSQL registra una fila en:

```sql
SELECT *
FROM hibob_etl_daily_scheduled_report.etl_run_history
ORDER BY started_at DESC;
```

La auditoría incluye estado, filas de origen, filas válidas, insertadas, actualizadas, descartadas, lotes y mensaje de error.

Los logs se escriben en consola y en:

```text
logs/hibob_etl_YYYYMMDD_HHMMSS.log
```

## Ejecución

```bash
python main.py
```

## Validación

```bash
pip install -r requirements-dev.txt
pytest -q
```
