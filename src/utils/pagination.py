from functools import wraps
from flask import request, jsonify


def paginate(default_limit=10, max_limit=100):
    """
    Decorador para paginar cualquier endpoint GET.
    Parámetro de ruta que usa: ?page=1&limit=20
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            # Obtener parámetros desde la URL
            try:
                page = int(request.args.get("page", 1))
                limit = int(request.args.get("limit", default_limit))
            except:
                return jsonify({"error": "Invalid pagination parameters"}), 400

            if limit > max_limit:
                limit = max_limit

            offset = (page - 1) * limit

            # El endpoint devuelve (lista, statusCode)
            data, status = func(*args, **kwargs)

            # Si el endpoint devolvió 404 NOT FOUND
            if status == 404:
                return jsonify({
                    "message": "No se encontraron resultados para esta consulta"
                }), 404

            if not isinstance(data, list):
                return jsonify({"error": "Pagination only works with list results"}), 500

            paginated = data[offset: offset + limit]

            return jsonify({
                "page": page,
                "limit": limit,
                "total": len(data),
                "results": paginated
            }), status

        return wrapper
    return decorator
