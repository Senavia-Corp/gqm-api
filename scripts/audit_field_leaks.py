"""Fuga a nivel de campo: qué se lleva dentro un rol de portal en cada 200.

La matriz de la Fase 3 dice si puedes entrar. Esto dice QUÉ TE LLEVAS.

El mecanismo que se está midiendo es `src/utils/relationships.py::add_relationships`,
que hace `model_dump(mode="json")` de TODAS las columnas de cada relación expandida
y solo redacta {"Password","password","hashed_password","pass"}. No hay proyección
por rol. Por eso la fuga suele estar tres niveles abajo y no en el primer nivel.

Dos detectores complementarios:

  1. CENTINELAS. El sembrado puso valores reconocibles con el prefijo del dueño
     (`A-`, `B-`). Encontrar `B-NOTA-INTERNA-GQM` en una respuesta a sub A nombra
     a la vez el campo filtrado y la víctima. Es prueba directa, no indicio.

  2. VOCABULARIO PROHIBIDO. Rutas de clave que un rol de portal no debe recibir
     nunca (margen, comisión, coste, políticas IAM, contacto del cliente).

Uso: .venv/bin/python scripts/audit_field_leaks.py --csv salida.csv
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.audit_portal_lib import call, tokens  # noqa: E402

A = {"sub": "SUBC60001", "tec": "TEC60001", "job": "QID-I60001", "task": "TSK60001",
     "att": "ATT60001", "cli": "CLI60001", "pmc": "PMC60001"}
B = {"sub": "SUBC60002", "tec": "TEC60002", "job": "PTL-I60001", "task": "TSK60003",
     "att": "ATT60003", "cli": "CLI60002", "pmc": "PMC60002"}
MUNDO = {"subcontractor": A, "technical": A, "sub_B": B, "tech_de_sub_B": B,
         "tech_independiente": A}

# Campos que un rol de portal NO debe recibir jamás, sea de quien sea.
PROHIBIDOS = {
    "Gqm_formula_pricing": "margen: fórmula de precio de GQM",
    "Gqm_adj_formula_pricing": "margen ajustado de GQM",
    "Gqm_target_sold_pricing": "precio objetivo de venta",
    "Gqm_target_return": "retorno objetivo de GQM",
    "Gqm_premium_in_money": "prima de GQM",
    "Gqm_final_sold_pricing": "precio final de venta",
    "Gqm_final_percentage": "porcentaje final",
    "Gqm_final_target_return": "retorno final",
    "Gqm_final_prem_in_money": "prima final",
    "Acc_receivable": "cuentas por cobrar",
    "Gqm_total_change_orders": "total de change orders",
    "Gqm_total_materials_fees": "total de materiales",
    "Gqm_paid_fees": "honorarios pagados",
    "Bldg_dept_fees": "tasas del building dept",
    "Ptl_gc_fee": "fee del general contractor",
    "Tech_formula_pricing": "fórmula de precio del técnico",
    "Estimated_rent": "renta estimada",
    "Estimated_material": "material estimado",
    "Document": "DOCUMENTO DE POLÍTICA IAM",
    "Password": "hash de contraseña",
    "podio_item_id": "id interno de Podio",
    "podio_profile_id": "id de perfil de Podio",
}

# ── Campos que solo son fuga SI EL REGISTRO ES DE OTRO ───────────────────────
#
# `Score`, `Gqm_compliance` y `Notes` estaban en la lista dura de arriba cuando
# se escribio este escaner, y era correcto ENTONCES: antes del arreglo del
# scoping, un rol de portal alcanzaba la ficha de cualquiera, asi que toda
# aparicion era de otro por definicion.
#
# Cerrados P-01, P-02 y P-05, un rol de portal solo alcanza su PROPIO registro,
# y su propio `Score` o su propio `Gqm_compliance` no son una fuga: el panel los
# pinta en su ficha («Compliance: —», «No score»). Mantenerlos en la lista dura
# convertiria el detector en un generador de falsos positivos, y un detector que
# grita siempre deja de leerse.
#
# Quien decide aqui es el detector de CENTINELAS, que prueba la propiedad por
# construccion: si un valor con el prefijo del otro mundo aparece en una
# respuesta, es de otro, se llame el campo como se llame. Esa es la senal
# fuerte; esta lista solo documenta que se movio y por que.
SOLO_FUGA_SI_ES_AJENO = {
    "Score": "puntuación interna del subcontratista",
    "Gqm_compliance": "estado de cumplimiento",
    "Notes": "notas internas",
}


def rutas(nodo, prefijo=""):
    """Rutas de clave. Los índices de lista se colapsan a [] para que la
    identidad sea estable entre corridas y comparable.

    Se emite CADA clave, no solo las hojas. Emitir solo hojas dejaba invisible
    cualquier campo prohibido cuyo valor sea un objeto o una lista — y el peor
    de todos, `permissions[].Document` (la política IAM), es exactamente eso:
    un objeto. El primer barrido dio 0 fugas de política IAM y era falso.
    """
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            ruta = f"{prefijo}.{k}" if prefijo else k
            yield ruta
            yield from rutas(v, ruta)
    elif isinstance(nodo, list):
        for it in nodo:
            yield from rutas(it, f"{prefijo}[]")


def centinelas(nodo, dueno_ajeno):
    """Valores del sembrado que delatan de QUIÉN es el dato."""
    out = set()

    def anda(n, ruta=""):
        if isinstance(n, dict):
            for k, v in n.items():
                anda(v, f"{ruta}.{k}" if ruta else k)
        elif isinstance(n, list):
            for it in n:
                anda(it, f"{ruta}[]")
        elif isinstance(n, str) and n.startswith(f"{dueno_ajeno}-"):
            out.add(f"{ruta} = {n!r}")

    anda(nodo)
    return out


def main():
    T = tokens()
    filas = []
    analizadas, saltadas = [], []
    SONDAS = [
        ("GET /jobs/<propio>",             "/jobs/{job}",                      "propio"),
        ("GET /jobs/",                     "/jobs/?limit=100",                 "propio"),
        ("GET /tasks/<propia>",            "/tasks/{task}",                    "propio"),
        ("GET /technician/<ajeno>",        "/technician/{tec}",                "ajeno"),
        ("GET /technician/",               "/technician/?limit=100",           "todos"),
        ("GET /subcontractors/<propio>",   "/subcontractors/{sub}",            "propio"),
        ("GET /subcontractors/<ajeno>",    "/subcontractors/{sub}",            "ajeno"),
        ("GET /attachments/",              "/attachments/?limit=100",          "todos"),
        ("GET /tlactivity/job/<ajeno>",    "/tlactivity/job/{job}",            "ajeno"),
        ("GET /auth/me",                   "/auth/me",                         "propio"),
        # El job COMPARTIDO entre sub A y sub B: aqui la fuga no es por id sino
        # por la COLECCION ANIDADA — `subcontractors[]` traia al otro sub con
        # sus ordenes dentro. Es el caso que los mundos disjuntos no pueden ver.
        ("GET /jobs/<compartido>",         "/jobs/QID-I60029",                 "compartido"),
    ]
    for suj in ("subcontractor", "technical", "sub_B", "tech_de_sub_B", "tech_independiente"):
        propio = MUNDO[suj]
        ajeno = B if propio is A else A
        letra_ajena = "B" if propio is A else "A"
        for etiqueta, plantilla, quien in SONDAS:
            mundo = ajeno if quien == "ajeno" else propio
            st, pl = call(T[suj], "GET", plantilla.format(**mundo))
            if st != 200:
                # Un 404 sobre lo ajeno es el arreglo funcionando: no hay cuerpo
                # que analizar. Pero se CUENTA y se informa: decir «0 fugas» sin
                # decir cuantas sondas se examinaron hace que el 0 parezca mas
                # fuerte de lo que es, y ese es justo el tope silencioso que
                # esta auditoria se prohibio a si misma.
                saltadas.append(f"{suj}·{etiqueta}·{quien}={st}")
                continue
            analizadas.append(f"{suj}·{etiqueta}")
            claves = set(rutas(pl))
            prohib = sorted({c for c in claves
                             if c.split(".")[-1].replace("[]", "") in PROHIBIDOS})
            cent = sorted(centinelas(pl, letra_ajena))
            for c in prohib:
                hoja = c.split(".")[-1].replace("[]", "")
                filas.append({"sujeto": suj, "endpoint": etiqueta, "objeto": quien,
                              "clave": c, "veredicto": "PROHIBIDO",
                              "detalle": PROHIBIDOS[hoja]})
            for c in cent:
                filas.append({"sujeto": suj, "endpoint": etiqueta, "objeto": quien,
                              "clave": c.split(" = ")[0], "veredicto": "CENTINELA AJENO",
                              "detalle": f"dato del mundo {letra_ajena}: {c.split(' = ',1)[1]}"})

    destino = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
    if destino:
        with open(destino, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["sujeto", "endpoint", "objeto", "clave",
                                               "veredicto", "detalle"])
            w.writeheader(); w.writerows(filas)
    from collections import Counter
    print(f"COBERTURA: {len(analizadas)} sondas analizadas · {len(saltadas)} saltadas "
          f"(no devolvieron 200, casi siempre porque el scoping las corta)")
    if saltadas:
        print("  saltadas: " + ", ".join(saltadas[:8])
              + (f" … y {len(saltadas)-8} mas" if len(saltadas) > 8 else ""))
    print(f"filas de fuga: {len(filas)}")
    print("\nPor endpoint y veredicto:")
    for (ep, v), n in Counter((f["endpoint"], f["veredicto"]) for f in filas).most_common():
        print(f"  {n:3d}  {v:16s} {ep}")
    print("\nCampos prohibidos distintos que alcanza un rol de portal:")
    for c, n in Counter(f["clave"] for f in filas if f["veredicto"] == "PROHIBIDO").most_common(25):
        print(f"  {n:3d}× {c}")
    if destino:
        print(f"\nCSV → {destino}")
    return 1 if filas else 0


if __name__ == "__main__":
    sys.exit(main())
