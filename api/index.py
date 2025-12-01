# api/index.py
from main import create_app

# Vercel detecta esta variable `app` y la usa como WSGI Application
app = create_app()