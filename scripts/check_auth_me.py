"""Comprobación del endpoint /auth/me sin tocar ninguna base de datos real.

Verifica lo que puede romperse en frío: que la ruta queda registrada, que es
GET, que NO está en la whitelist pública (o sea, exige JWT), y que sin token
responde 401 en vez de filtrar datos.
"""
import os, sys, pathlib

# Ejecutable desde cualquier sitio: main.py vive en la raíz del repo.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/fake")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "test")

from main import app

rutas = {str(r.rule): sorted(r.methods - {"HEAD", "OPTIONS"}) for r in app.url_map.iter_rules()}

assert "/auth/me" in rutas, "la ruta /auth/me no está registrada"
assert rutas["/auth/me"] == ["GET"], f"métodos inesperados: {rutas['/auth/me']}"
print("✅ /auth/me registrada como GET")

c = app.test_client()

r = c.get("/auth/me")
assert r.status_code == 401, f"sin token debería ser 401, fue {r.status_code}"
print(f"✅ sin token → {r.status_code} (falla cerrado, no es pública)")

r = c.get("/auth/me", headers={"Authorization": "Bearer no-es-un-jwt"})
assert r.status_code == 401, f"con token basura debería ser 401, fue {r.status_code}"
print(f"✅ token inválido → {r.status_code}")

# Control positivo: una ruta que SÍ es pública, para probar que el 401 de
# arriba viene del guard y no de que todo devuelva 401 en este arnés.
r = c.post("/auth/login", json={})
assert r.status_code != 401, "el control positivo también dio 401: el arnés no prueba nada"
print(f"✅ control positivo /auth/login → {r.status_code} (no 401)")
print("\nTODO OK")
