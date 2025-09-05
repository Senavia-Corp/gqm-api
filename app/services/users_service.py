def save_user(user: dict) -> dict:
    # Simulación de persistencia/negocio
    # Aquí escribirías a DB, emitirías eventos, etc.
    user = dict(user)
    user["status"] = "user created"
    return user
