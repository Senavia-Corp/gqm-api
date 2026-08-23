"""Obtiene un token JWT por rol y lo guarda en ~/.gqm-rbac-tokens/<rol>.json (0600).

Modos (excluyentes):
  --dev                 4 usuarios @senavia-test.com; contraseña = SEED_DEV_PASSWORD (env o .env)
  --env-file RUTA       fichero 0600 con RBAC_<ROL>_EMAIL / RBAC_<ROL>_PASSWORD (ROL =
                        FULL_ADMIN|GQM_MEMBER|SUBCONTRACTOR|TECHNICAL); lo escribe quien conoce
                        las contraseñas, nunca el auditor
  --interactivo         correo por input(), contraseña por getpass()
  --api URL             defecto http://127.0.0.1:8000 (prod: https://gqm-api.vercel.app)

Nunca acepta contraseñas por argv ni las imprime. stdout: «rol: OK <user_id> <role_name>».
"""
import getpass, json, os, pathlib, ssl, stat, sys, urllib.error, urllib.request

ROLES = ["FULL_ADMIN", "GQM_MEMBER", "SUBCONTRACTOR", "TECHNICAL"]
DEV_EMAILS = {
    "FULL_ADMIN": "admin-dev@senavia-test.com", "GQM_MEMBER": "member-dev@senavia-test.com",
    "SUBCONTRACTOR": "sub-dev@senavia-test.com", "TECHNICAL": "tech-dev@senavia-test.com",
}
# Los tokens se guardan SEPARADOS por entorno: mezclarlos hace que la matriz
# mida los ids de un entorno contra la BD del otro (pasó el 23-ago: los tokens de
# producción pisaron los de develop y el runner buscó SUBC60415 en develop).
OUT_BASE = pathlib.Path.home() / ".gqm-rbac-tokens"


def entorno_de(api: str) -> str:
    return "dev" if ("localhost" in api or "127.0.0.1" in api) else "prod"


def _ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def login(api, email, password):
    body = json.dumps({"Email_Address": email, "Password": password}).encode()
    req = urllib.request.Request(f"{api}/auth/login", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl()) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {}


def read_env_file(path):
    p = pathlib.Path(path)
    mode = stat.S_IMODE(p.stat().st_mode)
    if mode & 0o077:
        sys.exit(f"⛔ {path} debe ser 0600 (es {oct(mode)})")
    creds = {}
    for line in p.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip().strip('"')
    return creds


def main():
    argv = sys.argv[1:]
    api = argv[argv.index("--api") + 1] if "--api" in argv else "http://127.0.0.1:8000"
    api = api.rstrip("/")
    creds = {}
    if "--dev" in argv:
        pwd = os.environ.get("SEED_DEV_PASSWORD")
        if not pwd:
            from decouple import config
            pwd = config("SEED_DEV_PASSWORD", default="")
        if not pwd:
            sys.exit("⛔ falta SEED_DEV_PASSWORD")
        creds = {r: (DEV_EMAILS[r], pwd) for r in ROLES}
    elif "--env-file" in argv:
        ev = read_env_file(argv[argv.index("--env-file") + 1])
        for r in ROLES:
            e, p = ev.get(f"RBAC_{r}_EMAIL"), ev.get(f"RBAC_{r}_PASSWORD")
            if not e or not p:
                sys.exit(f"⛔ faltan RBAC_{r}_EMAIL / RBAC_{r}_PASSWORD")
            creds[r] = (e, p)
    elif "--interactivo" in argv:
        for r in ROLES:
            e = input(f"{r} correo: ").strip()
            creds[r] = (e, getpass.getpass(f"{r} contraseña: "))
    else:
        sys.exit(__doc__)

    OUT = OUT_BASE / entorno_de(api)
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(OUT_BASE, 0o700)
    os.chmod(OUT, 0o700)
    print(f"entorno={entorno_de(api)} · {api}")
    fallos = 0
    for r in ROLES:
        email, pwd = creds[r]
        code, data = login(api, email, pwd)
        if code != 200 or "access_token" not in data:
            print(f"{r}: FALLO login HTTP {code}")
            fallos += 1
            continue
        rd = (data.get("user_data") or {}).get("role_detail") or {}
        out = {"token": data["access_token"], "user_id": data.get("user_id"),
               "user_type": data.get("user_type"), "role_name": rd.get("Name")}
        path = OUT / f"{r}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(out, fh)
        print(f"{r}: OK {out['user_id']} {out['role_name']}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
