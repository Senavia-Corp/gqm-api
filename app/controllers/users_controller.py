from ..services.users_service import save_user

def create_user(data: dict) -> dict:
    # Validaciones ligeras (ejemplo)
    data = data or {}
    data.setdefault("name", "anonymous")
    # Orquestar lógica de negocio:
    saved = save_user(data)
    return saved
