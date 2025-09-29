from flask import Flask

# Blueprints
from src.routes.Podio import podio_bp
# OJO: tu routes/Job.py ya define 'main' como blueprint; puedes importarlo y registrarlo si quieres:
# from routes.Job import main as job_bp


def create_app():
    app = Flask(__name__)

    # Ruta simple de home
    @app.route("/")
    def root():
        return "Home"

    # Registrar blueprints
    app.register_blueprint(podio_bp)
    # app.register_blueprint(job_bp, url_prefix="/jobs")   # opcional, si quieres prefijo

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)