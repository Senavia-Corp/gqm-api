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


def upload_to_cloudinary(
    file_bytes: bytes,
    filename: str,
    mimetype: str,
    folder: str,
    tags: str = ""
) -> dict:
    resource_type = get_resource_type(mimetype)

    # Limpiar el nombre del archivo para Cloudinary
    # Reemplaza espacios y caracteres especiales
    clean_filename = filename.rsplit(".", 1)[0]  # sin extensión
    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
    clean_filename = clean_filename.replace(" ", "_").replace("/", "_")

    upload_params = {
        "resource_type":   resource_type,
        "folder":          folder,
        # ← con extensión
        "public_id":       f"{clean_filename}.{extension}" if extension else clean_filename,
        "unique_filename": True,
    }
    if tags:
        upload_params["tags"] = tags

    if resource_type == "video":
        result = cloudinary.uploader.upload_large(
            file_bytes,
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
