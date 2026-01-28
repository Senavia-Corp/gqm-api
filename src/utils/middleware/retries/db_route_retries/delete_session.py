
from src.utils.middleware.retries.retries import retry_db


@retry_db(max_retries=3, delay=1)
def delete_with_retry(session, obj):
    # Elimina un objeto de la DB con retry en caso de errores de infraestructura.
    session.delete(obj)
    session.commit()
