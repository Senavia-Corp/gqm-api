# Arreglos aplicados — de 50 filas no conformes a 0

Sesión posterior a la auditoría, sobre las mismas ramas.
`gqm-api` `a626f70` · `gqm-panel-admin` `7155887`.

## Antes y después

| Medida | Auditoría | Ronda 1 | Ronda 2 | Tras las 2 revisiones |
|---|---|---|---|---|
| Matriz de permisos (337 filas) | **50 no conformes** | 0 | 0 | **0** |
| Fuga de campo | **690 filas** | 0 | 0 | **0** |
| Bloque 4 del verificador | 102 | 106 | 162 | **176** |
| Playwright | 30 (portal solo navegación) | 47 | 58 | **61** |
| Suite completa | 753 passed | 765 passed | 806 passed | **840 passed** |
| Fallos restantes de la suite | 27 failed · 7 errors | igual | **idénticos, uno a uno, a los de `main`** |
| Flujo e2e | 8 pasos + 3 negativas | igual | igual, en verde |

Los 27 fallos y 7 errores restantes se compararon con `main` **enumerando los
identificadores de prueba, no contándolos**: los dos conjuntos son idénticos.
33 de ellos exigen credenciales de Podio, ausentes a propósito en este entorno;
el otro depende de la forma de los datos de una BD recién sembrada.

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

## Ronda 2 — lo que quedaba de la lista, con la misma disciplina

Cada uno se verificó a mano antes de tocar nada, y cada uno lleva una sonda
nueva en el arnés probada por mutación.

| ID | Qué se midió | Qué se hizo |
|---|---|---|
| **O-05** | Sembrado un member y un technician con el MISMO correo: los dos logins dan 200 con su `user_type`, y `forgot-password` resolvía siempre al member. El técnico no podía recuperar su contraseña **jamás**, y con el 200 constante nadie podía notarlo | Un enlace por principal, con el tipo de cuenta en el asunto. `Login_auth.py`, `email_service.py` |
| **O-06** | HTTP crudo contra `POST /technician/`: `'Abcdefg1'` (8) → panel ACEPTA · servidor **400**; `'Abcdefghi1'` (10) → 201. Siete pantallas pedían 8 caracteres y `/profile` **seis** | `lib/password-policy.ts`, espejo del servidor, cableado en las 8 pantallas |
| **O-07** | `jwt_handler` leía las claves con `os.getenv` en el **import**, antes de que `load_dotenv()` las pusiera en el entorno. Reproducido en tres líneas | Lectura en cada uso, y la ausencia de clave pasa a decir **qué** variable falta |
| **U-06** | Abriendo una tarea como sub: `GET /api/members` → **403** tragado por un `.catch()`, y las pestañas «Unassigned» y «GQM Member», que el API rechaza con 403 | Al portal sólo la rama que puede guardar. `TaskDetailsDialog.tsx` |
| **U-07** | El sub pulsa «Delete» y **no ocurre nada**: ni aviso, ni diálogo, ni petición. Había **dos** copias del `use-toast` de shadcn y ninguna se pintaba — el `<Toaster/>` que las renderiza no existe en el repositorio | Las dos reenvían a sonner, que sí está montado |
| **U-08** | «Delete» exige `subcontractor:update`, que el sub no tiene; «view» va a `/technicians/<id>`, que el middleware rebota. De los 4 endpoints de esa página, con el token del sub sólo responde uno | No se le ofrecen. El admin los conserva |
| **U-09** | Dos botones «View Job» y un enlace «View job» a `/jobs/<id>`: el sub acaba en su propia ficha **perdiendo la pestaña**; el técnico, en `/dashboard` con el diálogo cerrado | No se le ofrecen; ampliar `PORTAL_PREFIXES` habría cambiado un rebote por una pantalla rota a medias |
| **R4 (UI)** | El diálogo de tarea del técnico era de **solo lectura**: la única acción del rol no tenía camino en el producto | Tres botones de estado. Verificado hasta la BD |
| **Arnés** | `validar_password` no tenía **ni una** prueba y la migración de correos únicos tampoco: borrar cualquiera de las dos dejaba toda la verificación en verde | `test_politica_password.py` (21), `test_correo_unico.py` (15), `test_jwt_secreto.py` (4), todas en `verificar_portal.sh` |

### Dos lecciones de esta ronda

**El mismo defecto vivía en dos sitios y arreglar uno dejó el otro mudo.** Había
dos copias byte a byte del `use-toast`. Al arreglar la primera volvió el aviso de
la ficha del subcontratista y el de `/profile` seguía sin salir. Lo cazó una sonda
que ejercita una pantalla **distinta** de aquella donde se midió el fallo — si
hubiera probado la misma, habría dado verde con la mitad del sistema rota.

**El propio arnés destapó un fallo latente de producción.** Al añadir dos ficheros
de prueba cambió el orden de imports y 94 pruebas que no tocan nada de esto
empezaron a fallar con `TypeError: Expected a string value` desde dentro de PyJWT.
No era el arnés: era O-07. La aplicación funcionaba por suerte de orden de imports.

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
| **Los dos vocabularios de rol** | El servidor usa `gqm_role`; parte del gating de UI aún lee `localStorage.user_data.role`, editable. Unificarlos del todo es un refactor grande. Las guardas **nuevas** se escribieron contra el vocabulario del servidor, y en la ronda 2 se pasaron a la cookie las de `/profile` (4 sitios), `LeadTechnicianDashboard` y `CreateTaskDialog` |
| **`Resource` por objeto en `PolicyEvaluator`** | Implementado y sin usar: todos los sitios pasan `"*"`. Es la causa raíz de la familia `P-nn`. Decisión de arquitectura |
| **`GET /podio/items/<app_type>`** | Ruta solo-JWT, **no auditada**: devuelve 500 sin credenciales de Podio |


---

# Las dos revisiones adversariales

Sobre el diff de cada ronda se lanzó una revisión adversarial: varios revisores
independientes, una dimensión cada uno, con el encargo de **encontrar fallos
reales y medirlos**, no de opinar sobre el código. Devolvieron **24 hallazgos en
la segunda ronda, todos ejecutados**. Lo que sigue es lo que encontraron en MIS
arreglos, que es la parte que importa.

## Tres veces arreglé un fallo y metí otro

- **O-05.** El arreglo de la recuperación de contraseña mandaba un correo por
  principal. Eso **triplicó** un agujero que ya existía: la clave del limitador
  se construía como `_client_key(f"forgot|{email}")`, y el `.strip()` de dentro
  recorta los extremos de `"forgot| ana@x.com"`, que no tiene ninguno. Bastaba
  un espacio para abrir un cupo nuevo — y ahora cada petición mandaba 3 correos
  en vez de 1. Medido por el revisor: 27 correos SMTP reales.
- **O-07.** Arreglando que las claves JWT se congelaran en el import, hice más
  silencioso otro fallo: `ACCESS_TOKEN_EXPIRES_MIN='abc'` pasó a caer al
  defecto de 60 minutos sin decir nada, cuando el código anterior reventaba al
  arrancar. Es justo la lección que O-07 venía a dejar escrita.
- **U-06.** Filtré las pestañas de asignación para dejarle al portal sólo la
  suya… y el manejador seguía limpiando los tres ids, así que **el único botón
  que le quedaba le borraba la asignación**.

## Y una sonda mía no podía fallar

`test_jwt_secreto.py` lanzaba el subproceso **sin `env=`**, así que heredaba el
entorno del padre — y `verificar_portal.sh` corre antes un fichero que importa
`main` → `load_dotenv()`. El hijo veía la clave, el `os.getenv` del import la
encontraba, y **el código roto también pasaba**. Aislada daba `2 failed`; en el
orden del arnés, `1 failed, 35 passed`. Ahora el hijo recibe un entorno saneado
y hay una prueba que guarda a la prueba.

La misma clase de fallo apareció dos veces más:

- la sonda de U-07 afirmaba que existía un nodo visible, no lo que decía: con el
  adaptador tirando **todo** el texto del aviso seguía verde;
- la sonda de U-08 tenía congelado un fallo **como expectativa** — esperaba el
  botón «view» en minúscula, que era el nombre de una clave de traducción sin
  traducir. Al añadir la clave se puso roja, que es lo que tenía que hacer.

## Cuatro fallos apilados en una sola pantalla

La ficha de técnico bajo un subcontratista tenía cuatro, cada uno tapando al
siguiente: `params` es una promesa en Next 16 y se declaraba como objeto plano
(la ficha pedía `/api/technician/undefined`); al llegar los datos, un
`.map((t) => …)` tapaba al traductor; detrás, un `Job_status` NULL tiraba la
página; y al final el botón «Save Password» sólo dejaba el campo preparado —
quien lo pulsaba se iba creyendo que la contraseña estaba cambiada.

Ninguno se veía porque el primero impedía que el resto llegara a ejecutarse.
Es el mismo patrón que U-01: quitas un callejón sin salida y aparece el
siguiente.

## La compuerta antes de mezclar: medida, no razonada

El plan de producción decía «comprobar en Vercel que existen `LOGIN_SECRET_KEY`
y `REFRESH_SECRET_KEY`; si falta alguna, nadie podrá iniciar sesión». Escrito
así daba a entender que el arreglo de O-07 podía **causar** esa caída, y eso era
una hipótesis, no un hecho: nadie la había ejecutado.

`scripts/comparar_jwt_entornos.py` carga las dos versiones del módulo —la de
`origin/main` y la de esta rama— en intérpretes nuevos, con seis entornos
construidos a mano, y distingue fallar **en el import** (la aplicación no
levanta) de fallar **al usar** (levanta y el error sale en `/auth/login`).

| entorno | `main` | esta rama |
|---|---|---|
| las dos claves presentes | firma y verifica | firma y verifica |
| sin `LOGIN_SECRET_KEY` | `TypeError` de PyJWT | `ClaveJWTAusente`, que la nombra |
| `ACCESS_TOKEN_EXPIRES_MIN=''` | **`ValueError` en el import** | defecto 60 |
| `ACCESS_TOKEN_EXPIRES_MIN='abc'` | **`ValueError` en el import** | error que la nombra |
| `ACCESS_TOKEN_EXPIRES_MIN='0'` | firma tokens ya caducados | rehúsa |
| duración ausente | defecto 60 | defecto 60 |

No hay ningún entorno en el que hoy se pueda entrar y con esta rama no. El único
renglón donde la rama rehúsa y `main` no es una duración `0`, que firma sesiones
muertas al instante — roto en los dos casos, sólo que ahora lo dice.

**La primera versión de ese script estaba amañada a mi favor.** Copiaba a un
directorio neutral sólo la versión de `main` y leía la de esta rama desde su
sitio en el repositorio; como `decouple` busca el `.env` subiendo desde el
fichero que lo llama, la rama encontraba el `.env` de desarrollo y el renglón
«sin `LOGIN_SECRET_KEY`» salía **«firma y verifica»**. Con esa medición llegué a
escribir en el plan de producción una tabla que decía lo contrario de lo que el
script imprimía. Copiando **las dos** versiones fuera del repositorio, el
renglón pasó a `ClaveJWTAusente`, que es la verdad y además lo que el plan ya
afirmaba.

Es el mismo error de la sección anterior, cometido otra vez y en la herramienta
que existía para no cometerlo: **un banco de pruebas que no puede dar un
resultado desfavorable no está midiendo nada.**

De paso queda descartada la alarma que lo destapó: el `.env` está en
`.gitignore` y Vercel construye desde el repositorio, así que **nunca viaja al
despliegue**; y `decouple` da precedencia a `os.environ` sobre el fichero. En
producción ese respaldo no existe y no puede sustituir en silencio una clave
ausente por una de desarrollo.

## Lo que esto dice del método

Las dos revisiones encontraron cosas que yo no vi **en mi propio trabajo**, y en
particular pruebas que daban verde sobre código roto. Sin ellas, la entrega
habría salido con tres regresiones y con un arnés que las tapaba. La regla que
más rindió no fue ninguna técnica: fue **verificar cada hallazgo a mano antes de
tocar nada**, y **sabotear cada arreglo después** para comprobar que la sonda lo
ve.
