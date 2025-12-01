
import time
from flask import request


def register_request_logger(app):
    @app.before_request
    def log_request():
        request._start_time = time.time()

        try:
            body = request.get_data(as_text=True)
            if len(body) > 2000:  # Evita imprimir cosas gigantes
                body = "[Payload demasiado grande]"
        except:
            body = "[No se pudo leer el body]"

        print("\n🔵 [REQUEST]")
        print(f"➡️  {request.method} {request.path}")
        print(f"🌐 IP: {request.remote_addr}")

    @app.after_request
    def log_response(response):
        duration = None
        if hasattr(request, "_start_time"):
            duration = round((time.time() - request._start_time) * 1000, 2)

        print("🟢 [RESPONSE]")
        print(f"⬅️  {response.status}")
        if duration is not None:
            print(f"⏱️  Duración: {duration} ms")
        print("──────────────────────────────")

        return response
