# Runbook — consolidar ORD68994 / ORD69726 (PAR6095)

**Esto lo ejecuta una persona.** Hay dinero de por medio, la decisión de cuál
fila sobrevive no es mecánica, y ninguno de los pasos es reversible sin trabajo.

Medido contra producción el **25-ago-2026**. Vuelve a medirlo antes de tocar
nada: si los números no coinciden, para y averigua por qué.

---

## Qué pasa

`upsert_order` es check-then-insert sin lock y la tabla no tenía restricción, así
que dos entregas del mismo evento de Podio pudieron crear dos filas en el mismo
slot `(job_podio_id, tech_field)`.

```
job_podio_id 3304340068  →  PAR6095 (PAR, 2026)
tech_field   tech-1-ptl-original-pricing
```

| | ORD68994 | ORD69726 |
|---|---|---|
| Formula / Adj_formula | **110** | **330** |
| Subcontratista | SUBC60341 | SUBC60341 (el mismo) |
| Title | PO-PAR6095-**0369** | PO-PAR6095-**0363** |
| Notes | Unit 1011 · Unit 110 · Unit 1107 | **idénticas** |
| EstimateCost colgando | **1 — EST60300** | 0 |
| ChangeOrder colgando | 0 | 0 |

`recalculate_job_fields` recorre **todas** las orders del job y las acumula:

```
suma de las 3 orders del job hoy : 660
sin ORD68994                     : 550
```

Es el **único** slot duplicado en 9.729 orders. `change_order` no tiene ninguno
en 1.283 filas.

---

## Lo que los datos sugieren, y por qué aun así lo decides tú

Las notes de las dos filas son **idénticas** y describen tres unidades:

```
Unit 1011 - 1/1 Completed 5/14 (90/125)
Unit 110  - 2/2 Schedule  5/20 (110/150)
Unit 1107 - 3/2 Completed 5/18 (130/180)
```

`90 + 110 + 130 = 330`, que es exactamente la `Formula` de **ORD69726**. La de
ORD68994 (110) coincide solo con la segunda unidad.

**Pero ORD68994 es la que tiene el EstimateCost**, y no encaja con esas notes:

```
EST60300 · ID_Order=ORD68994 · Cost_type=Subcontractor · Status=NULL
          Title="Unit 315" · Builder_cost=110 · Client_price=150
```

«Unit 315» no aparece en las notes de ninguna de las dos. Así que **no está
claro** si EST60300 pertenece a este trabajo, a otro, o es residuo. Eso hay que
mirarlo en Podio y con quien llevara el job, no deducirlo desde la BD.

---

## Antes de empezar

- [ ] **El PR #129 tiene que estar desplegado en producción.** Sin él,
      `map_order_delete_to_podio` emite `[]` a Podio al borrar una de las dos
      filas y **se lleva por delante el importe de la que sobrevive**. Comprueba
      que `main` incluye el commit y que el deploy de `Production – gqm-api`
      está en `success`.
- [ ] `PODIO_READONLY=true` **encendido en el Vercel de producción** durante toda
      la ventana. Es la única capa que corta escrituras salientes pase lo que
      pase.
- [ ] Exportar a fichero, fuera de la BD:
      - las dos filas completas de `"order"`
      - `EST60300` completa
      - la **revisión del item Podio `3304340068`** (`GET /item/3304340068`)

---

## Pasos

1. **Decidir cuál sobrevive** mirando el item en Podio y el histórico del job.
   Los datos de arriba apuntan a ORD69726, pero EST60300 cuelga de ORD68994.

2. **Decidir qué pasa con EST60300.** Si sobrevive ORD69726, ese EstimateCost se
   queda huérfano o hay que reapuntarlo. `delete_order` desengancha los
   EstimateCost con un `PATCH /estimate/<id>` — y ojo:

   > **`PATCH /estimate/<id>` llama a `sync_job_to_podio` incondicionalmente**
   > (`EstimateCost.py:127` y `:136`). `sync_podio` no aparece en ese fichero.
   > No te fíes de `sync_podio=false` para nada que pase por ahí.

   Por eso el punto de `PODIO_READONLY` de arriba no es opcional.

3. **Borrar la fila perdedora** con `sync_podio=false`.

4. **Corregir el campo en Podio DESDE LA UI, no por API.** El valor correcto es
   el de la superviviente. Hacerlo por API con `PODIO_READONLY` encendido no
   funcionaría, y apagarlo abre la puerta a escrituras de otros procesos.

5. **Comprobar que el job cuadra:**

   ```sql
   SELECT sum("Adj_formula") FROM "order" WHERE job_podio_id = '3304340068';
   -- debe dar 550 si sobrevive ORD69726
   ```

   Y forzar `recalculate_and_apply` sobre PAR6095 para que los agregados del job
   se rehagan.

6. **Solo entonces**, correr la migración:

   ```bash
   alembic upgrade head
   ```

   Aplica tres revisiones pendientes: `a1t11podio`, `b2r12adjuntos` (el rescate
   de los adjuntos de agosto, que lleva sin correr desde el 23-ago) y
   `e7a3c9d21f80` (estos índices).

   - **Cadena de conexión DIRECTA, no la del pooler.** Los `CREATE INDEX
     CONCURRENTLY` fallan a través de PgBouncer.
   - Si quedara algún duplicado, la migración **aborta en seco** con la lista.
     Eso es deliberado: forzarla dejaría un índice `INVALID`.

7. **Verificar `indisvalid`** — este paso no es opcional:

   ```sql
   SELECT c.relname, i.indisvalid
     FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
    WHERE c.relname IN ('ux_order_job_slot', 'ux_change_order_job_slot');
   ```

   Los dos deben dar `TRUE`. Si alguno da `FALSE`, el `CONCURRENTLY` se cortó a
   medias: `DROP INDEX CONCURRENTLY <nombre>;` y repetir. Un índice `INVALID`
   **no impide duplicados** — es creerse protegido sin estarlo, que es peor que
   no tenerlo. Y como la sentencia lleva `IF NOT EXISTS`, un segundo intento lo
   daría por bueno sin arreglarlo.

8. Apagar `PODIO_READONLY` en producción.

---

## Qué queda protegido después

- Una segunda Order en el mismo slot ya no se puede insertar.
- `upsert_order` / `upsert_change_order` degradan a UPDATE en vez de reventar
  (savepoint + `except IntegrityError`), que es lo que el upsert quería hacer
  desde el principio.
