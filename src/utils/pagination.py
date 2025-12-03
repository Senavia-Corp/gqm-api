from functools import wraps
from flask import request, jsonify


def paginate(default_limit=10, max_limit=100):

    from flask import Response

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            # ---------------------------
            # Leer parámetros de paginación
            # ---------------------------
            try:
                page = int(request.args.get("page", 1))
                limit = int(request.args.get("limit", default_limit))
            except:
                return jsonify({"error": "Invalid pagination parameters"}), 400

            if limit > max_limit:
                limit = max_limit

            offset = (page - 1) * limit

            # ---------------------------
            # Ejecutar endpoint original
            # ---------------------------
            result = func(*args, **kwargs)

            data = None
            status = 200

            # Caso 1: El endpoint devuelve (data, status)
            if isinstance(result, tuple) and len(result) == 2:
                data, status = result

                # Si data es una Response → no paginar
                if isinstance(data, Response):
                    return data, status

            # Caso 2: endpoint devuelve una Response
            elif isinstance(result, Response):
                return result

            # Caso 3: devuelve solo una lista
            else:
                data = result

            # ---------------------------
            # Validación
            # ---------------------------
            if not isinstance(data, list):
                return jsonify({
                    "error": "Pagination only works with list results",
                    "received_type": str(type(data))
                }), 500

            # ---------------------------
            # LISTA VACÍA → TU NUEVO COMPORTAMIENTO
            # ---------------------------
            if len(data) == 0:
                return jsonify({
                    "message": "No hay datos disponibles.",
                    "page": page,
                    "limit": limit,
                    "total": 0,
                    "results": []
                }), 200

            # ---------------------------
            # Paginar resultados
            # ---------------------------
            paginated = data[offset: offset + limit]

            return jsonify({
                "page": page,
                "limit": limit,
                "total": len(data),
                "results": paginated
            }), status

        return wrapper
    return decorator
