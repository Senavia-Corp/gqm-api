# Fase 4 — Fuga de datos a nivel de campo

`04-fugas-de-datos.csv` · **690 filas**. Generado por `scripts/audit_field_leaks.py`.

La Fase 3 dice **si entras**. Esta dice **qué te llevas**.

## El mecanismo que se mide

`src/utils/relationships.py::add_relationships` hace `model_dump(mode="json")` de **todas
las columnas** de cada relación expandida y solo redacta
`{"Password","password","hashed_password","pass"}`. No hay proyección por rol. La superficie
de fuga de una ruta **es la unión de todas las columnas de todas las relaciones que expande**
— por eso el dato sensible está tres niveles abajo, no en el primer nivel del objeto.

## Dos detectores

1. **Vocabulario prohibido** — 25 rutas de clave que un rol de portal no debe recibir nunca.
2. **Centinelas** — el sembrado puso valores reconocibles con el prefijo de su dueño.
   Encontrar `B-NOTA-INTERNA-GQM` en una respuesta a sub A nombra a la vez **el campo y la
   víctima**. Es prueba directa, no indicio; y sin centinelas un campo NULL sería
   indistinguible de un campo filtrado.

> **Un fallo del propio arnés, corregido y declarado.** El primer barrido emitía solo las
> rutas *hoja*, así que cualquier campo prohibido cuyo valor fuese un objeto quedaba
> invisible — y el peor de todos, `permissions[].Document` (la política IAM), es
> exactamente eso. El escáner reportó **0 fugas de política IAM y era falso**. Ahora emite
> también las claves intermedias: son 10 filas reales. Un detector que no puede ver lo que
> busca da un verde que no significa nada.

## Hallazgos

| ID | Sev | Dónde | Qué se lleva |
|---|---|---|---|
| **F-01** | **S1** | `GET /technician/<id>`, `GET /technician/` | **El documento de política IAM** del objetivo: `permissions[].Document`, con su `Statement` completo — el mapa exacto de lo que ese usuario puede hacer. 10 filas. |
| **F-02** | **S1** | `GET /technician/*`, `GET /tasks/<propia>`, `GET /attachments/`, `GET /tlactivity/job/*` | **El bloque financiero completo de los jobs**, vía `subcontractor.jobs[]`: `Gqm_formula_pricing`, `Gqm_target_return`, `Gqm_final_sold_pricing`, `Acc_receivable`, `Gqm_premium_in_money`, `Ptl_gc_fee`, `Bldg_dept_fees`, `Estimated_rent`, `Estimated_material` y 8 más. |
| **F-03** | **S1** | todas las anteriores | **La proyección del técnico es puenteable.** A un técnico `/jobs/` le oculta el precio con `JobReadBasic`, pero recibe **50 campos financieros** por `/technician/`, `/tasks/`, `/attachments/` y `/tlactivity/`. La protección existe en una ruta y en ninguna otra. |
| **F-04** | **S2** | `GET /technician/*`, `GET /subcontractors/*` | Datos comerciales de otros subcontratistas: `Score`, `Gqm_compliance`, `Notes`. |
| **F-05** | **S2** | `GET /subcontractors/<ajeno>`, `GET /attachments/` | Centinelas del mundo ajeno: `Project_location`, `Po_wtn_wo`, `Additional_detail` — dirección de obra, orden de compra y notas internas de jobs de otro sub. |
| **F-06** | **S3** | varias | `podio_item_id` en 6 rutas: identificadores internos de Podio expuestos al portal. |

## F-03 es el hallazgo estructural

Vale la pena verlo con precisión, porque explica por qué arreglar `/jobs/` no basta:

```
técnico → GET /jobs/<propio>        → 200, SIN campos financieros   ✅ JobReadBasic proyecta
técnico → GET /technician/<quien sea> → 200, CON los 17 Gqm_*        🔴 nadie proyecta
técnico → GET /tasks/<propia>       → 200, CON los 17 Gqm_*          🔴
técnico → GET /attachments/         → 200, CON los 17 Gqm_*          🔴
```

`serialize_job()` (`Job.py:57-68`) es **la única proyección que existe en el código**, y
solo la usan las rutas de `/jobs`. Cualquier otra ruta que expanda una relación con `job`
dentro entrega el objeto entero. La protección del técnico no es una regla de negocio
aplicada: es una propiedad de una sola ruta.

## Verificación de la ruta más citada

```
GET /technician/TEC60002  como subcontractor (sub A)  → 200
claves de primer nivel: Email_Address, ID_Technician, Location, Name, Phone_Number,
                        Type_of_technician, attachments, permissions, subcontractor, tasks
permissions[0].Document = {"Statement":[{"Action":["job:read_basics","tasks:read",
    "tasks:read_own","tasks:update","technician:read","skill:read","attachment:read",
    "attachment:read_technicians","profile:update_own"],"Effect":"Allow","Resource":["*"]}]}
```

## Lo que no filtra

- **`Password` no aparece nunca.** `SENSITIVE_FIELDS` de `relationships.py:91-96` cumple su
  función en todas las rutas barridas.
- `GET /jobs/` y `GET /jobs/<id>` **al técnico** no llevan bloque financiero: la proyección
  funciona donde está puesta.
- `GET /auth/me` solo expone `podio_item_id` del propio sujeto — dato propio, severidad baja.
