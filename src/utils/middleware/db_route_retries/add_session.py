
from src.utils.middleware.retries import retry_db


@retry_db(max_retries=3, delay=1)
def save_with_retry(session, obj):

    # Agrega un objeto a la DB con retry en caso de errores de infraestructura.
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj
