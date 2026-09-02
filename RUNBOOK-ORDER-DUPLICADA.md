# PAR6095 — ORD68994 / ORD69726 **no eran un duplicado**

> **NO BORRES NINGUNA DE LAS DOS FILAS.** Este fichero fue durante una semana un
> runbook para consolidarlas. Lo que decía era falso, y ejecutarlo habría roto un
> job cerrado y cobrado. Se conserva como registro de qué se creyó, por qué, y
> qué lo desmintió.

Medido contra producción el **2-sep-2026**: BD por el MCP `gqm-prod-readonly`,
Podio con `scripts/leer_item_podio.py` (solo lectura).

---

## Lo que se creía

Dos Orders en el mismo slot `(job_podio_id, tech_field)` — el único caso en
9.801 orders — inflando el agregado del job:

```
job_podio_id 3304340068  →  PAR6095 (PAR, 2026)
tech_field   tech-1-ptl-original-pricing
ORD68994 = 110      ORD69726 = 330
```

| | ORD68994 | ORD69726 |
|---|---|---|
| Title | PO-PAR6095-**0369** | PO-PAR6095-**0363** |
| Formula / Adj_formula | 110 | 330 |
| Subcontratista | SUBC60341 | SUBC60341 (el mismo) |
| Notes | Unit 1011 · Unit 110 · Unit 1107 | **idénticas** |
| EstimateCost | EST60300 «Unit 315» (110/150) | ninguno |
| ChangeOrder | 0 | 0 |

La conclusión era que había que borrar una y dejar el job en 550.

## Lo que dice Podio

`tech-1-ptl-original-pricing` resultó ser un campo **`money`**, no
`calculation` — o sea que el 440 lo escribió una persona, no una fórmula. Y el
job está **pagado**:

```
job-status                Paid
check-amount-payment-1    440.0000   ← Tech 1 · Payment 1, PAGADO
check-amount-payment-1-2  220.0000   ← Tech 2 · Payment 1
total-paid                  0.0000   ← «Total (Left to) Pay Tech 1»
payment-received-1        910.0000   ← cobrado al cliente
amount-left-to-collect      0.0000
```

## Cuadra al céntimo, y sólo cuadra si ORD68994 es real

| | builder | client |
|---|---|---|
| PO-0363 — Units 1011 · 110 · 1107 | 330 | 455 |
| PO-**0369** — Unit 315 (EST60300) | **110** | **150** |
| **Tech 1** | **440** | 605 |
| PO-0367 — Units 1207 · 1110 (Tech 2) | 220 | 305 |
| **Total** | **660** | **910** |

Los cuatro campos derivados de Podio confirman esa columna:

```
gqm-formula-total-cost         660.0000
gqm-target-sold-price          910.0000
gross-profit-margin              0.2747   = (910-660)/910
gqm-pricing-return-premium-in  250.0000   = 910-660
```

Si ORD68994 fuese un duplicado, el coste sería 550 y el margen 0.3956. Y los 150
de «Unit 315» están **dentro de los 910 que el cliente ya pagó**.

**Son dos POs reales del mismo subcontratista que juntos son los 440 que cobró.**

Las Notes idénticas —lo que hizo pensar en un duplicado— son un artefacto: en
Podio hay **un solo campo de notas por slot** (`description` para tech-1, ver
`ORDER_PAR_FIELDS`), así que dos POs en el mismo slot comparten texto por fuerza.

---

## Cómo entró el segundo PO sin que nadie lo decidiera

Que los dos sean reales no significa que el camino fuera correcto. `tlactivity`
de PAR6095:

```
2026-08-18 18:56:18   MEM60012   Order deleted   PO-PAR6095-0363
2026-08-18 19:03:10   MEM60012   Order created   PO-PAR6095-0363   → ORD69726
```

Siete minutos, una persona, la misma PO. El DELETE **pre-#129** emitía `[]` sin
mirar si quedaba otra Order en el slot, así que vació la casilla de Podio con
ORD68994 todavía dentro; el CREATE consultó el slot con `is_primary_taken`
(`order_changeorder_mappers.py:160`), que **mira la casilla de Podio y no la
BD**, la vio libre y pasó.

O sea: el guard no opinó. Que el resultado fuera correcto es suerte, no diseño.

**`created_at` no sirve para datar nada aquí:** 9.599 de las 9.801 orders
comparten el instante `2026-08-11T03:20:03.808Z`, de un backfill masivo.

---

## Qué se hizo

1. **`ux_order_job_slot` retirado de `e7a3c9d21f80`.** Prohibía este registro.
   La revisión sólo crea ya `ux_change_order_job_slot` (0 duplicados en 1.285
   filas). Producción estaba en `b2r12adjuntos` y la revisión no se había
   aplicado nunca, así que se editó en sitio sin revisión nueva.
2. **`POST /order` comprueba el slot contra la BD** además de contra Podio
   (`Order.py`, `_slot_ocupado`), y traduce el choque del índice a un 409 en vez
   de un 500. Cierra la vía por la que entró el segundo PO sin decisión humana.
   Ojo: **hoy impide crear un segundo PO en un slot ocupado**, que es justo lo
   que este job tiene. Si la respuesta a la pregunta de abajo es «sí se puede»,
   este guard hay que replantearlo con ella.
3. `upsert_order` conserva su degradación savepoint + `IntegrityError` → UPDATE.
   Sin el índice es código inalcanzable; se deja por si vuelve.

## Qué queda abierto

- **¿Varios POs por slot son válidos en el negocio?** Es la pregunta que decide
  si `ux_order_job_slot` puede volver y si el guard de `create_order` está bien
  planteado. PAR tiene cuatro slots y aquí `tech-3-formula` / `tech-4-formula`
  están libres, así que la alternativa —un PO por slot, moviendo Unit 315 a
  tech-3— es viable, pero exige escribir en Podio sobre un job pagado y enlazar
  SUBC60341 a `technician-3`.
- **Quién puso el 440 y cuándo.** No está medido. Si resultara escrito en agosto
  *reaccionando* al segundo PO, todo lo de arriba habría que releerlo. Lo
  contesta `GET /item/3304340068/revision`. Los 910 con Week Assigned 5/14–5/18
  apuntan a que Unit 315 estaba desde mayo, pero eso es inferencia, no medida.

## Lecciones, que son el motivo de conservar esto

- **La BD sola no distingue un duplicado de dos registros legítimos.** Aquí todo
  —notas idénticas, mismo sub, un `EstimateCost` que no encajaba— apuntaba a
  corrupción, y la BD no tenía cómo desmentirlo. Lo desmintió Podio, que es
  donde está el dinero.
- **`created_at` de un backfill no data nada**, y se usó para decidir cuál fila
  era «la vieja».
- **Un índice único es una afirmación sobre el negocio**, no sólo sobre el
  esquema. Éste afirmaba «un PO por técnico y job» sin que nadie lo hubiera
  confirmado, y el primer contraejemplo estaba ya cobrado.
