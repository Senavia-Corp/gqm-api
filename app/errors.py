from flask import Flask, jsonify

def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(e):
        return jsonify(error="Not Found"), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify(error="Internal Server Error"), 500
