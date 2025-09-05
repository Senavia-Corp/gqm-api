from flask import Blueprint

bp = Blueprint("root", __name__)

@bp.get("/")
def root():
    return "Home"
