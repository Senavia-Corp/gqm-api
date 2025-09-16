import psycopg2
from psycopg2 import DatabaseError
from decouple import config

def get_connection():
    try:
        connect=psycopg2.connect(
            host=config('PGSQL_HOST'),
            user=config('PGSQL_USER'),
            password=config('PGSQL_PASSWORD'),
            database=config('PGSQL_DATABASE'),
            port=5433,
        )
        return connect
    except DatabaseError as ex:
        raise ex
    