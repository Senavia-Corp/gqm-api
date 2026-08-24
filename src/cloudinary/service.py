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
        "folder":          folder,
        # ← con extensión
        "public_id":       f"{unique_name}.{extension}" if extension else unique_name,
        "unique_filename": True,
    }
    if tags:
        upload_params["tags"] = tags

    if resource_type == "video":
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


def delete_from_cloudinary(public_id: str, resource_type: str = "image") -> bool:
    """
    Elimina un archivo de Cloudinary por su public_id.
    Retorna True si fue eliminado correctamente.
    """
    result = cloudinary.uploader.destroy(
        public_id,
        resource_type=resource_type
    )
    return result.get("result") == "ok"
