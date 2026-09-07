# Handoff de arreglos — portal Subcontractor / Technical

> ## ⚠️ Este documento ya está EJECUTADO
>
> Se escribió como lista de trabajo pendiente, antes de arreglar nada. **Los bloques
> A a F están hechos**, más otros nueve hallazgos que aparecieron al arreglarlos.
> No lo sigas como una lista de tareas: léelo como el razonamiento de por qué cada
> arreglo es el que es.
>
> - Qué se hizo y qué se midió: **`08-arreglos-aplicados.md`**
> - Cómo desplegarlo: **`PLAN-PRODUCCION.md`**
> - Comprobarlo en un comando: **`bash scripts/verificar_portal.sh`**
>
> Lo único de aquí que **sigue pendiente y es para ti** es el SQL del final: la deuda
> de datos de producción, que no se pudo medir desde esta sesión.

Escrito para alguien que **no vivió esta auditoría**. Ordenado por dependencias, no solo por
severidad: los tres primeros bloques comparten causa raíz y arreglarlos en orden evita
rehacer trabajo.

Antes de nada, dos hechos que cambian cómo se prioriza:

1. **Nada de esto está siendo explotado hoy.** 0 de 432 subcontratistas tienen `ID_Role` y
   `permission_subc`/`permission_tech` están vacías (PR #114). Hay margen para arreglar
   *antes* de armar el portal — pero solo hasta ese día.
2. **El flujo central funciona.** No hay que rediseñar nada: hay que cerrar rutas laterales.

---

## Bloque A — La causa raíz común (haz esto primero)

Los hallazgos P-01, P-03, P-04, P-05, P-06 son **el mismo defecto repetido**: rutas
alcanzables por portal que leen un recurso por id **sin comprobar pertenencia**. Ya existen
las primitivas; solo no se llaman.

**Reutiliza, no escribas nuevo** (`src/utils/middleware/auth/routes_protection.py`):

| Primitiva | Línea | Para qué |
|---|---|---|
| `portal_scope()` | `:127-133` | `(rol, id)` si el llamante es de portal |
| `scope_jobs_statement()` | `:136-149` | acota una consulta de jobs |
| `scope_tasks_statement()` | `:311-332` | acota una consulta de tareas |
| `job_belongs_to_portal_user()` | `:335-349` | pertenencia de un job |

**Convención de esta base de código**: para un rol de portal, un recurso ajeno pedido por id
responde **404**, no 403 — un 403 confirma la existencia y es enumerable. El modismo ya usado
en `Tasks.py:170` es `if not obj or not pertenece(obj): 404`. Úsalo.

| # | Fichero:línea | Arreglo | Cómo se prueba | Qué puede romper |
|---|---|---|---|---|
| **A1** · P-01 | `src/routes/Technician.py:63-74` | Comprobar pertenencia antes de devolver: un sub solo ve técnicos con `ID_Subcontractor == él`; un técnico, solo a sí mismo. Y **quitar `permissions` de la lista de `add_relationships`** (`:86-87`): nadie de portal necesita el documento IAM de otro | `audit_portal_matrix.py` → la fila `GET /technician/<id> · ajeno` debe pasar a 404 | El panel usa esta ruta en `LinkTechnicianModal`; comprobar que el sub sigue viendo a **los suyos** |
| **A2** · P-02 | `src/routes/Technician.py:31-32` | Acotar el listado por `ID_Subcontractor` cuando `portal_scope()` devuelve un sub. **Decisión ratificada: solo los suyos** | matriz → `GET /technician/` enumeración sin intrusos | Es la deuda «Fase B» del PR #116; el selector de técnicos del panel depende de ella |
| **A3** · P-03 | `src/routes/Attachments.py:56-68` y `:105` | El filtro por carpeta se salta si el llamante tiene `attachment:read` global — **y ambas políticas de portal lo tienen**. Hacer que el atajo `has_global_read` **no aplique a roles de portal**, y añadir pertenencia del job | matriz → `/attachments/` enumeración y `/attachments/<ajeno>` | Ojo: `GET /attachments/` **devuelve 404 con lista vacía** (`:70-71`); no confundir con denegación |
| **A4** · P-04 | `src/routes/TLActivity.py:115,161,206,251` | Acotar las cuatro GET por relación. `main.py:257-269` ya movió las escrituras a `admin:sync` (eso cerró la mitad grave de H2); falta la lectura | matriz → las 4 rutas de `/tlactivity/` con objeto ajeno | Son las que consume el timeline del panel: verificar que el sub sigue viendo **su** timeline |
| **A5** · P-05 | `src/routes/Subcontractor.py:172-193` | Pertenencia: un sub solo lee su propia ficha. Y **recortar la expansión**: `orders`, `orders.financial_docs`, `orders.estimate_costs` no deben salir a portal | matriz → `/subcontractors/<ajeno>` = 404; Fase 4 → sin `ORD*` ni `Gqm_*` | El panel monta la ficha del sub con esta ruta: es su landing |
| **A6** · P-06 | `src/routes/Certificate.py:82-94` | El `<subc>` del path se usa crudo (`:94`): compararlo con el id del llamante | matriz → `/certificate/subcontractor/<ajeno>` | — |

> **Coste real del bloque A**: seis handlers. No hace falta tocar el modelo ni migrar datos.

---

## Bloque B — La proyección de campos (F-01…F-05)

**F-03 es el hallazgo estructural y conviene entenderlo antes de tocar nada**:
`serialize_job()` (`Job.py:57-68`) es **la única proyección que existe en todo el código**, y
solo la usan las rutas de `/jobs`. Cualquier otra ruta que expanda una relación con `job`
dentro entrega el objeto entero, bloque financiero incluido. Por eso a un técnico `/jobs/` le
oculta el precio y `/technician/`, `/tasks/`, `/attachments/` y `/tlactivity/` se lo dan.

**Arreglar el bloque A reduce F-02/F-04/F-05 pero no los elimina**: cierran el acceso a lo
ajeno y dejan intacto lo que se entrega de más sobre lo propio.

| # | Arreglo | Nota |
|---|---|---|
| **B1** | Aplicar `serialize_job()` (o una proyección equivalente) **en toda ruta que expanda un job**, no solo en `/jobs` | Es lo que convierte la protección del técnico en una regla aplicada y no en una propiedad de una sola ruta |
| **B2** | Quitar `permissions` de la expansión de `Technician` | Cubre F-01 y es de una línea |
| **B3** | Considerar una lista blanca por rol en `add_relationships` (`src/utils/relationships.py:6-98`) | Hoy hace `model_dump()` de **todas** las columnas y solo redacta `Password`. Es la causa raíz de toda la Fase 4 |
| **B4** | `PolicyEvaluator` **admite `Resource` por objeto y ningún sitio de llamada lo usa** (todos pasan `"*"`) | Es la razón de que la autorización a nivel de objeto se haga a mano y la cobertura sea desigual. Decisión de arquitectura, no arreglo puntual |

---

## Bloque C — Escrituras indebidas (P-07, P-08)

| # | Fichero:línea | Arreglo | Cómo se prueba |
|---|---|---|---|
| **C1** · P-07 | `src/routes/Tasks.py:202-212` | `task_belongs_to_portal_user` valida el **job**, no el **técnico destino**. Añadir: si el llamante es un sub, `ID_Technician` debe pertenecerle. **Decisión ratificada: solo a los suyos** | matriz → `POST /tasks/ técnico de OTRO sub` debe pasar a 403 y **no crear fila** |
| **C2** · P-08 | `routes_protection.py:289` | `PROFILE_PRIVILEGED_FIELDS = {"ID_Role","Active","ID_Subcontractor"}` filtra `Active`, y **`Subcontractor` no tiene `Active`: tiene `Status`**. Añadir `Status`, `Score`, `Gqm_compliance`, `Gqm_best_service_training` | matriz → la fila debe pasar a 403 y **la relectura de la fila debe mostrar el valor viejo** |

> C2 es de una línea y evita que un subcontratista se autoapruebe el cumplimiento. Hazlo
> aunque no hagas nada más.

---

## Bloque D — Interfaz (U-01…U-05)

**U-01 y U-02 son los que bloquean la entrega**, más que cualquier fuga: sin ellos el
producto no se puede usar.

| # | Arreglo | Nota |
|---|---|---|
| **D1** · U-01 | **Dar al técnico una pantalla propia donde aterrizar.** Hoy va a `/subcontractors`, que no tiene permiso para ver: su primera pantalla es «Access Denied» y el único botón cierra un bucle | El componente `LeadTechnicianDashboard` **ya existe** y está inalcanzable. Lo más barato es apuntar `PORTAL_PREFIXES.technical` a una ruta de tareas y arreglar `homeFor()` en `tests/rbac/helpers.ts:44`, **que hoy codifica la landing rota como la esperada** |
| **D2** · U-02 | El botón «New Task» se condiciona a `subcontractor:update` (`app/subcontractors/[id]/page.tsx:1322-1330`), que la política del sub no concede. Cambiarlo a `tasks:create` | Sin esto, R3 no tiene camino en el producto |
| **D3** · U-03 | `middleware.ts:96` compara el prefijo `/subcontractors` **sin mirar el id**. La única guarda de pertenencia de la página es para `LEAD_TECHNICIAN` (`page.tsx:459-470`), **un rol que no existe en el backend** | Arreglar A5 lo mitiga (la API devolvería 404), pero la guarda de UI debe escribirse para `subcontractor` |
| **D4** · U-05 | El sidebar pinta `/dashboard` y `/jobs` a roles que el middleware rebota. Alinear `Sidebar.tsx:66-75` con `middleware.ts:19-24` | 2 de 3 enlaces del sub y 2 de 2 del técnico están muertos |
| **D5** · U-04 | Ocultar el interruptor **Sync Podio** a roles de portal | — |
| **D6** | **Unificar el vocabulario de rol.** El servidor usa `gqm_role` (cookie); casi todo el gating de UI lee `localStorage.user_data.role`, **editable desde devtools**, con un valor `LEAD_TECHNICIAN` que no existe en el backend | Deuda de fondo: mientras coexistan, cualquier guarda de UI escrita contra el vocabulario cliente es decorativa |

---

## Bloque E — Onboarding, **antes** del alta masiva

Estos tres hay que cerrarlos **antes** de dar de alta a los 432, no después.

| # | Arreglo | Por qué antes |
|---|---|---|
| **E1** · O-02 | **Índice único sobre `Email_Address`** en `technician`, `subcontractor` y `member` (hoy no hay ninguno) | Con 432 altas, un correo repetido no da error: crea una cuenta muda que consume el correo y **a la que nadie podrá entrar nunca**, porque el login resuelve siempre a la primera fila. Requiere migración Alembic y **sanear duplicados existentes primero** |
| **E2** · O-01 | Validación de fuerza de contraseña en servidor | Hoy `"1"` y `"password"` devuelven 201 |
| **E3** · O-03 | Cambio obligatorio en el primer acceso | La contraseña la escribe el administrador y es la definitiva |
| **E4** | **La app no soporta alta masiva.** No hay importación, ni invitación, ni generación de credenciales. `cleanup_rbac.py` asigna roles en bloque pero **no crea credenciales** | Es una funcionalidad que falta, no un bug |

---

## Bloque F — Limpieza y deuda menor

- **F-06**: `podio_item_id` sale en 6 rutas de portal.
- **`tasks:read_own` y `attachment:read_technicians` son permisos decorativos**: ninguna ruta
  los exige. `tasks:read_own` ya se marcó así en la auditoría de Tasks (R16) y **sigue en el
  documento de política sembrado** (`seed_rbac.py:87,99`).
- **`GET /podio/items/<app_type>`** es solo-JWT, sin comprobación de permiso, y **quedó no
  auditada**: devuelve 500 sin credenciales de Podio. Revisarla con Podio configurado.
- **Oráculo de existencia en adjuntos**: `Attachments.py:99-109` devuelve 404 si no existe y
  403 si existe y es ajeno. Los dos códigos juntos distinguen «no hay» de «hay y no es tuyo».
  Ningún test lo cubre.
- **`protect_blueprint` nunca deja `g.user_policies`** (`routes_protection.py:120`). Hoy es
  **latente**: los 12 lectores están tras `@require_permission`. Es una trampa para cualquier
  handler que se mueva de blueprint — si pasa, `serialize_job` devolverá el payload **sin
  proyectar**.
- **`scripts/sanear_tasks.py`** nunca comprobó `APP_ENV` y sigue sin hacerlo.
- **`scripts/audit_rbac_map.py`** mantiene una copia a mano de `public_prefixes` que ya se
  desincronizó una vez (le faltaba `/webhook/podio/dead_letter_cron`). Debería leerla de
  `main.py` en vez de duplicarla.

---

## Cómo reproducir el entorno de esta auditoría

```bash
pg_ctlcluster 16 main start
cd /home/user/gqm-api
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed_rbac.py
.venv/bin/python scripts/seed_portal_audit.py        # --limpiar para deshacer
.venv/bin/python -m flask --app main:app run --host 127.0.0.1 --port 8000 --no-reload

# los tres arneses de la auditoría
.venv/bin/python scripts/audit_rbac_map.py --csv mapa.csv          # sin BD ni servidor
.venv/bin/python scripts/audit_portal_matrix.py --csv matriz.csv   # sale !=0 si hay no conformes
.venv/bin/python scripts/audit_field_leaks.py --csv fugas.csv
```

**El criterio de «arreglado»**: `audit_portal_matrix.py` sale con código 0. Hoy sale 1 con 50
filas no conformes.

---

## SQL para la deuda de datos de producción

No ejecutable desde esta sesión (sin MCP de solo lectura y con el 5432 cerrado). **Ejecútalo
tú contra el read-only y pega la salida en el informe.** Enumera, no cuenta — un recuento
puede tapar un ausente compensado por un sobrante.

```sql
-- 1. La brecha de onboarding: 432 subs frente a cuántos técnicos utilizables
SELECT 'subcontractor' AS tipo, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE "Password" IS NOT NULL) AS con_password,
       COUNT(*) FILTER (WHERE "ID_Role" IS NOT NULL)  AS con_rol,
       COUNT(*) FILTER (WHERE "Email_Address" IS NOT NULL) AS con_correo
FROM subcontractor
UNION ALL
SELECT 'technician', COUNT(*), COUNT(*) FILTER (WHERE "Password" IS NOT NULL),
       NULL, COUNT(*) FILTER (WHERE "Email_Address" IS NOT NULL)
FROM technician;

-- 2. O-02 antes de poner el índice único: duplicados que hay que sanear
SELECT "Email_Address", COUNT(*), array_agg("ID_Technician") FROM technician
 WHERE "Email_Address" IS NOT NULL GROUP BY 1 HAVING COUNT(*) > 1;
SELECT "Email_Address", COUNT(*), array_agg("ID_Subcontractor") FROM subcontractor
 WHERE "Email_Address" IS NOT NULL GROUP BY 1 HAVING COUNT(*) > 1;
SELECT "Email_Address", COUNT(*), array_agg("ID_Member") FROM member
 WHERE "Email_Address" IS NOT NULL GROUP BY 1 HAVING COUNT(*) > 1;

-- 3. Cardinalidad y huérfanos de las tablas puente
SELECT 'job_subcontractor' t, COUNT(*) FROM job_subcontractor
UNION ALL SELECT 'job_technician', COUNT(*) FROM job_technician;

SELECT js.job_id, js.subcontr_id FROM job_subcontractor js
  LEFT JOIN jobs j ON j."ID_Jobs" = js.job_id
  LEFT JOIN subcontractor s ON s."ID_Subcontractor" = js.subcontr_id
 WHERE j."ID_Jobs" IS NULL OR s."ID_Subcontractor" IS NULL;

SELECT jt.job_id, jt.technician_id FROM job_technician jt
  LEFT JOIN jobs j ON j."ID_Jobs" = jt.job_id
  LEFT JOIN technician t ON t."ID_Technician" = jt.technician_id
 WHERE j."ID_Jobs" IS NULL OR t."ID_Technician" IS NULL;

-- 4. Tareas: sin técnico, con técnico ajeno al sub del job, o apuntando a job borrado
SELECT "ID_Tasks","ID_Jobs" FROM tasks WHERE "ID_Technician" IS NULL;

SELECT ta."ID_Tasks", ta."ID_Jobs", ta."ID_Technician", te."ID_Subcontractor" AS sub_del_tecnico
  FROM tasks ta
  JOIN technician te ON te."ID_Technician" = ta."ID_Technician"
 WHERE ta."ID_Jobs" IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM job_subcontractor js
                    WHERE js.job_id = ta."ID_Jobs" AND js.subcontr_id = te."ID_Subcontractor");

SELECT ta."ID_Tasks", ta."ID_Jobs" FROM tasks ta
  LEFT JOIN jobs j ON j."ID_Jobs" = ta."ID_Jobs"
 WHERE ta."ID_Jobs" IS NOT NULL AND j."ID_Jobs" IS NULL;

-- 5. H1/H8: ¿siguen vivas las 141 filas de auditoría sin vínculo?
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE "ID_Jobs" IS NULL) AS sin_job
  FROM tlactivity;
SELECT "ID_TLActivity","Action","Action_datetime" FROM tlactivity
 WHERE "ID_Jobs" IS NULL ORDER BY "Action_datetime" DESC LIMIT 50;

-- 6. Quién puede entrar hoy al portal (debería ser 0 según el PR #114)
SELECT s."ID_Subcontractor", s."Email_Address", s."ID_Role"
  FROM subcontractor s WHERE s."ID_Role" IS NOT NULL;
SELECT COUNT(*) FROM permission_subc;
SELECT COUNT(*) FROM permission_tech;
```
