# Fase 7 — Acceso y onboarding

Cómo llega un subcontratista o un técnico real a tener credenciales, y si ese camino
soporta dar de alta a los 432 subcontratistas que ya están cargados.

## 1. El camino de alta

El admin crea al técnico o al subcontratista desde el panel y **escribe él mismo** la
contraseña (`Password` + `Confirm Password`). No hay invitación por correo, no hay token de
activación, no hay contraseña temporal generada por el sistema. La credencial nace conocida
por el administrador y viaja al usuario por un canal que la aplicación no controla.

## 2. Hallazgos

| ID | Sev | Qué |
|---|---|---|
| **O-01** | **S2** | **Cero validación de fuerza de contraseña.** `POST /technician/` acepta `"1"`, `"abc"`, `"password"` y `"12345678"` — las cuatro devuelven **201**. No hay longitud mínima, ni comprobación de diccionario, ni de complejidad, en servidor. |
| **O-02** | **S2** | **Correos duplicados permitidos, y la segunda cuenta queda inalcanzable.** Dos técnicos con `audit-duplicado@senavia-test.com` se crean sin error (`TEC60008`, `TEC60009`). El login resuelve **siempre** al primero: `sub=TEC60008`. La segunda cuenta existe, ocupa su fila y **nadie puede entrar en ella jamás**. No hay índice único sobre `Email_Address` en `technician`, `subcontractor` ni `member` — verificado contra `pg_indexes`. |
| **O-03** | **S3** | **No se obliga a cambiar la contraseña en el primer inicio de sesión.** La respuesta de `/auth/login` trae `access_token`, `refresh_token`, `token_type`, `user_data`, `user_id`, `user_type` y **ningún indicador** de contraseña temporal o cambio pendiente. La contraseña que escribió el administrador es la definitiva hasta que el usuario decida cambiarla. |

## 3. Lo que sí está bien resuelto

- **La recuperación de contraseña no filtra si la cuenta existe.** `/auth/forgot-password`
  responde `200 {"message":"If the email exists, a reset link was sent"}` tanto para
  `sub-dev@senavia-test.com` como para un correo inventado. Es la respuesta correcta.
- **El límite de intentos funciona.** Ocho intentos fallidos seguidos:
  `401, 401, 401, 401, 429, 429, 429, 429`. Corta al quinto, por `(IP, correo)`.
- **La vida del token de acceso es de 60 minutos**, con refresh aparte. Los claims son los
  mínimos: `sub`, `role`, `iat`, `exp` — sin permisos embebidos, así que revocar una política
  surte efecto en la siguiente petición y no al expirar el token.

## 4. El alta masiva de los 432 subcontratistas

El PR #114 dejó medido el punto de partida: **0 de 432 subcontratistas tienen `ID_Role`**, y
`permission_subc` / `permission_tech` están vacías. Es decir, hoy **ningún** subcontratista
de producción puede iniciar sesión, y ese es justamente el motivo de que los hallazgos de
esta auditoría estén latentes y no explotados.

Para armar el portal hay que, por cada uno de los 432: asignar `ID_Role`, fijar una
contraseña y comunicarla. Con el camino actual eso significa **432 contraseñas escritas a
mano por un administrador**, sin fuerza mínima, sin caducidad y sin cambio obligatorio en el
primer acceso. La aplicación **no soporta hoy un alta masiva**: no hay importación, ni
invitación, ni generación de credenciales.

`scripts/cleanup_rbac.py` asigna roles en bloque a partir de listas de correos codificadas
en el propio fichero (`:61-83`), pero **no crea credenciales**: resuelve la mitad del
problema.

Y O-02 convierte el volumen en un riesgo real: entre 432 registros importados de Podio, un
correo repetido no da error — crea una cuenta muda que consume el correo y a la que nadie
podrá entrar nunca. Sin índice único, ese fallo es silencioso.

## 5. Dos huecos del modelo que afectan al acceso

- **El técnico no tiene rol.** `Technician` no tiene columna `ID_Role`
  (`TechnicianModel.py:20-51`); su política cuelga directa de `permission_tech`. Por eso
  `/auth/login` devuelve `role_detail = None` para un técnico (`Login_auth.py:177`) y
  `/auth/me` **no tiene rama de técnico** (`:330-368`, que termina en
  `401 "Invalid role in token"`).
- Ese `role_detail = None` es lo que `lib/role-map.ts` traduce, y explica por qué el panel
  necesita su propio vocabulario para el técnico. Está en la raíz de la divergencia
  documentada en la Fase 6.

## 6. Lo no auditado aquí

- **El envío real del correo de recuperación.** El endpoint responde 200 sin credenciales
  SMTP configuradas; que la respuesta sea correcta no prueba que el correo salga. Queda como
  no auditado.
- La caducidad y el uso único del token de restablecimiento no se ejercitaron end-to-end por
  el mismo motivo.
