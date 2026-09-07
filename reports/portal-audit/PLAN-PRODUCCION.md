# Plan para dejar el portal listo en producción

Este documento es el runbook del cutover. Está escrito para ejecutarse en orden,
con un punto de parada y un rollback en cada paso.

---

## 0. Lo que hay que entender antes de tocar nada

**Mezclar a `main` despliega a producción. No hay paso intermedio.** Lo dejó escrito el
PR #116 y sigue siendo cierto: Vercel construye desde `main` y el alias
`gqm-api.vercel.app` apunta al último despliegue de producción. Lo mismo con el panel y
`gqmconnect.com`.

**Hoy el portal está apagado y eso es lo que os protege.** El PR #114 midió que
**0 de 432 subcontratistas tienen `ID_Role`**, y que `permission_subc` y `permission_tech`
están vacías. Ningún subcontratista ni técnico puede iniciar sesión hoy. Por eso los
hallazgos de la auditoría eran *críticos latentes*: se arman el día del alta.

**Consecuencia directa para el orden del cutover**: el código endurecido puede desplegarse
**antes** de armar el portal, y debe. Desplegar primero es seguro; armar primero no.

**El preview de Vercel apunta a la API de producción** (aviso heredado de los PR #49 y
#116). No ejercitar escrituras desde un preview.

**Hay 5 crons de Vercel** contra producción (`vercel.json`): reconciliación de Podio a las
07:00/07:20/07:40 UTC, refresco de tokens QBO los lunes a las 06:00, y la dead-letter a las
08:00. La ventana de despliegue debe evitarlos.

**Las variables de sesión: qué cambia y qué no.** La ronda 2 encontró que `jwt_handler`
congelaba `LOGIN_SECRET_KEY` y `REFRESH_SECRET_KEY` en el import (O-07). El plan decía
«comprobar en Vercel que existen, o nadie podrá iniciar sesión». Esa frase daba a entender
que el arreglo podía *causar* la caída. **Se midió, y no es así.** Se ejecutaron las dos
versiones del módulo —la de `main` y la nueva— contra los mismos seis entornos:

| entorno del despliegue | `main` (hoy en producción) | versión nueva |
|---|---|---|
| las dos claves presentes | firma y verifica | firma y verifica |
| `LOGIN_SECRET_KEY` ausente | `TypeError` de PyJWT → 500 en login, y **401 mudo** en toda petición autenticada | error que **nombra la variable** |
| `ACCESS_TOKEN_EXPIRES_MIN=''` | `ValueError` **en el import: la app no arranca** | usa el defecto (60) |
| `ACCESS_TOKEN_EXPIRES_MIN='abc'` | `ValueError` **en el import: la app no arranca** | error que nombra la variable |
| `ACCESS_TOKEN_EXPIRES_MIN='0'` | **firma tokens ya caducados** (sesión muerta al instante, sin pista) | rehúsa firmar |
| duración ausente | defecto 60 | defecto 60 |

Reproducible con `.venv/bin/python scripts/comparar_jwt_entornos.py`.

Lectura: **no hay ningún entorno en el que hoy se pueda iniciar sesión y tras el despliegue
no se pueda.** El único renglón donde la versión nueva rehúsa y `main` no es una duración
`0` o negativa, que firma sesiones ya caducadas — roto en ambos casos, solo que ahora lo
dice. Y en dos renglones la versión nueva arranca donde `main` ni siquiera levantaba.

Esto **no exime de mirar las variables** antes del paso 2 — sigue siendo lo primero que hay
que descartar si algo va mal —, pero deja de ser una compuerta que bloquea el despliegue:

```bash
vercel env ls production | grep -E 'LOGIN_SECRET_KEY|REFRESH_SECRET_KEY|EXPIRES'
```

*(Esta sesión no pudo ejecutarlo: el proxy de salida devuelve `403` en el `CONNECT` a
`gqm-api.vercel.app` y no hay `vercel` CLI autenticado. Queda documentado, no verificado —
la tabla de arriba sí está medida, en local, con las dos versiones reales del módulo.)*

**Cada repositorio construye DOS proyectos de Vercel.** Al mezclar a `main` se despliegan a
la vez:

| repositorio | proyectos que construyen |
|---|---|
| `gqm-api` | `gqm-api` (`gqm-api.vercel.app`) y `gqm-api-dev` (`gqm-api-dev.vercel.app`) |
| `gqm-panel-admin` | `gqm-panel-admin` y `gqm-panel-admin-8sfd` |

El panel llega al API por el proxy `/api` usando `PYTHON_API_BASE_URL`, una variable de
**servidor** del proyecto de Vercel del panel. Conviene saber a cuál de los dos API apunta
cada uno de los dos paneles antes de dar el cutover por bueno: es lo que decide si el panel
de producción está hablando con el API endurecido o con el otro.

---

## 1. Orden de despliegue

Cada paso tiene su verificación y su vuelta atrás. **No avanzar con un paso en rojo.**

### Paso 1 — Sanear los correos duplicados *(sin desplegar nada)*

Es prerrequisito del paso 3 y no toca código.

```bash
GQM_PROD_DATABASE_URL=... .venv/bin/python scripts/sanear_correos_duplicados.py
```

Sale en uno de tres estados:

- *«no hay correos duplicados»* → seguir al paso 2.
- *N filas saneables* → son grupos donde **una sola** fila tiene contraseña utilizable; las
  demás no pueden iniciar sesión hoy ni podrán nunca. Repetir con `--aplicar`.
- *grupos AMBIGUOS* → dos o más filas del mismo correo **con** contraseña. **El script no
  las toca a propósito**: decidir cuál es la buena es adivinar una identidad. Resolverlos a
  mano antes de continuar.

> **Rollback**: el script solo vacía `Email_Address` de filas que no pueden iniciar sesión.
> No borra ninguna fila. Para revertir, restaurar ese campo desde el respaldo.

### Paso 2 — Desplegar la API endurecida

```bash
# Con la rama ya revisada y en verde:
gh pr merge --merge   # SHA nuevo → Vercel no deduplica
```

Verificar el alias: `gqm-api.vercel.app` con `target=production` y `aliasError: null`.

> **Rollback**: Instant Rollback de Vercel al despliegue anterior. Ningún cambio de este
> despliegue toca el esquema, así que revertir el código basta.

### Paso 3 — Aplicar la migración `e9c1correo`

**No se aplica sola.** Producción va por detrás de la cabeza y hay que mirar qué arrastra:

```bash
GQM_PROD_DATABASE_URL=... .venv/bin/alembic current    # ¿en qué revisión está prod?
GQM_PROD_DATABASE_URL=... .venv/bin/alembic history    # ¿qué hay entre eso y e9c1correo?
GQM_PROD_DATABASE_URL=... .venv/bin/alembic upgrade head
```

`e9c1correo` crea tres índices únicos parciales sobre `lower(Email_Address)` en `member`,
`subcontractor` y `technician`, con `CREATE UNIQUE INDEX CONCURRENTLY` dentro de un
`autocommit_block` — **no bloquea escrituras**, igual que `c3b8d5a1f740`.

Si quedan duplicados, la migración **se para en seco con la lista** en vez de dejar un
índice inválido que Postgres marca y nadie mira. Eso no es un fallo del despliegue: es la
señal de que el paso 1 no se completó.

> **Rollback**: `alembic downgrade -1` hace `DROP INDEX CONCURRENTLY`. Sin pérdida de datos.

### Paso 4 — Desplegar el panel

Después de la API, nunca antes. Panel viejo + API nueva es un estado seguro (la API
deniega); panel nuevo + API vieja no lo es.

> **Rollback**: Instant Rollback al despliegue anterior del panel.

### Paso 5 — Armar el portal *(el paso irreversible en la práctica)*

Este es el que enciende todo lo demás. **Solo después de que 1–4 estén en verde.**

Para cada subcontratista que vaya a entrar: asignar `ID_Role`, fijar una contraseña que
cumpla la política nueva, y comunicarla por un canal fuera de la aplicación.

`scripts/cleanup_rbac.py` asigna roles en bloque a partir de listas de correos, pero **no
crea credenciales**: resuelve la mitad. La otra mitad no está automatizada — ver §3.

> **Recomendación fuerte: no armar los 432 de golpe.** Empezar por 2 o 3 subcontratistas
> reales durante una semana. Un fallo con 3 usuarios se corrige; con 432 se convierte en
> una migración de credenciales.

> **Rollback**: poner `ID_Role = NULL` en los subcontratistas armados y borrar sus filas de
> `permission_subc` / `permission_tech`. Vuelve al estado de hoy, que es el estado seguro.

---

## 2. Verificación después de cada despliegue

```bash
bash scripts/verificar_portal.sh
```

Cinco bloques, un solo veredicto: compuerta de aislamiento, matriz de permisos (8 sujetos),
fuga de campo, tests RBAC y flujo end-to-end con sus pruebas negativas. **Ninguno comprueba
solo un `200`**: cada uno puede fallar si la lógica se rompe.

Contra producción, con `rbac_matriz_43.py --entorno prod --sin-bd`, que nunca emite un
DELETE con un rol que pudiera borrar de verdad.

**Comprobación manual mínima tras el paso 5**, con un subcontratista real recién armado:

1. Inicia sesión y aterriza en su ficha.
2. Ve **sus** jobs, **sus** tareas y **sus** técnicos, y ninguno ajeno.
3. Puede crear una tarea y asignarla a un técnico suyo.
4. Su técnico inicia sesión y **ve sus tareas**, no una pantalla de «Access Denied».
5. Pedir por URL la ficha de otro subcontratista devuelve 404.
6. Cambia su propia contraseña desde `/profile`: la pantalla enseña los cuatro requisitos
   reales (10 caracteres, 3 de 4 clases, no común, no repetida) y una contraseña que no los
   cumple **no llega a salir a la red** (O-06).
7. Su técnico cambia el estado de una tarea desde el diálogo del tablero y el cambio se ve
   al recargar (R4).
8. Ninguna pantalla del portal ofrece un botón que acabe en 403 o en un rebote: ni «View
   Job», ni «view»/«Delete» en la tarjeta de técnico, ni las pestañas Opportunities,
   Certificates y Performance del panel del técnico (U-06 a U-09).
9. Una acción que falle debe **mostrar un aviso en pantalla**. Hasta la ronda 2 los avisos
   se escribían en una cola que nadie renderizaba (U-07): si algo falla en silencio, el
   `<Toaster/>` de sonner no está montado.

---

## 3. Lo que sigue faltando después de este cutover

Honestidad sobre el alcance: estos arreglos cierran los hallazgos de la auditoría. No
convierten la aplicación en un producto de portal terminado.

| Qué falta | Por qué importa |
|---|---|
| **Alta masiva** | No hay importación, ni invitación por correo, ni generación de credenciales. Armar 432 subcontratistas hoy es teclear 432 contraseñas a mano |
| **Cambio obligatorio en el primer acceso (O-03)** | La contraseña que escribe el administrador es la definitiva hasta que el usuario decida cambiarla |
| **Los dos vocabularios de rol (D6)** | El servidor usa la cookie `gqm_role`; parte del gating de UI aún lee `localStorage.user_data.role`, editable desde devtools, con un `LEAD_TECHNICIAN` que no existe en el backend. En la ronda 2 se pasaron a la cookie las guardas de `/profile`, `LeadTechnicianDashboard`, `CreateTaskDialog`, `TaskDetailsDialog` y `TechnicianCard`; el resto sigue pendiente. Mientras coexistan, cualquier guarda de UI escrita contra el vocabulario cliente es decorativa — aunque **ninguna de ellas es la que autoriza**: eso lo hace el API |
| **`Resource` por objeto en `PolicyEvaluator`** | Está implementado y ningún sitio de llamada lo usa: todos pasan `"*"`. Por eso la autorización a nivel de objeto se hace a mano en cada handler y la cobertura es desigual. Es la causa raíz de la familia P-nn |
| **`GET /podio/items/<app_type>`** | Ruta solo-JWT, sin comprobación de permiso, **no auditada**: devuelve 500 sin credenciales de Podio. Revisar con Podio configurado |
| **Deuda de datos de producción** | No se pudo medir desde la sesión de auditoría. El SQL enumerativo está en `HANDOFF-ARREGLOS.md` |
| **96 claves de traducción que no existen** | `t()` devuelve la propia clave cuando no la encuentra, así que la pantalla imprime el nombre interno: «techType *», «password *». **Ninguna es del portal** —su espacio está completo—; el resto vive en pantallas que esta auditoría no miró. Lista completa abajo |

### Las 96 claves de traducción que faltan

Detectadas con un barrido de todas las llamadas `t("…")` del panel contra
`messages/{en,es}.json`. **No es un fallo del portal**: sus dos espacios de
nombres (`subcontractors` y `dashboard`) quedaron completos — 36 claves
añadidas. Lo que queda es deuda del panel entero, y se deja enumerada porque el síntoma es visible
para el usuario: la etiqueta sale con el nombre de la clave.

| Área | Claves |
|---|---|
| `jobEstimate` | 58 |
| `jobPurchasesTab` | 15 |
| `jobTimelineTab` | 13 |
| `roles_permissions` | 6 |
| `clients` | 3 |
| `commissions` | 1 |

No se redactan aquí a propósito: es texto de producto de pantallas que no
audité (presupuestos de obra, comisiones, comunidades, proveedores), y
escribirlo sin conocer esas pantallas produciría copia mala en dos idiomas. El
listado completo, clave por clave y con el fichero donde se usa, está en
`reports/portal-audit/i18n-faltantes.txt`.

---

## 3 bis. Una consecuencia del arreglo O-05 que conviene saber

`forgot-password` devolvía el primer principal por orden de tabla, así que un
técnico que compartiera correo con un member **no podía recuperar su contraseña
jamás**. Ahora se manda un enlace por cada cuenta abierta sobre esa dirección.

Eso tiene una consecuencia que hay que decir en voz alta: **quien controle el
buzón puede reiniciar TODAS las cuentas abiertas sobre él.** Antes, con un buzón
compartido de empresa (`office@…`), quien lo leyera sólo alcanzaba la cuenta de
técnico; ahora alcanza también la de subcontratista, que en el portal ve más.

No es una regresión evitable: recuperar la contraseña por correo **es** darle esa
potestad a quien controla el correo, y que antes sólo llegara a la primera por
orden de tabla era un accidente, no un control de seguridad. Pero cambia el
consejo operativo para el alta de los 432:

> **Una dirección de correo por persona.** Un buzón de empresa compartido entre
> el subcontratista y sus técnicos convierte a cualquiera que lo lea en dueño de
> todas esas cuentas. El índice único de `e9c1correo` impide el duplicado
> *dentro* de cada tabla, no *entre* tablas.

---

## 4. Ventana y responsables

- **Ventana sugerida**: 23:00–06:00 UTC, como los cutovers anteriores. Evita los 5 crons
  (el primero a las 06:00 los lunes; el resto de 07:00 a 08:00).
- **Los pasos 1, 3 y 5 los ejecuta una persona con acceso a producción.** No están
  automatizados a propósito: los tres tocan datos o credenciales reales.
- **Los pasos 2 y 4 son mezclas de PR.**
