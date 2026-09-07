# Fase 3 — Matriz de permisos ejecutada

`03-matriz-permisos.csv` · **309 filas** · 259 conformes · **50 no conformes** · 8 no auditables.

Generada por `scripts/audit_portal_matrix.py`. Ocho sujetos
(`anonimo`, `full_admin`, `gqm_member`, `subcontractor`, `sub_B`, `technical`,
`tech_de_sub_B`, `tech_independiente`) × superficie alcanzable × objetos
(`propio`, `ajeno`, `inexistente`).

## Lo que hace distinta a esta matriz

La del PR #116 tenía **un solo sujeto por rol de portal**. Sin un segundo sub, el objeto
«ajeno» no existe y un IDOR entre pares es invisible **por construcción**: no es que se
buscara y no apareciera, es que no había dónde mirar. Los 50 no conformes de aquí son casi
todos de la columna `ajeno`.

## Disciplina aplicada

- **Toda escritura se verifica releyendo la fila en la BD.** La columna `nota` lleva el
  estado real de la fila, no el código HTTP. En este proyecto un `POST /tasks/ {}` ya
  devolvió 201 con todo NULL (T-07).
- **Los conjuntos se enumeran.** Los listados se paginan hasta el final —`@paginate()`
  topa `limit` en 100 y rebana en Python— y se comparan por identificador, nunca por
  recuento.
- **El `esperado` sale de la Fase 1**, ratificada por el usuario.

### Correcciones al `esperado` durante la ejecución — declaradas

En la primera corrida salieron 118 no conformes. Al revisarlas, **68 eran errores míos al
derivar el `esperado`**, no defectos del sistema. Se corrigieron y se declaran aquí, porque
bajar un recuento de hallazgos sin explicar por qué es exactamente lo que hace inútil a una
auditoría:

| Corrección | Por qué |
|---|---|
| Un rol sin la acción debe recibir **403 del decorador** | Un técnico no tiene `subcontractor:read`; su 403 en `/subcontractors/` es correcto, no un hallazgo |
| Endpoints **lista-por-relación** vs **objeto-por-id** | `/tlactivity/job/<inexistente>` devuelve `200 []` legítimamente. En estos el veredicto lo da el **contenido**, no el código |
| **Denegación deliberada** documentada en el código | `/jobs/subcontractor/<ajeno>` → 403 lo argumenta `Job.py:832-833`; `/commission/member/<id>` lo cierra `Commission.py:213`; `/member/<id>`, `self_profile_guard` |
| `/jobs/subcontractor/<propio>` solo es «propio» para un sub | El id del path es un `SUBC`; el de un técnico nunca lo iguala (`Job.py:834`) |
| `/podio/items/<app_type>` → **no auditable** | Devuelve 500 a todos los roles por falta de credenciales de Podio. Aquí no se puede juzgar |

Ninguna corrección tocó las decisiones ratificadas en la Fase 1.

## Hallazgos

| ID | Sev | Endpoint(s) | Filas | Qué pasa |
|---|---|---|---|---|
| **P-01** | **S1** | `GET /technician/<id>` | 5 | Cualquier rol de portal lee la ficha de **cualquier** técnico: sus tareas, los jobs de su sub y **su documento de política IAM** |
| **P-02** | **S1** | `GET /technician/` | 5 | El listado devuelve **todos** los técnicos del sistema, sin scoping. Es la deuda que el PR #116 marcó «Fase B» — sigue viva |
| **P-03** | **S1** | `GET /attachments/`, `GET /attachments/<id>` | 10 | Los cinco sujetos de portal reciben **el corpus entero de adjuntos**, de cualquier job y cualquier sub |
| **P-04** | **S1** | `GET /tlactivity/{job,subcontractor,client,parent-mgmt-co}/<id>` | 20 | Cuatro rutas de timeline sin scoping: cualquier rol de portal lee la actividad de cualquier job, sub, cliente o gestora |
| **P-05** | **S1** | `GET /subcontractors/<id>`, `GET /subcontractors/` | 4 | Un sub lee la ficha completa de otro sub, con sus `orders`, sus `technicians` y las tareas de estos |
| **P-06** | **S2** | `GET /certificate/subcontractor/<id>`, `GET /certificate/` | 4 | Un sub lee los certificados de cumplimiento de otro sub |
| **P-07** | **S1** | `POST /tasks/` | 1 | Un sub crea una tarea y se la asigna a **un técnico de otro sub** → **201, y la fila queda escrita** con `ID_Technician=TEC60002`. Rompe R3 |
| **P-08** | **S1** | `PATCH /subcontractors/<propio>` | 1 | Un sub se fija a sí mismo `Gqm_compliance` y `Score` → **200, y persiste en BD**. Se autoaprueba el cumplimiento |

**50 filas, 8 hallazgos.** Todos verificados con evidencia enumerada; los dos de escritura,
además, releyendo la fila.

### Por qué P-01 es el más grave

Es la demostración más limpia de que el scoping de tareas se puede rodear. Sobre **la misma
tarea** `TSK60003`, propiedad del técnico de sub_B:

```
sub A → GET /tasks/TSK60003        → 404   ✅ el scoping funciona
sub A → GET /technician/TEC60002   → 200   🔴 y dentro viene TSK60003
```

`scope_tasks_statement` protege `/tasks/*`, pero `Technician.py:63-74` carga
`joinedload(Technician.tasks)` y lo vuelca sin comprobar pertenencia. La misma respuesta
trae `permissions[].Document`: **el documento de política IAM del objetivo**, es decir, el
mapa de lo que ese usuario puede hacer.

### Lo que sí funciona

No todo está roto, y decirlo importa tanto como lo demás:

- **R2 se cumple en el núcleo**: `/jobs/<ajeno>` y `/tasks/<ajeno>` devuelven **404** a los
  cinco sujetos de portal. Los controles negativos de la matriz **pueden fallar**, y no
  fallan.
- **R4 se cumple**: `POST /tasks/` como técnico → **403** en los tres técnicos, y la BD
  confirma que no se creó fila.
- **R5 se cumple**: `DELETE /tasks/<propia>` y `DELETE /jobs/<propio>` → **403** en los
  cinco sujetos, incluso sobre recurso propio. La fila sigue existiendo tras el intento.
- **Ambigüedad 7 ratificada**: retirar la asignación corta el acceso al instante (200 → 404).
- El **técnico independiente** opera con normalidad: su scope (`Tasks.ID_Technician == uid`)
  no depende de tener subcontratista.
- Las tres rutas que el decorador deja pasar por la semántica OR de `profile:update_own`
  (`/member/<id>`, `/commission/member/<id>`) están **cerradas en el handler**.

## Las 8 filas no auditables

`GET /podio/items/<app_type>` es una de las cuatro rutas **solo-JWT** de la aplicación:
alcanzable por cualquier autenticado sin comprobar permiso. En este entorno devuelve 500
por falta de credenciales de Podio, así que **no se puede juzgar aquí** si filtra algo. Se
reporta como no auditada, no como aprobada, y va al `HANDOFF`.
