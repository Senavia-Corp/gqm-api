# Fase 6 — Interfaz de portal

Medido contra el panel real (`next dev -p 3100`) apuntando a la API local, con sesión de
cookie httpOnly. Capturas por rol en `capturas/`.

## 1. Dónde aterriza cada rol y qué menú se le pinta

| Rol | Aterriza en | Sidebar pintado | Enlaces que **funcionan** |
|---|---|---|---|
| `full_admin` | `/dashboard` | 11 ítems | 11 / 11 |
| `gqm_member` | `/dashboard` | 8 ítems | 8 / 8 |
| `subcontractor` | `/subcontractors/SUBC60001` | `/dashboard`, `/jobs`, `/subcontractors/SUBC60001` | **1 / 3** |
| `technical` | `/subcontractors` | `/dashboard`, `/jobs` | **0 / 2** |
| `tech_independiente` | `/subcontractors` | `/dashboard`, `/jobs` | **0 / 2** |

`/dashboard`, `/jobs` y `/settings` devuelven **307** a los roles de portal:
`middleware.ts:19-24` no incluye ninguno en `PORTAL_PREFIXES`, mientras
`Sidebar.tsx:66-75` sí los pinta. **El menú promete lo que el middleware niega.**

## 2. El técnico no puede usar la aplicación — U-01, S3

Es el hallazgo que bloquea la entrega para ese rol.

Un técnico inicia sesión y aterriza en `/subcontractors`, que es la **lista interna de
subcontratistas**. No tiene `subcontractor:read`, así que la pantalla que ve es:

> **Access Denied** — You do not have the required permissions (`subcontractor:read`) to
> view this section. · botón **Return to Dashboard**

Y ese botón lleva a `/dashboard`, que `middleware.ts:92-105` devuelve a `/subcontractors`,
que vuelve a ser **Access Denied**. Es un bucle cerrado: el único botón de la pantalla de
error conduce a la misma pantalla de error.

`homeFor()` en `tests/rbac/helpers.ts:44` **codifica esta landing como la esperada**, así
que los 30 tests del PR #49 pasan en verde sobre una pantalla de acceso denegado. Un test
que solo comprueba la URL de destino no ve que el destino sea inservible.

**Veredicto R6 para el técnico: no puede completar su trabajo.** No ve sus tareas, no tiene
ninguna ruta de navegación viva y el único control que se le ofrece cierra un bucle.

## 3. El subcontratista no tiene forma de crear una tarea — U-02, S3

`/subcontractors/<propio>?tab=tasks` **sí** lista sus tareas (`TSK60001`, `TSK60002`,
`TSK60018`, con técnico, estado y prioridad). Pero **no existe el botón «New Task»**.

La causa: el botón se condiciona a `hasPermission("subcontractor:update")`
(`app/subcontractors/[id]/page.tsx:1322-1330`), y la política `subcontractor-portal` concede
`subcontractor:read`, **no** `subcontractor:update`.

Resultado: la regla **R3** —«el sub crea tareas y las asigna a sus técnicos»— está permitida
en la API (`tasks:create`, verificado: 201) y **no tiene ningún camino en la interfaz**. La
regla de negocio existe en el backend y no se puede ejercer desde el producto.

## 4. El BFF es una tubería, pero la API sí defiende

`middleware.ts:31-45` devuelve en la rama `/api/*` **antes** de toda lógica de rol, así que
ni `FULL_ADMIN_ONLY` ni `PORTAL_PREFIXES` protegen el BFF; 105 handlers reenvían el bearer
sin comprobar nada. Medido con una sesión de subcontratista:

```
/api/members?limit=200      → 403   Forbidden: member:read
/api/commission             → 403   Forbidden: commission:read
/api/roles                  → 403   Forbidden: role:read
/api/permissions            → 403   Forbidden: permission:read
/api/backend/member         → 403   /api/backend/permission → 403
```

**La tesis «el BFF es un colador» es cierta en la estructura y falsa en el efecto para estas
rutas**: la API es el límite de confianza real y aquí funciona. Conviene decirlo con
precisión y no apuntarlo como vulnerabilidad.

Donde sí importa es en el reverso: **el BFF no añade ninguna defensa en profundidad sobre
las rutas que sí filtran.** Con la misma sesión de navegador:

```
/api/backend/technician/TEC60002      → 200  ← Gqm_formula_pricing, "Document", B-NOTA-INTERNA-GQM
/api/backend/subcontractors/SUBC60002 → 200  ← Gqm_formula_pricing, ORD60002, B-NOTA-INTERNA-GQM
/api/backend/tlactivity/job/PTL-I60001 → 200
```

`app/api/backend/[...path]/route.ts` es un comodín sin lista blanca para cualquier ruta y
cualquier verbo. **Los hallazgos P-01, P-04 y P-05 no requieren un cliente HTTP ni robar un
token: se explotan con una línea de JavaScript en la consola del navegador de un
subcontratista que ha iniciado sesión con normalidad.** Eso es lo que sube su severidad.

## 5. URL directa a lo prohibido

| Ruta pedida por un subcontratista | Resultado |
|---|---|
| `/members`, `/commissions`, `/roles-permissions` | **307 → `/dashboard`** ✅ |
| `/dashboard`, `/jobs`, `/settings` | 307 → su propia ficha (enlaces muertos del menú) |
| **`/subcontractors/SUBC60002`** (ficha de otro sub) | **200, y muestra los datos de sub_B** 🔴 |

`middleware.ts:96` compara el prefijo `/subcontractors` **sin comprobar el id**, y la única
guarda de pertenencia de la página es para `LEAD_TECHNICIAN`
(`app/subcontractors/[id]/page.tsx:459-470`), un rol que no existe en el backend. Es la
manifestación en interfaz del hallazgo **P-05**.

## 6. Acciones prohibidas visibles

| Control | ¿Visible al sub? | Debería |
|---|---|---|
| **Sync Podio** (interruptor) | **sí** | no — sincronizar con Podio no es una acción de portal |
| Add Technician | no | correcto |
| Delete | no | correcto |
| New Task | no | **debería estar** (ver U-02) |

## 7. Los dos vocabularios de rol

- **Servidor**: cookie `gqm_role` ∈ `{full_admin, gqm_member, subcontractor, technical, none}`
  (`lib/role-map.ts:6`), derivada en el BFF a partir de `/auth/me`.
- **Cliente**: `localStorage.user_data.role` ∈ `{FULL_ADMIN, GQM_MEMBER, LEAD_TECHNICIAN,
  SUBCONTRACTOR}` (`lib/types.ts:526`), escrito por el navegador en
  `app/login/page.tsx:58-65`.

Casi todo el gating de UI lee **el segundo**, que es editable desde devtools.
`LEAD_TECHNICIAN` solo existe en ese vocabulario: **cero coincidencias en todo el
repositorio del backend**, incluidos los objetos git. Es un rol fantasma que sin embargo
gobierna condiciones de render reales (`JobTechniciansTab.tsx:18`,
`app/subcontractors/[id]/page.tsx:459-470`).

Consecuencia práctica: la única guarda de pertenencia de la ficha de subcontratista está
escrita para un rol que ningún usuario puede tener. Por eso no protege a nadie.

## 8. Estados vacíos y móvil

- La ficha del sub muestra vacíos explicados («No coverage areas added yet», «No leader
  assigned», contadores a 0). Correcto.
- El «Access Denied» del técnico es un vacío **no** explicado: no dice qué debería hacer ni
  ofrece una salida válida.
- Capturas a 390×844 en `capturas/*-movil.png`: el sidebar colapsa a *drawer* y la ficha del
  sub se reordena en una columna sin desbordes.

## Veredicto de la Fase 6

| Rol | ¿Puede completar su trabajo sin que nadie le explique la app? |
|---|---|
| `subcontractor` | **Parcialmente.** Ve sus jobs, sus tareas y sus técnicos, pero no puede crear ni asignar tareas, y 2 de sus 3 enlaces de menú no llevan a ninguna parte. |
| `technical` | **No.** Aterriza en «Access Denied» y no tiene ninguna ruta de navegación viva. |
| `tech_independiente` | **No.** Idéntico al anterior. |
