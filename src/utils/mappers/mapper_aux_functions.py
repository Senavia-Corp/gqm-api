import time

from src.utils.middleware.logs.logs import logger
from typing import Optional
from datetime import datetime
import re


def parse_date(value: Optional[str]) -> Optional[datetime.date]:

    # Convierte string de Podio a datetime.date.
    if not value:
        return None

    # Si es un diccionario de Podio
    if isinstance(value, dict):
        # Podio puede devolver varios formatos
        date_str = value.get("start_date") or value.get(
            "start_utc") or value.get("start")
    else:
        date_str = value

    if not date_str:
        return None

    # Solo quedarnos con la parte de fecha
    if " " in date_str:
        date_str = date_str.split(" ")[0]

    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def has_html(text: str) -> bool:
    """
    Detecta si un texto contiene HTML
    """
    return "<" in text and ">" in text


def clean_html(value: Optional[str]) -> Optional[str]:
    """
    Limpia HTML preservando saltos de línea entre párrafos
    """
    if not value:
        return None

    text = str(value)

    # Convertir párrafos y <br> en saltos de línea
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # Eliminar cualquier otra etiqueta HTML
    text = re.sub(r"<.*?>", "", text)

    # Limpiar espacios
    return text.strip()


# ─────────────────────── ANTI-BUCLE POR CONTENIDO ───────────────────────
#
# Antes esto era un diccionario EN MEMORIA con una ventana de 15 s, y descartaba
# por ítem y por reloj. Dos consecuencias medidas:
#
#   - No distinguía el eco de la app de una EDICIÓN HUMANA: la app escribe, tres
#     segundos después alguien corrige un campo en Podio, y se perdía sin error,
#     sin aviso y sin entrada en la cola de fallos.
#   - En Vercel cada entrega cae en otra lambda, así que la protección tampoco
#     cumplía su propio cometido de forma fiable.
#
# Ahora se guarda la HUELLA de lo que la app escribió y sólo se descarta lo que
# vuelve idéntico. La ventana se conserva como red: pasado ese tiempo, cualquier
# cosa entra.
recent_events = {}          # respaldo en proceso; la verdad está en la BD

ANTI_LOOP_WINDOW = 90       # segundos. Antes 15, y decidía por reloj.


def _huella(campos) -> str:
    """sha256 estable de los pares (external_id, valor) escritos."""
    import hashlib
    import json

    if not campos:
        return ""
    normal = {str(k): _normalizar_valor(v) for k, v in sorted(campos.items())}
    return hashlib.sha256(
        json.dumps(normal, sort_keys=True, default=str).encode()).hexdigest()


def _normalizar_valor(v):
    """Podio devuelve los importes como '300.0000' y los acepta como 300.
    Sin normalizar, el eco de la propia app no se reconocería."""
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if isinstance(v, list):
        return [_normalizar_valor(x) for x in v]
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return str(v).strip() if v is not None else None


def register_event(item_id, campos=None):
    """Anota que la app acaba de escribir `campos` en ese ítem."""
    item_id_str = str(item_id)
    huella = _huella(campos)
    claves = ",".join(sorted(str(k) for k in (campos or {})))
    recent_events[item_id_str] = (time.time(), huella, claves)
    try:
        from src.database.db_sqlmodel import get_session
        from src.models.PodioEchoModel import PodioEcho

        with get_session() as s:
            s.add(PodioEcho(item_id=item_id_str, huella=huella, claves=claves))
            s.commit()
    except Exception:
        # Que no se pueda anotar el eco NO debe tumbar la escritura a Podio:
        # el peor caso es que el eco vuelva a entrar y se aplique sobre sí mismo.
        logger.warning("No se pudo anotar el eco de %s", item_id_str, exc_info=True)


def olvidar_evento(item_id):
    """Retira la anotacion de eco de un item.

    Se anota ANTES de escribir en Podio, para ganarle la carrera al webhook. Si
    la escritura falla, esa anotacion es falsa y descartaria eventos legitimos.
    """
    item_id_str = str(item_id)
    recent_events.pop(item_id_str, None)
    try:
        from sqlmodel import select

        from src.database.db_sqlmodel import get_session
        from src.models.PodioEchoModel import PodioEcho

        with get_session() as s:
            for e in s.exec(select(PodioEcho).where(
                    PodioEcho.item_id == item_id_str)).all():
                s.delete(e)
            s.commit()
    except Exception:
        logger.warning("No se pudo olvidar el eco de %s", item_id_str, exc_info=True)


def is_recent_event(item_id, item=None):
    """¿Este evento es el eco de nuestra propia escritura?

    Dos señales, y la primera manda:

    1. **Quién firma la revisión.** Podio dice en `current_revision.created_by`
       quién hizo el cambio. Si lo firma una PERSONA, no es nuestro eco — y
       punto. Es la señal que arregla el defecto: antes, una edición humana
       hecha dentro de la ventana se descartaba sin más.
    2. **El contenido.** Si lo firma la API y además reproduce exactamente los
       campos que acabamos de escribir, es el eco.

    Comparar sólo el contenido no basta: la app escribe `job-status` y una
    persona toca `change-order-4` en la misma ventana; el subconjunto que
    escribimos sigue coincidiendo, y descartarlo perdería la edición humana.
    """
    item_id_str = str(item_id)
    huellas = _huellas_recientes(item_id_str)
    if not huellas:
        return False

    if item is None:
        # Sin item no hay nada que comparar: se conserva el criterio viejo, y
        # sólo para la ventana corta original.
        ts = recent_events.get(item_id_str)
        return bool(ts and (time.time() - ts[0]) < 15)

    if _lo_firma_una_persona(item):
        return False

    for huella, claves in huellas:
        if huella and claves and _coincide_con_lo_escrito(item, claves, huella):
            print(f"⛔ Ignorando webhook: es el eco de nuestra escritura ({item_id_str})")
            return True
    return False


def _lo_firma_una_persona(item) -> bool:
    """¿La revisión la firma una persona y no la API?

    Podio marca `type: "app"` cuando el cambio entra por token de aplicación —
    que es como escribe esta app— y `"user"` cuando lo hace alguien desde la
    interfaz. Si no viene el dato, se responde False y decide el contenido.
    """
    autor = ((item or {}).get("current_revision") or {}).get("created_by") or {}
    tipo = (autor.get("type") or "").lower()
    return tipo in ("user", "profile")


def _huellas_recientes(item_id_str) -> list:
    """Las huellas anotadas para ese ítem dentro de la ventana."""
    from datetime import datetime, timedelta, timezone

    salida = []
    ts = recent_events.get(item_id_str)
    if ts and (time.time() - ts[0]) < ANTI_LOOP_WINDOW:
        salida.append((ts[1], ts[2]))

    try:
        from sqlmodel import select

        from src.database.db_sqlmodel import get_session
        from src.models.PodioEchoModel import PodioEcho

        corte = datetime.now(timezone.utc) - timedelta(seconds=ANTI_LOOP_WINDOW)
        with get_session() as s:
            salida += [(e.huella, e.claves) for e in s.exec(
                select(PodioEcho)
                .where(PodioEcho.item_id == item_id_str, PodioEcho.created_at >= corte)
            ).all()]
    except Exception:
        logger.warning("No se pudieron leer los ecos de %s", item_id_str, exc_info=True)
    return salida


def _coincide_con_lo_escrito(item, claves, huella) -> bool:
    """El ítem que vuelve, ¿reproduce exactamente lo que escribimos?

    Se recorta el ítem entrante a las claves que la app escribió y se recalcula
    la huella sobre ESE subconjunto. Si coincide, es nuestro eco. Si alguien
    cambió cualquiera de esos campos —o tocó otro y el ítem entra igual—, no
    coincide y el evento se procesa.
    """
    esperadas = set(claves.split(","))
    campos = {}
    for f in item.get("fields", []) or []:
        ext = f.get("external_id")
        if ext not in esperadas:
            continue
        vals = f.get("values") or []
        if not vals:
            continue
        v = vals[0].get("value", vals[0]) if isinstance(vals[0], dict) else vals[0]
        campos[ext] = v
    if set(campos) != {c for c in esperadas if c}:
        return False        # falta alguno: no puede ser el eco exacto
    return _huella(campos) == huella
