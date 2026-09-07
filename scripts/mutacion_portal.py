"""Prueba de mutación, hecha bien.

Dos lecciones de la primera versión, que daba veredictos distintos en cada
corrida:

1. El login está limitado a 5 intentos/60 s por correo (Login_auth.py:46-47) y
   cada proceso de pytest hace 4 logins. Encadenar mutaciones agotaba el cupo y
   las sondas se ponían rojas por un 429 — rojo por el motivo equivocado, que
   es tan inútil como un verde falso. Se le da cupo al arnés por ENTORNO
   (`LOGIN_RATE_MAX_ATTEMPTS`), sin tocar el código ni el .env.
2. No basta con mirar el código de salida: se exige que el fallo mencione la
   ASERCIÓN esperada. Si no, no se cuenta como detectado.
"""
import os, pathlib, subprocess, sys

ENTORNO = {**os.environ, "LOGIN_RATE_MAX_ATTEMPTS": "100000",
           "LOGIN_RATE_WINDOW_SECONDS": "1"}
F = "tests/integration/test_portal_scoping.py"

MUTACIONES = [
    ("A1 · by-member-role deja de podar por rol", "src/routes/Job.py",
     [("        jobs_data = [acotar_job_para_portal(d) for d in jobs_data]\n", "")],
     "test_by_member_role_no_entrega_finanzas_al_sub", "entrega"),

    ("A1 bis · la poda se aplica también al staff", "src/utils/portal_redaction.py",
     [('    if not usuario or usuario.get("role") not in ROLES_DE_PORTAL:\n        return job_dict\n',
       "    if False:\n        return job_dict\n")],
     "test_by_member_role_el_staff_conserva_sus_finanzas", "assert"),

    ("A2 · /jobs/oldest sin poda y con una columna financiera nueva", "src/routes/Job.py",
     [("        return jsonify(acotar_job_para_portal({\n", "        return jsonify({\n"),
      ("        })), 200\n", "        }), 200\n"),
      ('            "Service_type":          job.Service_type,\n',
       '            "Service_type":          job.Service_type,\n'
       '            "Gqm_target_return":     job.Gqm_target_return,\n')],
     "test_oldest_es_seguro_por_construccion", "entrega"),

    ("11b · el job vuelve a llevar todos sus adjuntos", "src/utils/portal_redaction.py",
     [('''    adjuntos = job_dict.get("attachments")
    if isinstance(adjuntos, list):
        job_dict["attachments"] = [
            a for a in adjuntos
            if isinstance(a, dict)
            and (a.get("access_level") or "").strip().lower() == "technicians"]
''', "")],
     "test_job_solo_lleva_adjuntos_technicians_al_portal", "assert"),

    ("11b bis · la poda de adjuntos alcanza al staff", "src/utils/portal_redaction.py",
     [('    if not usuario or usuario.get("role") not in ROLES_DE_PORTAL:\n        return job_dict\n',
       "    if False:\n        return job_dict\n")],
     "test_job_del_staff_conserva_todos_los_adjuntos", "assert"),

    ("11a · cualquier carpeta vuelve a ser legible", "src/routes/Attachments.py",
     [('''    if getattr(att, "ID_Jobs", None) is not None:
        return carpeta == "technicians" and PolicyEvaluator.evaluate(
            user_policies, "attachment:read_technicians")

''', "")],
     "test_sub_lee_por_id_solo_la_carpeta_technicians", "assert"),

    ("11a bis · el listado deja de filtrar por carpeta", "src/routes/Attachments.py",
     [('''    if getattr(att, "ID_Jobs", None) is not None:
        return carpeta == "technicians" and PolicyEvaluator.evaluate(
            user_policies, "attachment:read_technicians")

''', "")],
     "test_sub_lista_adjuntos_solo_technicians", "assert"),

    ("10 · desaparece la regla de carpeta en la subida", "src/routes/Attachments.py",
     [('''        if entity_type == "job" and access_level != "technicians":
            raise AppException(
                "Forbidden: desde el portal solo se puede subir a la carpeta "
                "«technicians» de un job.",
                "forbidden_folder", 403)
''', "")],
     "test_sub_solo_sube_a_technicians", "assert"),

    ("10 bis · la regla de subida se aplica también al staff", "src/routes/Attachments.py",
     [("    if llamante_es_portal():\n        with get_session() as sesion_guarda:",
       "    if True:\n        with get_session() as sesion_guarda:")],
     "test_staff_sigue_subiendo_a_members", "assert"),
]

fallos = []
for etiqueta, fichero, ediciones, prueba, senal in MUTACIONES:
    p = pathlib.Path(fichero)
    original = p.read_text()
    s = original
    ok = True
    for viejo, nuevo in ediciones:
        if s.count(viejo) != 1:
            print(f"⚠️  {etiqueta}: ancla x{s.count(viejo)} — SALTADA"); ok = False; break
        s = s.replace(viejo, nuevo, 1)
    if not ok:
        fallos.append(etiqueta); continue
    p.write_text(s)
    try:
        r = subprocess.run([".venv/bin/python", "-m", "pytest", "-q", "--no-header",
                            "-p", "no:cacheprovider", f"{F}::{prueba}"],
                           capture_output=True, text=True, timeout=300, env=ENTORNO)
    finally:
        p.write_text(original)
    salida = r.stdout + r.stderr
    r429 = "429" in salida or "TOO MANY" in salida.upper()
    roja = r.returncode != 0 and not r429 and senal.lower() in salida.lower()
    motivo = ("429 del limitador — NO CUENTA" if r429
              else "roja por la aserción esperada" if roja
              else "SIGUE VERDE" if r.returncode == 0 else "roja por OTRO motivo")
    print(f"{'✅' if roja else '❌'} {etiqueta}\n     {prueba} → {motivo}")
    if not roja:
        fallos.append(etiqueta)

print("\n" + "=" * 72)
if fallos:
    print(f"❌ {len(fallos)} de {len(MUTACIONES)} sin detectar: {fallos}")
    sys.exit(1)
print(f"✅ las {len(MUTACIONES)} mutaciones ponen roja su sonda, y por el motivo correcto")
