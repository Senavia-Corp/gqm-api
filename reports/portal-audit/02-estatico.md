# Fase 2 — Auditoría estática

Lectura del código, sin ejecutarlo. Todo con `archivo:línea`.

## 1. Las cuatro capas de autorización

| Capa | Dónde | Qué hace |
|---|---|---|
| 0 · puerta JWT global | `main.py:116-185` | Falla **cerrado**. Sin `Authorization: Bearer` rechaza, salvo 11 prefijos públicos (`main.py:131-159`). Deja `g.current_user` (`:182-185`) |
| 1 · `@require_permission` | `routes_protection.py:191-285` | Carga las políticas IAM de la BD **en cada petición** y evalúa. Deja `g.user_policies` (`:273`) |
| 2 · `protect_blueprint` | `routes_protection.py:81-124` | Deriva la acción del verbo: GET→`:read`, POST→`:create`, DELETE→`:delete`, resto→`:update` (`:104-112`) |
| 3 · `@require_role` | `routes_protection.py:152-188` | Compara el claim `role` con una lista. Usado en **un solo sitio**: `ChatMessage.py:106,161` |

Evaluador: `src/utils/policy_evaluator.py:21-58`. Documentos estilo AWS IAM, comodines por
`fnmatch`, **`Deny` explícito cortocircuita** (`:52-54`), y por defecto deniega (`:33`).

### Dos propiedades del diseño que ensanchan la superficie

**a) Semántica OR sobre la lista de acciones** (`routes_protection.py:276-279`). Como ambas
políticas de portal incluyen `profile:update_own`, los roles de portal **pasan el
decorador** de `/member/<id>`, `PATCH /member/<id>` y `/commission/member/<id>`. Las tres
están cerradas *en el handler* (`Commission.py:213`, `self_profile_guard`), no en el
decorador. Verificado en la Fase 3: los cinco sujetos de portal reciben 403. Funciona, pero
quien lea solo el decorador concluirá lo contrario.

**b) `PolicyEvaluator` admite `Resource` por objeto y nadie lo usa.** *Todos* los sitios de
llamada pasan `resource="*"`. La autorización a nivel de objeto se hace a mano en cada
handler, y por eso la cobertura es desigual: es la causa raíz de los 8 hallazgos `P-nn`.

### `protect_blueprint` no deja `g.user_policies`

`routes_protection.py:120` deja `g.current_user` pero **nunca** `g.user_policies`. Un
handler que lea `getattr(g, "user_policies", [])` para proyectar campos recibirá `[]`,
`PolicyEvaluator.evaluate([], ...)` será `False` y `serialize_job` (`Job.py:67`) caerá a
devolver el diccionario **sin proyectar**. Hoy los 12 lectores de `g.user_policies` están
todos tras `@require_permission`, así que es **latente, no vivo** — pero es una trampa para
cualquier handler que se mueva de sitio.

## 2. Funciones de scoping

Todas en `routes_protection.py:127-371`:

| Función | Línea | Qué acota |
|---|---|---|
| `portal_scope()` | `:127-133` | **La única definición de «rol de portal»** en todo el código |
| `scope_jobs_statement()` | `:136-149` | sub → jobs enlazados; técnico → jobs enlazados |
| `scope_tasks_statement()` | `:311-332` | técnico → `Tasks.ID_Technician == uid`; sub → tarea propia **o** tarea de sus jobs |
| `job_belongs_to_portal_user()` | `:335-349` | pertenencia de un job |
| `task_belongs_to_portal_user()` | `:352-371` | pertenencia de una tarea |
| `self_profile_guard()` | `:292-308` | autoservicio: exige `role == target_type and id == target_id` |

**Dónde se aplican**: `Job.py` en 11 sitios, `Tasks.py` en 8, `Order.py` en 3,
`ChatMessage.py:49`, y dentro del generador de Excel (`export_service.py:102-103`).
`Tasks.py` es el fichero mejor acotado del repositorio.

**Dónde NO se aplican** — y son exactamente los hallazgos de la Fase 3:

| Endpoint | Fichero:línea | Acción exigida | Scoping |
|---|---|---|---|
| `GET /technician/<id>` | `Technician.py:63-74` | `technician:read` | **ninguno** — carga `tasks`, `subcontractor.jobs`, `permissions` |
| `GET /technician/` | `Technician.py:31-32` | `technician:read` | **ninguno** |
| `GET /subcontractors/<id>` | `Subcontractor.py:172-193` | `subcontractor:read` | **ninguno** — expande `orders`, `technicians.tasks`, `certificates` |
| `GET /attachments/[<id>]` | `Attachments.py:32,56-68,82,105` | `attachment:read` | **el filtro por carpeta se salta si el llamante tiene `attachment:read` global — y ambas políticas de portal lo tienen** |
| `GET /certificate/*` | `Certificate.py:27,56,82-94` | `certificate:read` | **ninguno** — el `<subc>` del path se usa crudo |
| `GET /tlactivity/{job,client,pmc,subcontractor}/<id>` | `TLActivity.py:115,161,206,251` | `tasks:read` (vía verbo) | **ninguno** |

`main.py:257-269` movió `list/create/update/delete_tlactivity` a `admin:sync` para impedir
que el portal falsificara auditoría (el hallazgo T-02 de la auditoría de Tasks), pero
**dejó las cinco rutas GET por relación en `tasks:read`** a propósito, porque son las que
consume el panel. Ninguna acota.

## 3. Permisos declarados vs. permisos exigidos

Un permiso que existe pero que nadie comprueba es un permiso falso.

| Acción en las políticas de portal | ¿La exige alguna ruta? |
|---|---|
| `job:read`, `job:read_basics`, `tasks:read`, `tasks:create`, `tasks:update`, `subcontractor:read`, `technician:read`, `skill:read`, `attachment:read`, `attachment:create`, `certificate:read`, `profile:update_own` | sí |
| **`tasks:read_own`** | **no la exige ninguna ruta** — decorativa |
| **`attachment:read_technicians`** | solo aparece en la lista OR de `/attachments/*`, donde `attachment:read` ya basta: **inerte** |

`tasks:read_own` ya se identificó como decorativa en la auditoría de Tasks (R16, commit
`7431d87`) y **sigue en el documento de política sembrado** (`seed_rbac.py:87,99`).

## 4. La convención 404 vs 403

Regla declarada (`Job.py:506-507`): *404 cuando revelar la existencia es la fuga; 403 cuando
el identificador ya lo conoce quien pregunta.* Aplicada de forma deliberada pero desigual.

- **404** (6 sitios): `/jobs/<ajeno>` `:511,514` · `/jobs/oldest` `:455` · `/tasks/<ajeno>`
  `Tasks.py:170,246,282` · `/order/<ajeno>` `Order.py:96`.
- **403** (7 sitios): `/jobs/subcontractor/<ajeno>` `Job.py:836` —con su razonamiento escrito
  en `:832-833`— · `POST /tasks/` en job ajeno `Tasks.py:211` · reasignación fuera de scope
  `:256,265` · `/order/subcontractor/...` `Order.py:115` · `self_profile_guard` `:305`.
- **Oráculo de existencia**: `Attachments.py:99-109` devuelve **404 si no existe y 403 si
  existe pero es ajeno** — los dos códigos juntos distinguen «no hay» de «hay y no es tuyo».
  Es exactamente lo que el modismo de `Tasks.py` (`if not obj or not pertenece: 404`) evita.
  Ningún test cubre esa secuencia.

## 5. Rutas sin ningún mecanismo de autorización

Cuatro rutas son **solo-JWT**: cualquier autenticado, sin comprobar permiso.

```
GET /auth/can                  por diseño
GET /auth/me                   por diseño
GET /static/<path:filename>    estático
GET /podio/items/<app_type>    ← ni por diseño ni documentado
```

`GET /podio/items/<app_type>` (`src/podio/get_user_id.py:39`) queda **no auditada**: en este
entorno devuelve 500 por falta de credenciales de Podio. Va al `HANDOFF`.

## 6. El rol fantasma `LEAD_TECHNICIAN`

**No existe en el backend.** Búsqueda de todas las variantes de mayúsculas y separadores en
el árbol de trabajo completo y en todos los objetos git alcanzables: **cero coincidencias**
en `gqm-api`. Los roles reales son las cuatro filas de `seed_rbac.py:53`, y los tres valores
que puede llevar el claim `role` del JWT son `member`, `technician` y `subcontractor`
(`Login_auth.py:135,166,193`).

En el panel, en cambio, `LEAD_TECHNICIAN` es el vocabulario que **casi todo el gating de UI
lee** (`lib/types.ts:526`, escrito por el cliente en `app/login/page.tsx:58-65`). Se detalla
en la Fase 6.
