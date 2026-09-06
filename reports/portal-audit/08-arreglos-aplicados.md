# Arreglos aplicados — de 50 filas no conformes a 0

Sesión posterior a la auditoría, sobre las mismas ramas.
`gqm-api` `78c5b36` · `gqm-panel-admin` `15a942d`.

## Antes y después

| Medida | Auditoría | Tras los arreglos |
|---|---|---|
| Matriz de permisos (309 filas) | **50 no conformes** | **0** |
| Fuga de campo | **690 filas** | **0** |
| Tests RBAC | 102 | **106** |
| Playwright | 30 (portal solo navegación) | **47**, con 16 de regresión de portal |
| Suite completa | 753 passed · 27 failed · 7 errors | **765 passed** · 27 failed · 7 errors *(idénticos: todos exigen Podio)* |
| Flujo e2e | 8 pasos + 3 negativas | igual, en verde |

Un solo comando reproduce el veredicto: **`bash scripts/verificar_portal.sh`**.

## La idea que ordena todo el arreglo

Los ocho hallazgos `P-nn` eran **el mismo defecto repetido**: leer un recurso por id sin
comprobar pertenencia. Y los seis `F-nn` eran **otro defecto único repetido**:
`serialize_job()` es la única proyección que existía en el código, y solo la usaban las
rutas de `/jobs`.

Por eso no se arreglaron catorce veces, sino dos:

### `src/utils/portal_redaction.py` — la redacción, donde pasa todo

Engancha en `add_relationships`, el punto por el que pasa **todo** volcado de la API.
Cierra F-01, F-02, F-04, F-05 y F-06 de una vez.

Arreglarlo ruta a ruta habría dejado el agujero abierto para la siguiente ruta que alguien
escribiera — que es exactamente lo que le pasó a `/jobs/by-type-year` en su día (T-27), y
la razón por la que el técnico recibía por cuatro rutas el precio que `/jobs/` le ocultaba.

### `portal_owns_technician` y `portal_owns_subcontractor` — la pertenencia

Dos funciones en `routes_protection.py`, junto a las primitivas de scoping que ya existían.
Cierran P-01, P-02, P-05 y P-06 con el modismo 404 que ya usaba `Tasks.py:170`: para un rol
de portal, un recurso ajeno **no confirma su existencia**.

## Los 24 hallazgos, uno a uno

| ID | Qué se hizo | Dónde |
|---|---|---|
| **P-01** | Pertenencia antes de devolver la ficha del técnico, y `permissions` fuera de la expansión | `Technician.py:97-113` |
| **P-02** | El listado se acota en el *statement*, antes de paginar, para que el `total` no delate cuántos hay | `Technician.py:48-58` |
| **P-03** | El atajo por `attachment:read` global deja de aplicarse al portal; se exige pertenencia del job, propia o de sus técnicos | `Attachments.py:31-95,122` |
| **P-04** | Las cuatro rutas de timeline por relación se acotan | `TLActivity.py` |
| **P-05** | Pertenencia en la ficha del sub, y `orders`/`financial_docs`/`estimate_costs` fuera para portal | `Subcontractor.py` |
| **P-06** | El `<subc>` del path se compara con el llamante | `Certificate.py` |
| **P-07** | El técnico destino debe pertenecer al sub, en `POST` y en `PATCH` | `Tasks.py` |
| **P-08** | `PROFILE_PRIVILEGED_FIELDS` gana `Status`, `Score`, `Gqm_compliance`, `Gqm_best_service_training` | `routes_protection.py:289` |
| **F-01…F-06** | Redacción central por rol | `portal_redaction.py` + `relationships.py` |
| **U-01** | El técnico aterriza en `/dashboard` con sus tareas | panel: `middleware.ts`, `dashboard/page.tsx`, `LeadTechnicianDashboard.tsx` |
| **U-02** | «New Task» pasa a `tasks:create`; el diálogo recibe `userRole`/`userSubId` | `subcontractors/[id]/page.tsx`, `CreateTaskDialog.tsx` |
| **U-03** | Guarda de pertenencia escrita para `subcontractor`, no para el rol fantasma | `subcontractors/[id]/page.tsx`, `middleware.ts` |
| **U-04** | «Sync Podio» oculto al portal | `subcontractors/[id]/page.tsx` |
| **U-05** | El sidebar deja de pintar rutas que el middleware rebota | `Sidebar.tsx` |
| **O-01** | Fuerza de contraseña validada en servidor | `password_policy.py` + rutas de alta |
| **O-02** | Índice único parcial e insensible a mayúsculas, con saneador previo | migración `e9c1correo` |
| **O-03** | **No arreglado** — ver «lo que queda» |

## Dos cosas que la auditoría no había visto

Aparecieron al arreglar, y las dos importan para el alta de los 432:

### O-04 — el login comparaba el correo de tres formas distintas

`Subcontractor` se buscaba con `lower()`; `Member` y `Technician`, con igualdad exacta.
Medido: un sub entra escribiendo `SUB-DEV@…`; un técnico recibe **401**, indistinguible de
una contraseña mal escrita. Con 432 registros importados de Podio, donde la capitalización
del correo no la controla nadie, es un fallo de acceso silencioso. Normalizado en los tres.

### La fuga del job compartido

Con dos subcontratistas en la **misma obra**, `GET /jobs/<id>` le entregaba a uno la ficha
del otro con sus `orders` dentro. **La matriz no podía verlo**: los mundos A y B eran
disjuntos por diseño, así que no había obra compartida contra la que probar. No es que se
buscara y no apareciera — es que no había dónde mirar, el mismo defecto de método que tenía
la matriz del PR #116 con un solo sujeto por rol.

Se añadió el job compartido como **fixture permanente** y `serialize_job` poda las
colecciones anidadas.

## Por qué el verde es creíble: prueba de mutación

Un verde que no puede ponerse rojo no vale nada. Saboteando `llamante_es_portal()` para que
devuelva siempre `False`:

```
escáner de fugas   0  →  397 filas     ✅ lo detecta
matriz de permisos 309/309 → 309/309   ✅ correcto: mide otra cosa
```

Los dos detectores están vivos y son independientes.

## Lo que queda abierto, y por qué

| Qué | Por qué no se hizo |
|---|---|
| **O-03** cambio obligatorio de contraseña en el primer acceso | Requiere una columna nueva (`must_change_password`), una migración y una pantalla en el panel. Es una funcionalidad, no un arreglo, y no debe colarse en un cutover de seguridad |
| **Un sub ve las tareas de otro sub en una obra compartida** | `scope_tasks_statement` concede, **por diseño y con tests**, todas las tareas de los jobs propios. En una obra compartida eso incluye las del otro contratista. Es coherente con `/tasks/`, no es una regresión, y cambiarlo altera una regla deliberada. **Decisión de negocio pendiente** — ver §final del informe |
| **Los dos vocabularios de rol** | El servidor usa `gqm_role`; casi todo el gating de UI lee `localStorage.user_data.role`, editable. Unificarlos es un refactor grande. Las guardas **nuevas** se escribieron contra el vocabulario del servidor |
| **`Resource` por objeto en `PolicyEvaluator`** | Implementado y sin usar: todos los sitios pasan `"*"`. Es la causa raíz de la familia `P-nn`. Decisión de arquitectura |
| **`GET /podio/items/<app_type>`** | Ruta solo-JWT, **no auditada**: devuelve 500 sin credenciales de Podio |
