# Fase 1 — Contrato y spec derivada

Este documento es **la única fuente del `esperado`** de la Fase 3. Sale de las respuestas
del usuario, no del comportamiento observado. Cambiarlo para que la matriz dé verde es la
prohibición explícita de la §7 del encargo.

## 1. Superficie real de la aplicación

Generada desde `app.url_map` con `scripts/audit_rbac_map.py`, que además introspecciona
los *closures* de los decoradores para recuperar la acción exigida por cada ruta.

| Mecanismo | Rutas (par método×ruta) |
|---|---|
| `protect_blueprint` (verbo → `recurso:acción`) | 195 |
| `require_permission` | 115 |
| público (sin JWT) | 14 |
| **solo-JWT (autenticado, sin comprobar permiso)** | **4** |
| `require_role` + `require_permission` | 2 |
| **Total** | **330** |

> Corregido durante la auditoría: la copia de `public_prefixes` de
> `audit_rbac_map.py:23-27` estaba desincronizada con `main.py:158` — le faltaba
> `/webhook/podio/dead_letter_cron`. Sin ese arreglo, la clasificación
> `public`/`jwt-only` mentía sobre una ruta.

### Las 4 rutas solo-JWT

Cualquier usuario autenticado las alcanza, incluidos los dos roles de portal, **sin que
se compruebe ningún permiso**:

```
GET /auth/can                  (por diseño: es el endpoint que responde «¿puedo?»)
GET /auth/me                   (por diseño: la ficha propia)
GET /podio/items/<app_type>    ← ni por diseño ni documentado
GET /static/<path:filename>
```

`GET /podio/items/<app_type>` se audita en la Fase 3 como ruta alcanzable por portal.

## 2. Superficie alcanzable por un rol de portal

Evaluando las políticas IAM realmente sembradas (`subcontractor-portal`,
`technical-portal`) contra la acción exigida por cada ruta:

| | Rutas |
|---|---|
| Alcanzables por el **subcontratista** | 46 |
| Alcanzables por el **técnico** | 33 |
| Unión (superficie de portal) | **46 de 330** |

Por recurso: `/jobs` 12 · `/subcontractors` 7 · `/tasks` 6 · `/tlactivity` 5 ·
`/attachments` 3 · `/certificate` 3 · `/technician` 3 · `/member` 2 · `/skills` 2 ·
`/chat` 1 · `/commission` 1 · `/jobs_excel` 1.

### Un detalle del evaluador que ensancha la superficie

`require_permission` usa **semántica OR** sobre la lista de acciones
(`routes_protection.py:276-279`). Como ambas políticas de portal incluyen
`profile:update_own`, los roles de portal **pasan el decorador** de rutas pensadas para el
autoservicio de un *member*:

```
GET   /commission/member/<id>   acciones=[commission:read, commission:read_own, profile:update_own]
GET   /member/<id>              acciones=[member:read, profile:update_own]
PATCH /member/<id>              acciones=[member:update, profile:update_own]
```

Las tres están **cerradas en el handler**, no en el decorador: `Commission.py:213` y
`self_profile_guard` exigen `role == target_type and id == target_id`, y un rol de portal
nunca es `member`. Se verifica en la Fase 3. Queda anotado como fragilidad: el decorador
no es la defensa, y quien lea solo el decorador concluirá lo contrario.

## 3. Las 10 ambigüedades — resueltas por el usuario

Cada una se midió primero contra el sistema y se presentó con su evidencia; la columna
«decisión» es la respuesta del usuario y es lo que fija el `esperado`.

| # | Pregunta | Comportamiento medido hoy | **Decisión** | Conforme |
|---|---|---|---|---|
| 1 | ¿El sub ve todos los técnicos? | `GET /technician/` → 200 con `TEC60001, TEC60002, TEC60003` (todos) | **Solo los suyos** | ❌ |
| 2 | ¿Reasigna una tarea de admin? ¿Reabre? | Reasigna **a un técnico ajeno** (200, persistido); cierra y reabre (200) | **Reasignar sí, pero solo a los suyos**; reabrir permitido | ❌ |
| 3 | ¿Ve el técnico el precio? ¿Y el sub? | Técnico **no** (proyección `JobReadBasic`); sub **sí**: `Gqm_formula_pricing`, `Gqm_target_return`, `Acc_receivable`, `Gqm_final_sold_pricing` | **El sub no debe verlo** | ❌ |
| 4 | ¿Ve el sub cliente y dirección? | `Project_location` completo **y** objeto `client` expandido | **Dirección sí, contacto no** | ❌ |
| 5 | ¿Ve el sub a otros subs del job? | Ficha completa de sub_B: `Email_Address`, `Phone_Number`, `Notes`, `Score`, `Gqm_compliance`, `ID_Role`, + `orders` y `technicians` anidados | **Nada** | ❌ |
| 6 | ¿Edita el sub el job? | `PATCH /jobs/<propio>` → **403** | No | ✅ |
| 7 | ¿Pierde el histórico al desasignarlo? | Asignado → 200; desasignado → **404** inmediato | **Correcto, ratificado** | ✅ |
| 8 | ¿Opera el técnico independiente? | `GET /tasks/` → 200 con su tarea | Sí, debe operar | ✅ |
| 9 | ¿Adjuntos entre sub y su técnico? | Ambos sentidos 200 — **pero ven también los de sub_B** | **Visibilidad mutua en el equipo, nada de otros subs** | ❌ |
| 10 | ¿Sub `Inactive` / sin compliance? | El sub se fijó a sí mismo `Gqm_compliance='APROBADO-POR-MI-MISMO'`, `Score=99.0` — **verificado releyendo la fila** | No debe poder | ❌ |

**7 de 10 no conformes.** Cada una genera hallazgo en la Fase 3 (`P-nn`) o la Fase 4 (`F-nn`).

## 4. Las reglas duras R1–R6 como filas de matriz

| Regla | Prueba positiva | Prueba negativa (obligatoria) |
|---|---|---|
| **R1** admin asigna | admin asigna job a sub → el sub lo ve | — |
| **R2** solo lo asignado | sub ve su job | sub pide job ajeno por id → **404** |
| **R3** sub crea tareas para *sus* técnicos en *sus* jobs | sub crea tarea en job propio para técnico propio → 201 | job ajeno → 403/404 · **técnico de otro sub → 403/404** |
| **R4** técnico no crea | técnico actualiza estado de tarea propia → 200 | `POST /tasks/` como técnico → **403**, y sin botón «New Task» en su UI |
| **R5** ni sub ni técnico borran | — | `DELETE /tasks/<id>` y `/jobs/<id>` → **403** incluso sobre recurso propio; y ningún `PATCH` que ponga `deleted=true` |
| **R6** entran y trabajan | login → landing propia → completa su trabajo sin callejón sin salida | — |

## 5. Convención 404 vs 403

Regla declarada en el código (`Job.py:506-507`): *404 cuando revelar la existencia es la
fuga; 403 cuando el identificador ya lo conoce quien pregunta*. Está aplicada de forma
**deliberada pero desigual** — `Job.py:832-833` argumenta por escrito por qué
`/jobs/subcontractor/<id>` devuelve 403 y no 404.

`esperado` para esta auditoría: **404 en todo objeto ajeno pedido por id**, salvo donde el
identificador lo aportó el propio llamante sobre sí mismo. Las divergencias se reportan
como inconsistencia, con su código real, no como fallo de seguridad automático.

## 6. Supuestos declarados

- La BD es **virgen y sembrada**: sirve para auditar el *código*, que es lo que decide los
  permisos, no para reproducir formas de datos de producción. Todo hallazgo que dependa de
  la forma del dato queda marcado como tal.
- `esperado` sale de esta tabla. Si un valor cambia, se cambia **aquí** y se vuelve a
  ejecutar la matriz; nunca al revés.
