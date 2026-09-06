# Fase 0 — Entorno, compuerta y siembra

## Punto de partida

| Repositorio | Rama | Commit | Estado inicial |
|---|---|---|---|
| `gqm-api` | `claude/gqm-portal-rbac-audit-2yckin` | `6e7a67e` | idéntica a `origin/main` |
| `gqm-panel-admin` | `claude/gqm-portal-rbac-audit-2yckin` | `199b15b` | idéntica a `origin/main` |

## El entorno no es el que asume el encargo

El `PROMPT-MAESTRO` está escrito para la máquina local. Esta sesión es un contenedor
remoto y efímero. Lo que falta, y qué se hizo en su lugar:

| El encargo asume | Aquí | Sustitución |
|---|---|---|
| `~/gqm-work/{api,panel}` | `/home/user/gqm-api`, `/home/user/gqm-panel-admin` | ruta |
| `~/Documents/GitHub/gqm-api-fixes/.env` | no existe | `.env` sintetizado (abajo) |
| `~/Documents/GitHub/gqm-api-fixes/run_local.py` | no existe | `flask --app main:app run --host 127.0.0.1 --port 8000` |
| `~/outputs/gqm-entrega/dev-env/verificar-aislamiento.sh` | no existe | aislamiento **estructural**, no verificado a posteriori (§Aislamiento) |
| `~/outputs/gqm-tasks-audit/` (H1–H12) | no existe | reconstruido desde los PR #114/#116 → ver `INFORME` |
| `~/Documents/GQM_repos/gqm-tests` | no existe | el panel ya trae `tests/rbac` (30 tests) |
| MCP `gqm-prod-readonly` | **no existe** | Fase 3.3 no ejecutable → SQL en el `HANDOFF` |
| agentes `ui-qa` / `browser-qa` | no existen | Playwright + Chromium en `/opt/pw-browsers` |
| Neon develop | **TCP 5432 bloqueado** | Postgres 16 local en loopback |

### El 5432 está cerrado — medido, no supuesto

```
neon.tech:443        -> OPEN
api.github.com:443   -> OPEN
neon.tech:5432       -> TimeoutError
google.com:5432      -> TimeoutError
```

Solo sale HTTPS/443 por el proxy. Ninguna base de datos externa —Neon develop
incluida— es alcanzable con psycopg2. **Postgres local no es una preferencia: es la
única opción.** Esto es lo que obliga a tocar la compuerta (§siguiente).

## Aislamiento: estructural, no declarativo

El `.env` de esta sesión **no contiene una sola credencial real**. No es que se hayan
apuntado a un entorno de pruebas: es que no existen.

```
APP_ENV=test
DATABASE_URL=postgresql://gqm_audit:***@127.0.0.1:5432/gqm_portal_audit
Podio app ids presentes: 0
¿apunta a Neon/prod?     0
```

`APP_ENV=test` hace que `src/config.py:186-195` solo avise por las credenciales de
Podio ausentes en vez de exigirlas. El clúster escucha en `localhost` (por defecto de
Debian, `listen_addresses` sin fijar), así que **no hay ruta de red desde esta base de
datos hacia ningún sitio**. Es una garantía más fuerte que la que daba el `.env` de
develop, que sí tenía credenciales vivas.

`.env` y `.venv/` están cubiertos por `.gitignore` (`:4` y `:10`); `git status` lo
confirma. Ninguno se empuja.

## La compuerta — el único cambio en código de producción

### Por qué

Seis ficheros repetían esta línea:

```python
if "ep-sparkling-sound" not in config("DATABASE_URL", default=""): sys.exit(...)
```

Es una allowlist por **subcadena del DSN entero**, no una propiedad de seguridad.
Rechaza un Postgres en loopback —estrictamente más seguro que Neon develop— y a la vez
acepta cosas que no debería. Sin ampliarla, en este contenedor **no arranca ni un solo
test**: `tests/conftest.py` usa `sys.exit`, que mata la sesión entera de pytest.

Esto es una desviación consciente de la §7 del encargo («no tocar `conftest.py` ni la
compuerta»), autorizada por el usuario tras exponerle la alternativa (auditoría solo
estática). Se declara aquí con su diff, como manda la regla de oro 6.

### Qué se hizo

Un helper único, `src/utils/db_guard.py`, que **parsea el host** en vez de buscar una
subcadena. Los seis call-sites lo importan. Nunca se elimina la rama de develop ni el
rechazo de producción; se añade la rama de loopback.

| Fichero | Cambio |
|---|---|
| `src/utils/db_guard.py` | **nuevo** — `classify_database_url()` (pura) y `require_dev_database()` |
| `tests/unit/test_db_guard.py` | **nuevo** — 21 tests, el contrato de aceptación/rechazo |
| `tests/conftest.py` | 9 líneas → importa el helper |
| `scripts/seed_rbac.py` | ídem |
| `scripts/cleanup_rbac.py` | ídem |
| `scripts/audit_tasks_matrix.py` | ídem — **además pasa de `assert` a `sys.exit`**: las guardas viejas desaparecían con `python -O` |
| `scripts/sanear_tasks.py` | **sexto sitio, no previsto en el plan.** Cambio quirúrgico: misma semántica, host parseado. Nunca comprobó `APP_ENV` y **sigue sin hacerlo**; loopback ahora corre donde antes abortaba. Su `--permitir-produccion` queda intacto. |
| `scripts/e2e_podio_sync.py` | **no se toca**: exige Podio real, que aquí no existe |
| `scripts/rbac_spec_produccion.py` | **no se toca**: exige host de producción a propósito |

### El cambio es más estricto que el original en tres frentes

1. **Rechaza lo que la versión vieja aceptaba.**
   `postgresql://u:p@host-de-produccion/ep-sparkling-sound` pasaba la comprobación por
   subcadena —el marcador estaba en el nombre de la base de datos, no en el host—. Ahora
   se rechaza.
2. **Rechaza el `?host=` engañoso.** libpq da prioridad al `host` de la query sobre el de
   la autoridad, así que `postgresql://u:p@127.0.0.1/db?host=prod.neon.tech` conecta a
   producción. El helper recoge `?host=` y `?hostaddr=` y exige que **todos** los hosts
   sean loopback.
3. **Exige `.neon.tech`** para la rama de develop, así que
   `ep-sparkling-sound.atacante.example` ya no cuela.

Y conserva un caso que la comprobación por host se habría cargado: Neon identifica el
endpoint en `?options=endpoint%3D...` con drivers sin SNI (psycopg2 entre ellos). Mirar
solo el host habría **rechazado un DSN de develop legítimo** — una regresión. Está
cubierto por test.

### Prueba de mutación — sin esto, «ampliada» y «desactivada» son indistinguibles

| DSN | conftest | seed | cleanup | audit_tasks | sanear |
|---|---|---|---|---|---|
| Neon **producción** (`ep-morning-credit`) | ABORTA | ABORTA | ABORTA | ABORTA | ABORTA |
| host prod con `127.0.0.1` en la query | ABORTA | ABORTA | ABORTA | ABORTA | ABORTA |
| loopback pero `APP_ENV=production` | ABORTA | ABORTA | ABORTA | ABORTA | pasa¹ |

¹ `sanear_tasks.py` nunca comprobó `APP_ENV`; no se le añadió para no ampliar el cambio
más allá de lo aprobado. Queda anotado como deuda en el `HANDOFF`.

Las 21 filas del contrato completo están en `tests/unit/test_db_guard.py` y se ejecutan
en cada corrida de pytest.

## Base de datos

Clúster Debian ya inicializado en `/var/lib/postgresql/16`, arrancado con
`pg_ctlcluster 16 main start`. Rol `gqm_audit`, base `gqm_portal_audit`.

`alembic upgrade head`: **64 revisiones aplicadas sobre BD virgen, sin un solo fallo**,
hasta la cabeza única `f8b4d2e60a17`. Las migraciones de datos se comportaron como
no-ops sobre tablas vacías, como debían:

```
[a7c1f3e94b20] filas con podio_app_year corregido: 0
[sanear] con volcado: antes=0 despues=0
[rescate] no hay filas que rescatar; nada que hacer
```

## Sujetos y objetos sembrados — IDs reales

`scripts/seed_rbac.py` siembra usuarios, roles y políticas **y nada más**: ni un job, ni
una tarea, ni un enlace. Las corridas anteriores se apoyaban en los datos que ya había en
Neon develop. Sobre una base virgen hay que construir el mundo entero, y de eso se ocupa
`scripts/seed_portal_audit.py` (nuevo, idempotente, con `--limpiar`).

| Sujeto | Correo | ID | Nota |
|---|---|---|---|
| `full_admin` | `admin-dev@senavia-test.com` | `MEM60001` | rol Full Admin |
| `gqm_member` | `member-dev@senavia-test.com` | `MEM60002` | rol GQM Member |
| `subcontractor` | `sub-dev@senavia-test.com` | `SUBC60001` | sub A |
| **`sub_B`** | `sub-b-dev@senavia-test.com` | `SUBC60002` | **ningún job en común con A** |
| `technical` | `tech-dev@senavia-test.com` | `TEC60001` | **bajo `SUBC60001`** (ver abajo) |
| **`tech_de_sub_B`** | `tech-b-dev@senavia-test.com` | `TEC60002` | bajo `SUBC60002` |
| **`tech_independiente`** | `tech-indep-dev@senavia-test.com` | `TEC60003` | **sin subcontratista** |
| `anonimo` | — | — | sin token |

| Objeto | ID | Pertenece a |
|---|---|---|
| job de A | `QID-I60001` | `SUBC60001` + `TEC60001`, cliente `CLI60001`, gestora `PMC60001` |
| job de B | `PTL-I60001` | `SUBC60002` + `TEC60002`, cliente `CLI60002`, gestora `PMC60002` |
| job sin asignar | `PAR-I60001` | solo `TEC60003`, cliente `CLI60003` |
| tarea de tech A | `TSK60001` | propia de A |
| tarea sin asignar de A | `TSK60002` | job A, sin técnico |
| tarea de tech B | `TSK60003` | propia de B — **«ajena» para A** |
| tarea huérfana | `TSK60004` | job C, sin técnico ni sub |
| tarea de tech indep. | `TSK60005` | job C |

Además: adjuntos `ATT60001`–`ATT60004` (con `access_level` `internal` y `technicians`),
certificados `CERT60001`/`CERT60002`, órdenes `ORD60001`/`ORD60002`, y filas de
`tlactivity` por job, por sub y por cliente.

### Hallazgo de partida: el arnés previo nunca probó la relación sub↔técnico

`scripts/seed_rbac.py:242` llama a `upsert_technician` **sin fijar nunca
`ID_Subcontractor`**. Es decir: `tech-dev@senavia-test.com` era un técnico
**independiente**. El sujeto `technical` de la matriz del PR #116, de
`audit_tasks_matrix.py` y de los 30 tests de Playwright del PR #49 **nunca colgó de un
subcontratista**.

Consecuencia: la relación sub↔técnico —la que sostiene entera la regla R3, «el sub asigna
tareas a *sus* técnicos»— no la ha ejercitado nunca ninguna prueba automática. El
sembrado de esta auditoría lo corrige (`TEC60001` cuelga de `SUBC60001`) y separa el caso
independiente en un tercer técnico explícito.

### Valores centinela — por qué no hay NULLs en los campos sensibles

Todo campo sensible lleva un valor reconocible, nunca NULL. Con NULL, una respuesta de
portal sin datos financieros no probaría nada: sería imposible distinguir «el endpoint
filtra el campo» de «la columna estaba vacía». Los centinelas llevan el prefijo del
propietario (`A-`, `B-`, `C-`), así que al encontrarlos en una respuesta se sabe además
**de quién** es la fuga.

```
Gqm_formula_pricing      = 4444.44      Gqm_target_return   = 7777.77
Gqm_final_sold_pricing   = 9999.99      Acc_receivable      = 1414.14
Project_location         = '<A|B|C>-DIRECCION-CALLE-FALSA-123'
Additional_detail        = '<A|B|C>-NOTA-INTERNA-GQM'
Client.Text              = '<A|B|C>-NOTA-INTERNA-SOBRE-EL-CLIENTE'
ParentMgmtCo.President_* = '<A|B|C>-PRESIDENTE-CONTACTO'
```

## Línea base de tests

Los 7 sujetos autentican contra `127.0.0.1:8000` y reciben un JWT con el `sub` y el
`role` correctos.

| Conjunto | Resultado |
|---|---|
| **Tests RBAC** (`test_rbac_matrix`, `test_portal_scoping`, `test_tasks_scoping`, `test_security_gates`, `test_tasks_auditoria_seguridad`, `test_db_guard`) | **102 passed, 0 failed** |
| Suite completa | 753 passed · 27 failed · 7 errors · 7 skipped |

**Los 34 fallos restantes son todos de ficheros que exigen credenciales de Podio**
(`test_paridad_endpoints`, `test_bloqueo_escritura_podio`, `test_guarda_entorno_podio`,
`test_func_hooks`, `test_cutover_registro_por_evento`, los de webhook). No son
regresiones del cambio de compuerta: son la consecuencia directa del aislamiento, que
niega esas credenciales a propósito.

> **No se puede comparar contra la línea base de 384 que declara el PR #116.** Aquella se
> midió contra Neon develop con datos de forma productiva; esta corre sobre una base
> virgen sembrada. Son cifras distintas y decir lo contrario sería inventarse una
> equivalencia. Lo que sí se puede afirmar, y es lo que importa: **los 102 tests de RBAC
> pasan**, y ninguno de los fallos toca el código de permisos.

Comprobado además que **ninguna petición salió hacia Podio**: los tests que mencionan
«POST a Podio» sustituyen `requests.post/put/delete` con `monkeypatch` por una función
que lanza `AssertionError` **antes** de abrir conexión. Es su red de seguridad, no una
llamada real.

## Cómo reproducir

```bash
pg_ctlcluster 16 main start
cd /home/user/gqm-api
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed_rbac.py
.venv/bin/python scripts/seed_portal_audit.py          # --limpiar para deshacer
.venv/bin/python -m flask --app main:app run --host 127.0.0.1 --port 8000 --no-reload
```
