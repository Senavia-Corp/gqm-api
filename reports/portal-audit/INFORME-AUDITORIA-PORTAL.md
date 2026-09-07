# Auditoría del portal de Subcontractors y Technicians — informe

**Fecha**: 6-7 de septiembre de 2026 · **Rama**: `claude/gqm-portal-rbac-audit-2yckin`
**Partida**: `gqm-api` `6e7a67e` · `gqm-panel-admin` `199b15b`
**Cierre**: `gqm-api` `bd4f261` · `gqm-panel-admin` `d1e6f23`

---

## 0. Qué cambió después de la auditoría

Este informe se escribió **midiendo**, antes de tocar nada. Su veredicto original —el de
la §1— era «no se puede entregar hoy». Después el encargo cambió: arreglarlo todo,
verificarlo y dejarlo listo para producción.

Se hicieron **dos rondas de arreglo**, cada una seguida de una revisión adversarial. El
estado de cierre está en **`08-arreglos-aplicados.md`** y el plan de despliegue en
**`PLAN-PRODUCCION.md`**. En resumen:

| | Auditoría | Cierre |
|---|---|---|
| Matriz de permisos | 50 no conformes | **0 de 337** |
| Fuga de campo | 690 filas | **0** |
| Bloque de pruebas del verificador | 102 | **162** |
| Playwright | 30 | **58** |
| Suite completa | 753 passed | **806 passed** |

Lo que sigue conserva el texto de la auditoría, porque es el registro de lo que se midió.
Donde un hallazgo esté cerrado, lo dice `08-arreglos-aplicados.md`.

---

## 1. Veredicto (en el momento de la auditoría, antes de arreglar)

> **No se puede entregar hoy con los roles de portal activados.** Se puede entregar con
> **5 condiciones**: cerrar los cuatro grupos de fuga entre pares (P-01 a P-05), cerrar la
> autoaprobación de cumplimiento (P-08), dar al técnico una pantalla donde aterrizar (U-01),
> dar al subcontratista una forma de crear tareas (U-02), y poner un índice único en los
> correos antes del alta masiva (O-02).
>
> **Las cinco condiciones están cumplidas** — y otras diez más que aparecieron al
> arreglar. Ver `08-arreglos-aplicados.md`.

Con matices que importan:

- **El flujo de negocio central funciona.** El recorrido completo —admin crea job, lo asigna,
  el sub lo ve, crea tarea para su técnico, el técnico la actualiza, todos ven el cambio—
  pasa sus ocho pasos y sus tres pruebas negativas, con cada escritura verificada releyendo
  la fila. `scope_jobs_statement` y `scope_tasks_statement` cumplen donde están puestos.
- **Nada de esto está siendo explotado hoy**, porque el portal no está armado: el PR #114
  dejó medido que **0 de 432 subcontratistas tienen `ID_Role`** y que `permission_subc` /
  `permission_tech` están vacías. Los hallazgos son **críticos latentes**: se arman el día
  del alta, que es exactamente lo que se estaba a punto de hacer.
- **Los agujeros no están en el camino que se recorre trabajando**, sino en las rutas
  laterales —`/technician/`, `/attachments/`, `/tlactivity/`, `/subcontractors/`,
  `/certificate/`— que nadie visita usando la aplicación y cualquiera puede pedir desde la
  consola del navegador.

---

## 2. Estado de los hallazgos de la auditoría de Tasks

El directorio `~/outputs/gqm-tasks-audit/` no existe en este entorno, así que **la
numeración H1–H12 no es recuperable**. Se reconstruyó desde el PR #114 —que dice *«de 12
hallazgos de partida se confirmaron 11, se refutó 1 y aparecieron 16 más»*, sin
enumerarlos— y desde las etiquetas `T-nn` que sí viven en commits, código y tests.

Se informa de los 7 que el propio encargo describe. **H4 y H9–H12 quedan no recuperables**;
no se inventan.

| # | Descripción del encargo | Estado | Evidencia |
|---|---|---|---|
| **H2** | timeline de auditoría legible y falsificable por roles de portal | **Falsificación ARREGLADA · lectura VIVA** | `POST /tlactivity/` como sub → **403**; `PATCH` → **403** y la fila no cambia. Pero `GET /tlactivity/job/<ajeno>` → **200**. `main.py:257-269` movió las escrituras a `admin:sync` y **dejó a propósito** las cinco GET por relación en `tasks:read`. Es el hallazgo **P-04** |
| **H3** | `GET /jobs/<id>` puentea el scoping de tareas | **ARREGLADO en efecto, VIVO en estructura** | Diferencia de conjuntos vacía para el sub; el técnico no recibe `tasks` (proyección `JobReadBasic`). Pero nadie aplica `scope_tasks_statement` a la colección anidada: sigue siendo un accidente de proyección, no una comprobación. Ver **F-03** |
| **H5** | `LEAD_TECHNICIAN` es un rol fantasma | **ARREGLADO en la API · VIVO en el panel** | Cero coincidencias en todo `gqm-api`, incluidos objetos git. En el panel gobierna condiciones de render reales y es la **única** guarda de pertenencia de la ficha de subcontratista (`app/subcontractors/[id]/page.tsx:459-470`) — por eso no protege a nadie |
| **H6** | `technician_id` es un filtro muerto | **ARREGLADO** | `/tasks/weekly` sin filtro → 6 tareas; con `technician_id=TEC60002` → `['TSK60003']` |
| **H7** | cero validación en el servidor | **ARREGLADO** | `POST /tasks/ {}` → **400**; `Task_status` inventado → **400** con `validation_error` |
| **H1 / H8** | deuda de integridad en datos vivos | **NO AUDITABLE** | Requiere leer producción. Sin MCP de solo lectura y con el 5432 cerrado. SQL entregado en el `HANDOFF` |

---

## 3. Hallazgos

Severidad: **S1** fuga entre clientes o borrado indebido · **S2** permiso incorrecto sin
fuga · **S3** flujo roto o bloqueante · **S4** UX · **S5** cosmético.

| ID | Sev | Capa | Regla rota | Evidencia | Reproducción |
|---|---|---|---|---|---|
| **P-01** | S1 | API | R2 | `GET /technician/<ajeno>` → 200 con `tasks`, `subcontractor.jobs` y **`permissions[].Document`** (política IAM del objetivo). 5 sujetos | `curl -H "Bearer <sub A>" /technician/TEC60002` |
| **P-02** | S1 | API | R2 | `GET /technician/` devuelve **todos** los técnicos. Es la deuda que el PR #116 marcó «Fase B» | `/technician/?limit=100` → `TEC60001,2,3` |
| **P-03** | S1 | API | R2 | `GET /attachments/[<id>]` entrega **el corpus entero**: el filtro por carpeta se salta si el llamante tiene `attachment:read` global, y ambas políticas de portal lo tienen | `/attachments/` → `ATT60001..4` |
| **P-04** | S1 | API | R2 · H2 | Cuatro rutas de `/tlactivity/` sin scoping: `job`, `subcontractor`, `client`, `parent-mgmt-co` | `/tlactivity/job/PTL-I60001` como sub A → 200 |
| **P-05** | S1 | API+UI | R2 | Un sub lee la ficha completa de otro, con sus `orders`, sus `technicians` y las tareas de estos. **También por URL directa en el panel** | `/subcontractors/SUBC60002` → 200 |
| **P-06** | S2 | API | R2 | Un sub lee los certificados de cumplimiento de otro | `/certificate/subcontractor/SUBC60002` → 200 |
| **P-07** | S1 | API | **R3** | Un sub crea una tarea y se la asigna a **un técnico de otro sub** → **201 y la fila queda escrita** | `POST /tasks/ {ID_Technician:"TEC60002"}` |
| **P-08** | S1 | API | — | Un sub se fija a sí mismo `Gqm_compliance` y `Score` → **200, persiste**. Se autoaprueba el cumplimiento. `PROFILE_PRIVILEGED_FIELDS` filtra `Active`, y `Subcontractor` no tiene `Active`: tiene `Status` | `PATCH /subcontractors/<propio>` |
| **F-01** | S1 | API | — | `permissions[].Document`: el `Statement` completo del objetivo — el mapa de lo que puede hacer | Fase 4, 10 filas |
| **F-02** | S1 | API | — | El bloque financiero completo por `subcontractor.jobs[]`: 17 campos `Gqm_*`, `Acc_receivable`, `Ptl_gc_fee`… | Fase 4 |
| **F-03** | S1 | API | — | **La proyección del técnico es puenteable**: `/jobs/` le oculta el precio, y lo recibe por `/technician/`, `/tasks/`, `/attachments/` y `/tlactivity/`. 50 campos | Fase 4 |
| **F-04** | S2 | API | — | `Score`, `Gqm_compliance` y `Notes` de otros subcontratistas | Fase 4 |
| **F-05** | S2 | API | — | Centinelas ajenos: dirección de obra, orden de compra y notas internas de jobs de otro sub | Fase 4 |
| **F-06** | S3 | API | — | `podio_item_id` expuesto en 6 rutas | Fase 4 |
| **U-01** | **S3** | UI | **R6** | **El técnico no puede usar la aplicación.** Aterriza en `/subcontractors` → «Access Denied»; el único botón vuelve a la misma pantalla. Sus 2 enlaces de menú rebotan | Capturas `technical-landing.png` |
| **U-02** | **S3** | UI | **R3** | **El sub no tiene forma de crear una tarea.** «New Task» se condiciona a `subcontractor:update`, que su política no concede | `capturas/subcontractor-tab-tasks.png` |
| **U-03** | S1 | UI | R2 | La ficha de otro sub carga por URL directa: `middleware.ts:96` compara el prefijo sin mirar el id | `capturas/subcontractor-ficha-ajena.png` |
| **U-04** | S4 | UI | — | El interruptor **Sync Podio** es visible para el subcontratista | `capturas/subcontractor-landing.png` |
| **U-05** | S4 | UI | R6 | 2 de 3 enlaces del menú del sub y 2 de 2 del técnico son enlaces muertos: el menú promete lo que el middleware niega | Fase 6 §1 |
| **O-01** | S2 | API | — | Cero validación de fuerza de contraseña: `"1"`, `"abc"`, `"password"` → 201 | Fase 7 |
| **O-02** | S2 | API+datos | — | Correos duplicados permitidos; el login resuelve siempre al primero y **la segunda cuenta es inalcanzable para siempre**. Sin índice único en `technician`, `subcontractor` ni `member` | Fase 7 |
| **O-03** | S3 | API | — | No se obliga a cambiar la contraseña en el primer acceso | Fase 7 |

**24 hallazgos: 11 S1, 6 S2, 4 S3, 3 S4.**

### Por qué el panel sube la severidad en lugar de contenerla

`app/api/backend/[...path]/route.ts` es un comodín sin lista blanca para cualquier ruta y
cualquier verbo. Con una sesión normal de subcontratista en el navegador:

```
/api/backend/technician/TEC60002       → 200  ← Gqm_formula_pricing, "Document", B-NOTA-INTERNA-GQM
/api/backend/subcontractors/SUBC60002  → 200  ← Gqm_formula_pricing, ORD60002
```

P-01, P-04 y P-05 **no requieren un cliente HTTP ni robar un token**: se explotan con una
línea de JavaScript en la consola de un usuario legítimo.

**Matiz que corrige la hipótesis de partida**: el BFF *es* una tubería —devuelve antes de la
lógica de rol y reenvía el bearer sin comprobar nada— pero la API deniega correctamente
`/api/members`, `/commission`, `/roles` y `/permissions` (403 en los cuatro). La tesis «el
BFF es un colador» es **cierta en la estructura y falsa en el efecto** para esas rutas. No
es una vulnerabilidad por sí misma; es ausencia de defensa en profundidad justo donde la API
falla.

---

## 4. Lo que funciona

Decirlo importa tanto como lo demás, y los controles negativos **pueden fallar** y no fallan:

- **R2 en el núcleo**: `/jobs/<ajeno>` y `/tasks/<ajeno>` → **404** a los cinco sujetos de portal.
- **R4**: `POST /tasks/` como técnico → **403** en los tres técnicos, sin fila creada en BD.
- **R5**: `DELETE /tasks/<propia>` y `DELETE /jobs/<propio>` → **403**, incluso sobre recurso
  propio; la fila sigue existiendo tras el intento.
- **Ambigüedad 7 ratificada**: retirar la asignación corta el acceso al instante (200 → 404).
- **El técnico independiente opera con normalidad** en la API: su scope no depende de tener sub.
- **`Password` no aparece en ninguna respuesta** de las rutas barridas.
- **La recuperación de contraseña no revela si la cuenta existe**, y el límite de intentos
  corta al quinto.
- **H6 y H7 arreglados**; H2 arreglado en su mitad grave (la falsificación).

---

## 5. Lo que NO se pudo auditar, y por qué

| Qué | Motivo |
|---|---|
| **Fase 3.3 — perfilado de datos de producción** | No existe el MCP `gqm-prod-readonly` en esta sesión y **el puerto 5432 está cerrado** (solo sale HTTPS/443, medido). No hay ninguna vía. El SQL enumerativo va en el `HANDOFF` |
| Deuda de integridad H1/H8 (141 filas de auditoría sin vínculo, 153 tareas) | Igual que lo anterior: son datos de producción |
| `GET /podio/items/<app_type>` | Una de las 4 rutas **solo-JWT**. Devuelve 500 sin credenciales de Podio: **no auditada, no aprobada** |
| Envío real del correo de recuperación, caducidad y uso único del token | Sin SMTP configurado; el 200 del endpoint no prueba que el correo salga |
| 34 tests de la suite (`test_paridad_endpoints`, `test_bloqueo_escritura_podio`, webhooks…) | Exigen credenciales de Podio, que este entorno niega **a propósito**: no tenerlas es la garantía de aislamiento |
| Formas de datos reales | La BD es virgen y sembrada. Sirve para auditar el **código**, que es lo que decide los permisos; no reproduce la forma del dato de producción |

---

## 6. La desviación autorizada: la compuerta de aislamiento

Se tocó **código de producción** en un solo frente, autorizado por el usuario tras
exponerle la alternativa (auditoría solo estática). Sin ello no arranca ni un test en este
entorno: `tests/conftest.py` usa `sys.exit`, que mata la sesión de pytest.

Seis ficheros repetían `"ep-sparkling-sound" not in DATABASE_URL`. Ahora importan
`src/utils/db_guard.py`, que **parsea el host** y es más estricto en tres frentes: rechaza
`@host-de-produccion/ep-sparkling-sound` (que la versión vieja aceptaba, por estar el
marcador en el nombre de la base), recoge `?host=`/`?hostaddr=` —a los que libpq da
prioridad— y exige `.neon.tech` en la rama de develop. Conserva el caso
`?options=endpoint=…` que Neon usa con drivers sin SNI, cuyo rechazo habría sido una
regresión.

Prueba de mutación ejecutada: con un DSN de producción, con un DSN engañoso y con
`APP_ENV=production`, **los cinco call-sites siguen abortando**. 21 tests nuevos
(`tests/unit/test_db_guard.py`) fijan el contrato. Diff completo en `00-entorno.md`.

Un sexto sitio, `scripts/sanear_tasks.py`, no estaba en el plan aprobado: se declara. Nunca
comprobó `APP_ENV` y **sigue sin hacerlo**.

---

## 7. Cifras

| Fase | Resultado |
|---|---|
| Superficie total | 330 pares método×ruta · **46 alcanzables por un rol de portal** · 4 solo-JWT |
| Matriz (Fase 3) | 309 filas · 259 conformes · **50 no conformes** · 8 no auditables |
| Fugas de campo (Fase 4) | **690 filas** |
| Flujo e2e (Fase 5) | 8 pasos + 3 pruebas negativas: **todo pasa** |
| Tests RBAC | **102 passed, 0 failed** |
| Suite completa | 753 passed · 27 failed · 7 errors (los 34 fallos, todos por credenciales de Podio ausentes) |

### Y tras las dos rondas de arreglo

| Fase | Resultado |
|---|---|
| Matriz | 337 filas · **337 conformes · 0 no conformes** |
| Fugas de campo | **0 filas** · 37 sondas analizadas, 21 saltadas (declaradas) |
| Flujo e2e | 8 pasos + 3 negativas: en verde |
| Bloque de pruebas del verificador | **162 passed** |
| Playwright | **58 passed** |
| Suite completa | **806 passed** · 27 failed · 7 errors — **idénticos, uno a uno, a los de `main`**, comparados enumerando identificadores de prueba y no contándolos |

Un solo comando reproduce el veredicto: **`bash scripts/verificar_portal.sh`**.

El paquete completo está en `reports/portal-audit/`. La entrada de la sesión de arreglos es
**`reports/portal-audit/HANDOFF-ARREGLOS.md`**; el cierre, `08-arreglos-aplicados.md`; el
despliegue, `PLAN-PRODUCCION.md`.
