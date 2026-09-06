from urllib.parse import unquote

import cloudinary
import cloudinary.uploader
from src.config import (
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET
)

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

RESOURCE_TYPE_MAP = {
    # Imágenes
    "image/jpeg":       "image",
    "image/jpg":        "image",
    "image/png":        "image",
    "image/gif":        "image",
    "image/webp":       "image",
    "image/svg+xml":    "image",
    "image/tiff":       "image",
    "image/bmp":        "image",
    "image/heic":       "image",
    # Videos
    "video/mp4":        "video",
    "video/mov":        "video",
    "video/avi":        "video",
    "video/quicktime":  "video",
    "video/x-msvideo":  "video",
    "video/wmv":        "video",
    "video/webm":       "video",
    "video/mkv":        "video",
    "video/x-matroska": "video",
    # PDFs
    "application/pdf":  "raw",
    # Word
    "application/msword":                                                       "raw",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":  "raw",
    # Excel
    "application/vnd.ms-excel":                                                 "raw",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":        "raw",
    # PowerPoint
    "application/vnd.ms-powerpoint":                                                    "raw",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":        "raw",
    # Comprimidos
    "application/zip":               "raw",
    "application/x-zip-compressed":  "raw",
    "application/x-rar-compressed":  "raw",
    "application/x-7z-compressed":   "raw",
    # Texto
    "text/plain":   "raw",
    "text/csv":     "raw",
}


def get_resource_type(mimetype: str) -> str:
    """Retorna el resource_type que Cloudinary necesita según el mimetype."""
    return RESOURCE_TYPE_MAP.get(mimetype, "raw")


# Cloudinary rechaza estos caracteres en el public_id: devuelve
# "BadRequest: public_id (...) is invalid" y el fichero NO llega a subirse.
#
# Paso en produccion el 24-ago-2026 con "Invoice #147833791.pdf" (QID61359):
# la limpieza anterior solo sustituia espacios y barras, asi que la almohadilla
# sobrevivia hasta el public_id. Era el primer fichero con un caracter prohibido
# en 2.493 adjuntos, por eso nunca habia saltado — pero las facturas de
# proveedor llevan `#` a menudo.
_PROHIBIDOS_CLOUDINARY = "?&#\\%<>+"


def sanitizar_para_public_id(nombre: str) -> str:
    """Deja `nombre` en algo que Cloudinary acepte como public_id.

    Sustituye SOLO los caracteres prohibidos, no una lista blanca: hoy suben
    bien ~2.500 ficheros con acentos, parentesis y comas, y una lista blanca
    les cambiaria el public_id sin necesidad.

    Esto toca unicamente el identificador en Cloudinary. El nombre visible
    viaja aparte en `Attachments.Document_name`, asi que el cliente sigue
    viendo "Invoice #147833791.pdf" con su almohadilla.
    """
    limpio = nombre.replace(" ", "_").replace("/", "_")
    for prohibido in _PROHIBIDOS_CLOUDINARY:
        limpio = limpio.replace(prohibido, "_")
    # Los de control tampoco valen, y encima son invisibles al depurar.
    return "".join(c if c.isprintable() else "_" for c in limpio)


def sanitizar_carpeta(folder: str) -> str:
    """Sanea cada TRAMO de la carpeta, conservando las barras.

    `sanitizar_para_public_id` convierte `/` en `_`, asi que no sirve de una
    pieza para una ruta. Y la carpeta no es terreno seguro: `routes/Attachments.py`
    concatena ahi el `access_level` que llega del FORMULARIO, o sea texto de
    usuario. Una almohadilla por esa puerta reproduce la misma falla 13
    ("public_id ... is invalid") que se cerro para el nombre del fichero el
    24-ago-2026 — y el nombre saneado no protege de nada si la carpeta no lo esta.
    """
    if not folder:
        return folder
    tramos = [sanitizar_para_public_id(t) for t in str(folder).split("/") if t]
    return "/".join(tramos)


# Tope de la subida DIRECTA de Cloudinary: 10.485.760 B. Por encima devuelve
# "BadRequest: File size too large. Got N. Maximum is 10485760" y el fichero NO
# se sube. Es la falla 17 de produccion: un PDF de 18.887.334 B en QID61298
# (28-ago-2026), abierta desde entonces porque nada en el camino miraba el
# tamano — ni aqui ni en el receptor del webhook.
#
# `upload_large` trocea y esquiva ese tope, pero solo se usaba para VIDEO, asi
# que cualquier PDF grande moria. El umbral va holgadamente por debajo del tope
# real para no rozarlo nunca, y coincide con el `chunk_size` ya en uso.
_TOPE_SUBIDA_DIRECTA = 6_000_000


def upload_to_cloudinary(
    file_bytes: bytes,
    filename: str,
    mimetype: str,
    folder: str,
    tags: str = ""
) -> dict:
    resource_type = get_resource_type(mimetype)

    # Limpiar el nombre del archivo para Cloudinary
    clean_filename = filename.rsplit(".", 1)[0]  # sin extensión
    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
    clean_filename = sanitizar_para_public_id(clean_filename)
    extension = sanitizar_para_public_id(extension)

    # REG-116: con public_id explícito, unique_filename no hace nada — dos
    # archivos con el mismo nombre en la misma carpeta se PISABAN. Sufijo
    # único propio; el nombre original vive en Attachments.Document_name y
    # el public_id real queda persistido (REG-058) para el borrado.
    import uuid as _uuid
    unique_name = f"{clean_filename}_{_uuid.uuid4().hex[:8]}"

    upload_params = {
        "resource_type":   resource_type,
        "folder":          sanitizar_carpeta(folder),
        # ← con extensión
        "public_id":       f"{unique_name}.{extension}" if extension else unique_name,
        "unique_filename": True,
    }
    if tags:
        upload_params["tags"] = tags

    # El video va troceado siempre (REG-115). Lo demas, solo si no cabe en una
    # subida directa: cambiar el camino de los ~2.500 ficheros pequenos que hoy
    # suben bien no aporta nada y si arriesga.
    if resource_type == "video" or len(file_bytes) > _TOPE_SUBIDA_DIRECTA:
        # REG-115: upload_large espera un path/stream, no bytes crudos
        import io as _io
        result = cloudinary.uploader.upload_large(
            _io.BytesIO(file_bytes),
            **upload_params,
            chunk_size=6_000_000
        )
    else:
        result = cloudinary.uploader.upload(file_bytes, **upload_params)

    return {
        "secure_url":    result["secure_url"],
        "public_id":     result["public_id"],
        "resource_type": result["resource_type"],
        "format":        result.get("format", ""),
        "original_name": filename
    }


def identidad_cloudinary(obj) -> tuple[str, str]:
    """(public_id, resource_type) de un Attachments, para poder BORRARLO.

    Se LEE la identidad persistida al subir; no se reconstruye. Reconstruirla es
    imposible desde REG-116: el public_id lleva un sufijo `uuid4().hex[:8]` que
    ninguna funcion puede adivinar. Y aplicarle `sanitizar_para_public_id()`
    seria peor que no hacer nada — a las filas legacy hay que hacerles
    `unquote()`, que es justo la operacion INVERSA.

    Para las filas anteriores a REG-058 (2.288 de 2.493 en produccion) se deriva
    de la URL, que es la unica fuente que queda:

        https://res.cloudinary.com/<cloud>/raw/upload/v123/QID/61359/factura.pdf
                                          ^^^ resource_type      ^^^^^^^^^^^^^^ public_id

    El resource_type sacado asi coincide 205/205 con el persistido (medido en
    produccion el 25-ago-2026), asi que la derivacion es fiable.

    Ojo con la extension: en `raw` el public_id SI la incluye y en `image` NO.
    Por eso `rsplit(".", 1)` solo se aplica cuando el resource_type no es raw —
    quitarsela a un raw es lo que hacia que `destroy()` devolviera "not found"
    (REG-058), y es el defecto que sigue vivo en el camino del webhook.
    """
    if obj.cloudinary_public_id:
        return obj.cloudinary_public_id, (obj.cloudinary_resource_type or "image")

    partes = (obj.Link or "").split("/upload/")
    if len(partes) != 2:
        raise ValueError(f"Link sin /upload/, no se puede derivar identidad: {obj.Link!r}")

    resource_type = partes[0].rsplit("/", 1)[-1]        # 'raw' | 'image' | 'video'
    # El primer segmento tras /upload/ es la version (v1234567890); se descarta.
    ruta = partes[1].split("/", 1)[1]
    if resource_type != "raw":
        ruta = ruta.rsplit(".", 1)[0]
    return unquote(ruta), resource_type


def destroy_en_cloudinary(public_id: str, resource_type: str = "image") -> str:
    """Borra en Cloudinary y devuelve el veredicto CRUDO: "ok", "not found", ...

    Existe aparte de `delete_from_cloudinary` porque los dos llamadores necesitan
    leer "not found" de forma distinta:

      * En el camino normal, "not found" es la SENAL DE UN FALLO: significa que
        el public_id con el que preguntamos no es el del fichero (REG-058: al
        derivarlo de la URL se le quitaba la extension, y en `raw` el public_id
        SI la lleva). Si lo tratamos como exito, el fallo se vuelve mudo — que
        es exactamente por que el borrado del webhook lleva roto al 100% sin que
        nadie se enterara.

      * Reintentando un borrado ya registrado como fallido, "not found" es EXITO:
        el fichero no esta, que es lo que se pedia. Ahi la identidad sale de la
        fila persistida, no de una reconstruccion, asi que "not found" no puede
        deberse a haber preguntado por el public_id equivocado.
    """
    result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
    return result.get("result", "")


def delete_from_cloudinary(public_id: str, resource_type: str = "image") -> bool:
    """
    Elimina un archivo de Cloudinary por su public_id.
    Retorna True si fue eliminado correctamente.
    """
    return destroy_en_cloudinary(public_id, resource_type) == "ok"
