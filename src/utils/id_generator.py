"""Generacion de IDs con prefijo: PREFIX + ultimo_digito_año + contador.

Ejemplo: SUP50001 -> SUP (prefijo), 5 (año 2025), 0001 (contador). El contador
arranca con 4 cifras pero NO esta limitado a 4: al pasar de 9999 crece a 5
(...10000).

HISTORIA DE LOS DOS FALLOS DE ESTA FUNCION
===========================================

1) EL DESBORDE (arreglado en 1bb0de7). La version original buscaba el ultimo ID
   con `ORDER BY id DESC`, es decir en orden LEXICOGRAFICO:

       "TLA69999"  >  "TLA610000"      <- como texto, '9' > '1'

   Una vez existia TLA610000 el generador seguia viendo TLA69999 como "el
   ultimo" y devolvia un ID YA EXISTENTE, para siempre. En produccion dejo
   `tlactivity` sin escribir desde el 20-may-2026: el IntegrityError lo absorbe
   el `except` de log_activity y fallaba en silencio. 88 dias de auditoria
   perdidos. Por eso el maximo se calcula por el SUFIJO NUMERICO, no por texto.

2) LA CARRERA (lo que arregla este cambio). El arreglo de 1bb0de7 seguia
   haciendo `SELECT` de todos los IDs del prefijo+año y `max+1` EN PYTHON:
   check-then-act sin lock. Dos peticiones simultaneas leen el mismo maximo y
   proponen el mismo ID. Medido en DEV el 21-ago-2026:

       2 sesiones -> 0 colisiones     5 sesiones -> 3 colisiones (60% perdido)
       3 sesiones -> 1 colision       8 sesiones -> 6 colisiones (75% perdido)

   El techo real eran ~2 inserciones concurrentes. Y no es un problema de los
   adjuntos: la carrera vive AQUI, asi que los ~30 prefijos (ORD, EST, TLA, FD,
   FDI...) estaban igual de expuestos.

   Evidencia en produccion (podio_failed_syncs id=7..11): cinco entregas del
   mismo item en 1,6 s, todas con
       duplicate key value violates unique constraint "attachments_pkey"

COMO SE ARREGLA
===============
Un contador por (prefijo, digito de año) en la tabla `id_counters`, incrementado
con `UPDATE ... RETURNING` en una CONEXION APARTE que commitea al instante.

Lo decisivo es el TIEMPO DE RETENCION DEL LOCK. Un `pg_advisory_xact_lock` —que
fue mi primera idea— se libera al COMMIT de la transaccion que lo tomo, no al
salir de esta funcion. Y la transaccion del webhook de adjuntos contiene dos
`requests.get` a Podio y una subida a Cloudinary: seria un lock GLOBAL de
escritura retenido segundos, e indefinidamente si Podio se cuelga. La primitiva
correcta en el sitio equivocado.

Con la conexion autonoma, el row lock dura UNA SENTENCIA y no depende de cuanto
dure la transaccion del llamador. Por eso esta funcion puede quedarse donde
esta, en mitad de la transaccion larga, sin tocar nada alrededor.

Verificado con 8 hilos simultaneos contra la misma clave: 8 valores distintos,
0 colisiones, 0 errores.

SEMBRADO PEREZOSO
=================
`id_counters` nace vacia. La primera vez que se pide un ID de un par
(prefijo, año) el UPDATE afecta 0 filas y se siembra desde el maximo real de la
tabla, UNA sola vez en la vida de ese contador. Efecto util: el cambio de
digito de año es automatico (el 1-ene-2027 el contador de ('ATT','7') no existe,
se siembra desde 0 y sale ATT70001). Sin tarea manual anual, que es justo lo que
descarta ~30 secuencias de Postgres en un repo que ya perdio 88 dias de
auditoria por un caso borde del contador.

DEGRADACION
===========
Si el dialecto no es PostgreSQL (los 6 tests de desborde corren sobre
`sqlite://`) o si el camino autonomo falla por lo que sea, se cae al algoritmo
anterior de max+1. Un fallo del contador NO puede tumbar un alta.
"""
from datetime import datetime

from sqlalchemy import text

from src.utils.middleware.logs.logs import logger

# Cuantas cifras rellena el contador. No trunca: 10000 sale como "10000".
_ANCHO = 4


def _max_actual(conn, tabla: str, columna: str, prefix: str, year_digit: str) -> int:
    """Maximo sufijo numerico existente, para sembrar el contador.

    Se ejecuta sobre la conexion AUTONOMA, no sobre la sesion del llamador: si
    se hiciera con la suya, el SELECT dispararia autoflush y forzaria el INSERT
    pendiente — que es exactamente la cadena que dejo 12 ficheros perdidos en
    agosto (log_activity -> generate_custom_id -> autoflush -> UniqueViolation,
    tragado por audit.py:114, sesion envenenada).

    La regex `^PREFIJO<digito>[0-9]+$` replica el `try: int(...) except:
    continue` del algoritmo anterior: los IDs legacy sin sufijo numerico (p.ej.
    "BLGDEP6") se IGNORAN en vez de reiniciar el contador a 1, que colisionaria
    con los ya usados.

    Desambigua bien los prefijos que se solapan porque el digito de año esta en
    posicion fija: PTL6... no casa PTLGCF6..., FD6... no casa FDI6..., PM6... no
    casa PMC6...
    """
    patron = f"^{prefix}{year_digit}[0-9]+$"
    corte = len(prefix) + 2  # substring() es 1-based: salta prefijo + digito
    sql = text(
        f'SELECT coalesce(max(substring("{columna}" from :corte)::bigint), 0) '
        f'FROM "{tabla}" WHERE "{columna}" ~ :patron'
    )
    return int(conn.execute(sql, {"corte": corte, "patron": patron}).scalar() or 0)


def _siguiente_contador(bind, tabla: str, columna: str, prefix: str,
                        year_digit: str, resincronizar: bool) -> int:
    """Reserva el siguiente numero en una transaccion propia y CORTA.

    `bind.connect()` saca una conexion nueva del mismo pool y la cierra al
    salir; el commit es inmediato, asi que el row lock del UPDATE no queda
    retenido durante la transaccion (larga, con E/S de terceros) del llamador.
    """
    with bind.connect() as conn:
        # Cinturon: si otra transaccion retiene la fila, fallar en 3 s y caer
        # al respaldo es infinitamente mejor que esperar sin limite (en
        # produccion lock_timeout=0 y statement_timeout=0).
        conn.execute(text("SET LOCAL lock_timeout = '3s'"))
        if not resincronizar:
            fila = conn.execute(
                text("UPDATE id_counters SET last_value = last_value + 1 "
                     "WHERE prefix = :p AND year_digit = :y "
                     "RETURNING last_value"),
                {"p": prefix, "y": year_digit},
            ).first()
            if fila is not None:
                conn.commit()
                return int(fila[0])

        # Sembrado perezoso, o resincronizacion tras una colision: se toma el
        # mayor entre lo que dice el contador y el maximo real de la tabla. Sin
        # el GREATEST, un ID insertado a mano por encima del contador haria que
        # el bucle de reintento chocara cinco veces contra el mismo numero.
        semilla = _max_actual(conn, tabla, columna, prefix, year_digit)
        fila = conn.execute(
            text("INSERT INTO id_counters (prefix, year_digit, last_value) "
                 "VALUES (:p, :y, :v) "
                 "ON CONFLICT (prefix, year_digit) DO UPDATE "
                 "SET last_value = GREATEST(id_counters.last_value, :v0) + 1 "
                 "RETURNING last_value"),
            {"p": prefix, "y": year_digit, "v": semilla + 1, "v0": semilla},
        ).first()
        conn.commit()
        return int(fila[0])


def _max_en_python(session, model, id_field_name: str, prefix: str,
                   year_digit: str) -> int:
    """Algoritmo anterior. Se conserva como respaldo y para no-PostgreSQL.

    OJO CON EL AUTOFLUSH — aqui estuvo un defecto que encontro la revision.

    La version original usaba `session.exec(select(...))`, y `Session.exec`
    AUTOFLUSHEA: fuerza a escribir lo que el llamador tuviera pendiente. Esa es
    exactamente la cadena que perdio los 12 ficheros de agosto:

        session.add(attachment)      -> INSERT pendiente
        log_activity -> generate_custom_id -> exec() -> AUTOFLUSH
        -> UniqueViolation -> se lo traga audit.py:114 -> sesion envenenada

    Es decir: la RED DE SEGURIDAD contenia el bug del que protege. Y como el
    respaldo salta justo bajo carga, saltaria en el peor momento.

    `session.connection().execute()` va a la MISMA transaccion del llamador
    pero NO autoflushea. Y el LIKE es portable, asi que sirve igual para el
    camino de sqlite de los tests de desborde.
    """
    tabla = model.__tablename__
    filas = session.connection().execute(
        text(f'SELECT "{id_field_name}" FROM "{tabla}" '
             f'WHERE "{id_field_name}" LIKE :patron'),
        {"patron": f"{prefix}{year_digit}%"},
    ).fetchall()

    corte = len(prefix) + 1
    ultimo = 0
    for (valor,) in filas:
        # Los IDs legacy sin sufijo numerico (p.ej. "BLGDEP6") se IGNORAN en
        # vez de contar como 0, que reiniciaria el contador a 1 y colisionaria
        # con los ya usados.
        try:
            ultimo = max(ultimo, int(valor[corte:]))
        except (ValueError, TypeError, IndexError):
            continue
    return ultimo


def _empujar_contador(session, prefix: str, year_digit: str,
                      valor: int) -> int | None:
    """Deja `id_counters` al dia despues de usar el respaldo.

    DEFECTO QUE ARREGLA (lo encontro la revision adversarial, dos lentes por
    separado): el respaldo devolvia `max+1` sin tocar la tabla. Si el contador
    ya estaba sembrado y sincronizado, la SIGUIENTE llamada buena hacia
    `UPDATE ... last_value + 1` y devolvia EL MISMO numero que acababa de
    entregar el respaldo -> duplicate key.

    Peor aun por donde sale: en `log_activity` esa IntegrityError la absorbe
    `audit.py:114` y la fila de auditoria se pierde EN SILENCIO — el mismo modo
    de fallo que costo 88 dias. En el resto de llamadores la propaga
    `save_with_retry`, que documenta que NO reintenta IntegrityError, asi que
    el alta responde 500.

    CONEXION PROPIA, no la del llamador. La primera version usaba
    `session.connection()` buscando un acoplamiento que parecia elegante: al
    commitear con la transaccion del llamador, un rollback suyo dejaba el
    contador sin mover. Pero eso reintroducia EXACTAMENTE el problema por el que
    este diseno descarto `pg_advisory_xact_lock`:

        el INSERT ... ON CONFLICT toma el row lock de (prefix, year_digit) EN la
        transaccion del llamador, y lo retiene hasta que ESA transaccion
        commitee — que en el webhook de adjuntos incluye dos requests.get a
        Podio y una subida a Cloudinary.

    Y hay un caso peor que el bloqueo entre peticiones: la SIGUIENTE llamada del
    MISMO request usa la conexion autonoma y se queda esperando un lock que
    retiene su propia transaccion. No hay ciclo de esperas, asi que el detector
    de deadlocks de PostgreSQL nunca dispara. Medido en produccion:
    `lock_timeout = 0` y `statement_timeout = 0`, o sea espera INDEFINIDA hasta
    que Vercel mate la funcion.

    Lo que se pierde con la conexion propia: si el llamador hace rollback, el
    contador ya avanzo y ese numero queda quemado. Es un hueco en la secuencia,
    exactamente lo mismo que hace una secuencia de Postgres, y no afecta a la
    unicidad porque el sembrado usa GREATEST y el contador es monotono. Un hueco
    a cambio de no colgar una peticion es un cambio bueno.

    `SET LOCAL lock_timeout` como cinturon: aunque algo retenga la fila, esto
    falla en 3 s en vez de esperar para siempre, y el `except` lo absorbe.

    Best-effort: si esto tambien falla ya estamos en modo degradado y no puede
    empeorar el alta.
    """
    try:
        bind = session.get_bind()
        with bind.connect() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '3s'"))
            fila = conn.execute(
                text("INSERT INTO id_counters (prefix, year_digit, last_value) "
                     "VALUES (:p, :y, :v) "
                     "ON CONFLICT (prefix, year_digit) DO UPDATE "
                     "SET last_value = GREATEST(id_counters.last_value, :base) + 1 "
                     "RETURNING last_value"),
                {"p": prefix, "y": year_digit, "v": valor, "base": valor - 1},
            ).first()
            conn.commit()
            return int(fila[0]) if fila else None
    except Exception:
        logger.exception("no se pudo reconciliar id_counters para %s%s",
                         prefix, year_digit)
    return None


def generate_custom_id(session, model, id_field_name: str, prefix: str,
                       *, resincronizar: bool = False) -> str:
    """Devuelve el siguiente ID libre para `prefix` en el año en curso.

    La firma publica no cambia: los 61 sitios que la llaman siguen igual.

    `resincronizar=True` fuerza releer el maximo real de la tabla antes de
    incrementar. Lo usa el bucle de reintento de los adjuntos a partir del 2.o
    intento: sin eso reintentaria cinco veces contra un contador desfasado.
    """
    year_digit = str(datetime.now().year)[-1]

    try:
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            siguiente = _siguiente_contador(
                bind, model.__tablename__, id_field_name, prefix,
                year_digit, resincronizar)
            return f"{prefix}{year_digit}{siguiente:0{_ANCHO}}"
    except Exception:
        # Un fallo del contador no puede impedir un alta: se registra y se cae
        # al algoritmo anterior. Ese camino SIGUE siendo vulnerable a la
        # carrera (es el de antes de este cambio), pero ya no reintroduce el
        # autoflush ni deja el contador desfasado — ver _max_en_python y
        # _empujar_contador.
        logger.exception(
            "id_counters fallo para %s%s; se usa el calculo en Python",
            prefix, year_digit)

    ultimo = _max_en_python(session, model, id_field_name, prefix, year_digit)
    siguiente = ultimo + 1

    # Reconciliar el contador Y quedarse con el valor que reserve.
    #
    # Las DOS cosas importan. Si solo se empujara, la proxima llamada buena
    # repetiria este numero. Y si solo se leyera la tabla, dos llamadas
    # seguidas del respaldo DENTRO DE LA MISMA TRANSACCION devolverian el mismo
    # ID: el `_max_en_python` de arriba ya no autoflushea —a proposito, es lo
    # que envenenaba la sesion— asi que no ve la fila que el llamador dejo
    # pendiente. El contador si la recuerda, porque commitea aparte.
    #
    # Lo cazo `test_dos_ids_seguidos_por_el_respaldo_no_se_bloquean`. El
    # algoritmo anterior no tenia el problema justamente por el autoflush.
    #
    # Solo en PostgreSQL — en sqlite no existe id_counters y el respaldo es el
    # camino unico (ahi tampoco hay concurrencia que temer).
    try:
        if session.get_bind().dialect.name == "postgresql":
            reservado = _empujar_contador(session, prefix, year_digit, siguiente)
            if reservado:
                siguiente = reservado
    except Exception:
        logger.exception("no se pudo comprobar el dialecto al reconciliar")

    return f"{prefix}{year_digit}{siguiente:0{_ANCHO}}"
