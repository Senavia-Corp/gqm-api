# Runbook — consolidar ORD68994 / ORD69726 (PAR6095)

**Esto lo ejecuta una persona.** Hay dinero de por medio, la decisión de cuál
fila sobrevive no es mecánica, y ninguno de los pasos es reversible sin trabajo.

Medido contra producción el **2-sep-2026** (MCP `gqm-prod-readonly`). Vuelve a
medirlo antes de tocar nada: si los números no coinciden, para y averigua por qué.

---

## Qué pasa

Dos Orders ocupan el mismo slot `(job_podio_id, tech_field)`:

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

`recalculate_job_fields` recorre **todas** las orders del job y acumula
`Adj_formula` en `Tech_formula_pricing`:

```
suma de las 3 orders del job hoy : 660   (jobs.Tech_formula_pricing = 660)
sin ORD68994                     : 550
```

Es el **único** slot duplicado en 9.801 orders. `change_order` no tiene ninguno
en 1.285 filas.

---

## La causa raíz NO es la carrera de `upsert_order`

Esto estuvo mal documentado hasta el 2-sep-2026, aquí y en el docstring de
`e7a3c9d21f80`. `tlactivity` de PAR6095 lo desmiente:

```
2026-08-18 18:56:18   MEM60012   Order deleted   PO-PAR6095-0363
2026-08-18 19:03:10   MEM60012   Order created   PO-PAR6095-0363   → ORD69726
```

Siete minutos, una persona, la misma PO. **Eso no es una carrera.** Lo que pasó:

1. El DELETE **pre-#129** emitía `[]` a Podio sin mirar si quedaba otra Order en
   el slot, así que **vació la casilla** `tech-1-ptl-original-pricing` mientras
   ORD68994 seguía en la BD ocupándola.
2. Siete minutos después el CREATE consultó el slot con `is_primary_taken`
   (`order_changeorder_mappers.py:160`), que **mira la casilla de Podio, no la
   BD**. La vio vacía, la dio por libre, y coló la segunda fila.

O sea: el duplicado lo produjo el desfase Podio↔BD que el propio PR #129 vino a
cerrar. La carrera check-then-insert de `upsert_order` es un bug real y sigue
justificando el índice, pero **no es lo que pasó aquí**.

**`created_at` no sirve para datar nada:** 9.599 de las 9.801 orders comparten el
instante `2026-08-11T03:20:03.808Z` — un backfill masivo. ORD68994 es un artefacto
de ese backfill, no una fila «vieja». Sólo ORD69726 tiene fecha real. Y como el
backfill importó los dos POs desde Podio, **es probable que el duplicado ya
viniera de Podio**: razón de más para mirar Podio antes de borrar.

---

## Lo que los datos sugieren, y por qué aun así lo decides tú

La regla de la casa es `Formula = Σ Builder_cost` de los EstimateCost enlazados
(`job_calculator.py:315`, `recalculate_order_formulas`), y se cumple en 15 de las
16 orders con costes. En la hermana de este mismo job cuadra exacta: ORD68973
(tech-2) tiene EST60270 (90) + EST60271 (130) = **220** = su `Formula`.

Las notes de las dos filas en litigio son **idénticas** y describen tres unidades:

```
Unit 1011 - 1/1 Completed 5/14 (90/125)
Unit 110  - 2/2 Schedule  5/20 (110/150)
Unit 1107 - 3/2 Completed 5/18 (130/180)
```

`90 + 110 + 130 = 330`, que es exactamente la `Formula` de **ORD69726**. La de
ORD68994 (110) coincide solo con la segunda unidad. Además, `PO-PAR6095-0369`
**no tiene ni un solo evento de creación en `tlactivity`**: en este job sólo
0363 y 0367 tienen ciclo de vida registrado.

**Pero ORD68994 es la que tiene el EstimateCost**, y no encaja con esas notes:

```
EST60300 · ID_Order=ORD68994 · Cost_type=Subcontractor · Status=NULL
          Title="Unit 315" · Builder_cost=110 · Client_price=150
```

«Unit 315» no aparece en las notes de ninguna de las dos — aunque su par
`110/150` es idéntico al de la línea «Unit 110». Así que **no está claro** si
EST60300 pertenece a este trabajo, a otro, o es residuo. Eso hay que mirarlo en
Podio y con quien llevara el job, no deducirlo desde la BD.

Ojo con un espejismo: existen EST60261/62/63 con `Builder_cost` 90/110/130 —
justo las tres unidades— y sin `ID_Order`. Tentador, pero **el 82,6% de los 201
estimate_cost están huérfanos**, así que por sí solo no prueba nada.

---

## El 440 de Podio no lo escribió esta API

Leído del item el 2-sep-2026: `tech-1-ptl-original-pricing = 440.0000`
(= 110 + 330) y `tech-2-ptl-original-pricing = 220.0000`.

**Ningún mapper suma por slot.** `map_order_create_to_podio`
(`order_changeorder_mappers.py:177`) y `map_order_patch_to_podio` (`:241`)
**reemplazan** la casilla, y en `src/` no hay un solo sitio que agregue por
`tech_field`. `recalculate_job_fields` tampoco toca las casillas tech-N: escribe
`Tech_formula_pricing`, que es del job.

O sea que 440 salió de otro sitio. **Hay que saber de cuál antes de escribir
nada ahí**, porque el paso «corregir el campo en Podio desde la UI» supone que
el campo es editable, y eso está sin verificar:

```bash
python3 scripts/leer_item_podio.py 3304340068 --tipo PAR --anio 2026 --json reports/par6095_podio.json
```

Solo lectura (login + `GET /admin/podio/parity`). Da el `type` y los `values` de
cada casilla `tech-*`:

- **`calculation`** → Podio la calcula sola (típicamente sumando los POs
  enlazados). No se puede escribir ni a mano ni por API: **el paso 4 de abajo es
  imposible tal cual** y lo que se corrige son los enlaces de PO.
- **`number` / `money`** → alguien escribió 440. Averigua quién antes de pisarlo.
- **Si Podio enlaza los DOS POs a tech-1** → no es corrupción nuestra: es un dato
  real que el índice único va a prohibir. **Para y replantea el índice**, no
  borres la fila.

---

## Antes de empezar

- [x] **PR #129 desplegado en producción.** Verificado el 2-sep-2026: producción
      sirve `f0db2d8` (tip de `main`, READY/PROMOTED), y tanto `cfd9360` (#129)
      como `a524086` (#130) son ancestros. Sin #129,
      `map_order_delete_to_podio` emitiría `[]` al borrar una de las dos filas y
      se llevaría por delante el importe de la que sobrevive.
- [ ] Correr `scripts/leer_item_podio.py` (arriba) y **decidir con eso delante**.
- [ ] `PODIO_READONLY=true` en el Vercel de producción durante la ventana, **si
      se elige la vía A**. Hoy la variable **no existe**: hay que crearla. Es la
      única capa que corta escrituras salientes pase lo que pase
      (`podio_base_services.py:74`, antes de la whitelist y de tocar la red).
- [ ] Exportar a fichero, fuera de la BD:
      - las dos filas completas de `"order"`
      - `EST60300` completa
      - el volcado del item de Podio (lo deja el script con `--json`)

---

## Dos vías, y hay que elegir una

**Vía A — como estaba escrito este runbook.** `PODIO_READONLY=true`, borrar con
`sync_podio=false`, corregir la casilla a mano en la UI. Cero escrituras
automáticas. **Contra:** durante la ventana cada PATCH de `/estimate` acumula
filas `PodioFailedSync` de tipo `auto_sync_to_podio` que un `/resync` posterior
puede reproducir — `sync_job_to_podio` se traga la `EscrituraPodioBloqueada` en
su `except Exception` (`podio_job_sync.py:106`) y el HTTP sigue devolviendo 200.

**Vía B — dejar que #129 haga su trabajo.** Sin `PODIO_READONLY`, borrar con
`sync_podio=true&year=2026`: `map_order_delete_to_podio` (`:300-315`) busca la
superviviente y escribe su `Formula` en la casilla en la misma operación. Es el
caso exacto para el que se escribió #129, y con exactamente dos filas el
`.first()` sin `ORDER BY` es determinista. **Contra:** es una escritura
automática a Podio de producción.

Si el script dice que la casilla es `calculation`, **ninguna de las dos sirve tal
cual**: hay que arreglar los enlaces de PO en Podio.

---

## Pasos

1. **Decidir cuál sobrevive** con el volcado de Podio y el histórico del job
   delante. Los datos de la BD apuntan a ORD69726, pero EST60300 cuelga de
   ORD68994 y Podio manda sobre los dos.

2. **Decidir qué pasa con EST60300.** Si sobrevive ORD69726, ese EstimateCost se
   queda huérfano o hay que reapuntarlo. `delete_order` lo desengancha **solo**,
   en la misma sesión, con `ID_Order = None` (`Order.py:652-660`) — **no** emite
   ningún `PATCH /estimate/<id>`; este runbook decía lo contrario hasta el
   2-sep-2026.

   > El aviso sigue valiendo **si haces el PATCH a mano**:
   > `PATCH /estimate/<id>` llama a `sync_job_to_podio` incondicionalmente
   > (`EstimateCost.py:180` y `:195`; el POST en `:126`, el DELETE en `:228`).
   > `sync_podio` no existe en ese fichero — `grep -c` da 0. No te fíes de
   > `sync_podio=false` para nada que pase por ahí.

3. **Borrar la fila perdedora** por la vía elegida.

   Ojo aunque aquí no aplique: `Order.change_orders` cascadea `delete-orphan`
   (`OrderModel.py:44`) y la negativa por ChangeOrders vive **dentro** del
   `if sync_podio:` (`Order.py:613`), así que con `sync_podio=false` se
   borrarían ChangeOrders en silencio. PAR6095 tiene **0**.

4. **Cuadrar la casilla en Podio.** Vía A: a mano desde la UI, nunca por API
   (con `PODIO_READONLY` no funcionaría, y apagarlo abre la puerta a escrituras
   de otros procesos). Vía B: ya la escribió el DELETE; sólo hay que comprobarla.

5. **Comprobar que el job cuadra:**

   ```sql
   SELECT sum("Adj_formula") FROM "order" WHERE job_podio_id = '3304340068';
   -- debe dar 550 si sobrevive ORD69726
   SELECT "Tech_formula_pricing" FROM jobs WHERE podio_item_id = '3304340068';
   ```

   Y forzar `recalculate_and_apply` sobre PAR6095 para que los agregados del job
   se rehagan.

6. **Solo entonces**, correr la migración:

   ```bash
   alembic upgrade head
   ```

   Aplica **dos** revisiones pendientes: `e7a3c9d21f80` (estos índices) y
   `f8b4d2e60a17`. Producción está en `b2r12adjuntos`; `a1t11podio` y
   `b2r12adjuntos` ya se aplicaron — este runbook listaba tres hasta el
   2-sep-2026.

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

   Comprobar de paso que siguen los tres índices `CONCURRENTLY` de siempre
   (`ix_change_order_job_podio_id`, `ix_financial_document_id_jobs`,
   `ix_order_job_podio_id`): el autogenerate propone borrarlos en cada revisión.

8. Apagar `PODIO_READONLY` si se encendió.

---

## Qué queda protegido después

- Una segunda Order en el mismo slot ya no se puede insertar.
- `upsert_order` / `upsert_change_order` degradan a UPDATE en vez de reventar
  (savepoint + `except IntegrityError`, `sync_orders.py:147` y `:249`), que es lo
  que el upsert quería hacer desde el principio. Ya está desplegado desde #130;
  hoy es código inalcanzable porque el índice todavía no existe.
- `POST /order` comprueba el slot **contra la BD** además de contra Podio, y
  traduce el choque del índice a un **409** con el mismo mensaje que ya daba
  `is_primary_taken`, en vez de un 500 crudo (`Order.py`, `_slot_ocupado`). Es el
  agujero exacto por el que entró este duplicado.
