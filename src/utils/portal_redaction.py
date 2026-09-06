"""Campos que nunca deben salir hacia un rol de portal.

POR QUÉ ESTÁ AQUÍ Y NO EN CADA RUTA
====================================
`add_relationships` (src/utils/relationships.py) hace `model_dump()` de TODAS
las columnas de cada relación expandida y solo redacta la contraseña. No hay
proyección por rol en ninguna parte salvo `serialize_job()`, que únicamente usan
las rutas de `/jobs`. Ese es el hallazgo F-03 de la auditoría de portal: a un
técnico `/jobs/` le oculta el precio y `/technician/`, `/tasks/`, `/attachments/`
y `/tlactivity/` se lo entregan, porque expanden un job y nadie los proyecta.

Arreglarlo ruta a ruta deja el mismo agujero abierto para la siguiente ruta que
alguien escriba. Se arregla en el punto por el que pasa TODO: el volcado.

QUÉ SE REDACTA Y POR QUÉ
========================
· Bloque financiero del job — decisión ratificada del cliente (ambigüedad 3):
  el subcontratista no ve el margen de GQM. El técnico ya lo tenía vetado por
  `JobReadBasic`; esto lo extiende a las rutas que no proyectaban.
· `Document` — el documento de política IAM. Es el mapa de lo que un usuario
  puede hacer; entregárselo a un par es el hallazgo F-01.
· Identificadores internos de Podio (F-06).

Lo que NO se redacta aquí: `Score`, `Gqm_compliance` y `Notes` de otros
subcontratistas. Esos dejan de ser alcanzables por el arreglo de scoping
(P-05): tras él, un sub no puede leer la ficha de otro. Redactarlos también
aquí escondería el dato propio, que el panel sí muestra en su ficha.
"""
from flask import g

# Bloque financiero de `jobs`: el margen de GQM y todo lo que lo deja deducir.
CAMPOS_FINANCIEROS_JOB = frozenset({
    "Tech_formula_pricing", "Gqm_formula_pricing", "Gqm_adj_formula_pricing",
    "Gqm_target_sold_pricing", "Gqm_target_return", "Gqm_premium_in_money",
    "Gqm_final_sold_pricing", "Gqm_final_percentage", "Gqm_final_form_pricing",
    "Gqm_final_adj_form_pricing", "Gqm_final_target_return", "Gqm_final_prem_in_money",
    "Gqm_total_change_orders", "Gqm_total_materials_fees", "Gqm_paid_fees",
    "Acc_receivable", "Bldg_dept_fees", "Ptl_gc_fee", "Pricing_target",
    "Estimated_rent", "Estimated_material",
})

# Documentos de política IAM: nunca a un rol de portal.
CAMPOS_IAM = frozenset({"Document"})

# Identificadores internos de la integración con Podio.
CAMPOS_PODIO = frozenset({"podio_item_id", "podio_profile_id", "podio_file_id"})

CAMPOS_VETADOS_A_PORTAL = CAMPOS_FINANCIEROS_JOB | CAMPOS_IAM | CAMPOS_PODIO

# Los tres valores que puede llevar el claim `role` del JWT para un rol externo.
ROLES_DE_PORTAL = frozenset({"subcontractor", "technician"})


def llamante_es_portal() -> bool:
    """¿La petición en curso la hace un rol de portal?

    Falla CERRADO en el sentido seguro para el staff: sin `g.current_user`
    (scripts, tests unitarios, tareas de fondo) devuelve False y no se redacta
    nada, que es el comportamiento previo. La redacción solo se activa cuando
    hay un usuario de portal identificado.
    """
    usuario = getattr(g, "current_user", None)
    if not usuario:
        return False
    return usuario.get("role") in ROLES_DE_PORTAL


def campos_a_redactar(base: frozenset) -> frozenset:
    """`base` (los campos sensibles de siempre) más los vetados a portal."""
    if llamante_es_portal():
        return frozenset(base) | CAMPOS_VETADOS_A_PORTAL
    return frozenset(base)


# ── Colecciones anidadas del job que no deben salir a un rol de portal ───────
#
# La redaccion por nombre de campo (arriba) no basta aqui: el problema no es que
# un campo se llame de cierta forma, sino que la COLECCION entera pertenece a
# otro. En un job COMPARTIDO entre dos subcontratistas, `subcontractors[]` traia
# la ficha del otro y `subcontractors[].orders[]` sus condiciones economicas.
# Medido con sub_B enlazado al job de sub A: llegaban SUBC60002, TEC60002 y
# ORD60002.
#
# Decision ratificada por el cliente (ambiguedad 5): un sub no ve NADA de otro
# sub, ni siquiera compartiendo obra.
RELACIONES_VETADAS_A_PORTAL = frozenset({
    "members",          # personal interno de GQM, con sus correos
    "financial_docs",   # el sub perdio `finance:read` en la Fase A del PR #116
    "estimate_costs",
    "comdetails",       # detalle de comisiones
    "multipliers",
    "payment_units",
    "change_orders",
})

# Del cliente final, un rol de portal ve donde tiene que ir a trabajar y nada
# mas (ambiguedad 4 ratificada: direccion si, contacto no).
CLIENTE_VISIBLE_A_PORTAL = frozenset({
    "ID_Client", "Client_Community", "Address", "Client_Status",
    "Residential_Units", "Services_interested_in",
})


def acotar_job_para_portal(job_dict: dict) -> dict:
    """Poda las colecciones anidadas de un job segun quien pregunta.

    Se llama desde `serialize_job()`, que es el punto por el que pasan las once
    rutas de `/jobs`. Hacerlo ahi y no en cada handler es lo que evita que la
    proxima ruta de jobs nazca con el agujero abierto — que es exactamente lo
    que le paso a `/jobs/by-type-year` (T-27).

    No toca nada si el llamante es staff.
    """
    usuario = getattr(g, "current_user", None)
    if not usuario or usuario.get("role") not in ROLES_DE_PORTAL:
        return job_dict
    if not isinstance(job_dict, dict):
        return job_dict

    rol, uid = usuario.get("role"), usuario.get("id")

    for relacion in RELACIONES_VETADAS_A_PORTAL:
        job_dict.pop(relacion, None)

    if isinstance(job_dict.get("client"), dict):
        job_dict["client"] = {k: v for k, v in job_dict["client"].items()
                              if k in CLIENTE_VISIBLE_A_PORTAL}

    # Un subcontratista solo se ve a si mismo en la lista de contratistas del
    # job; un tecnico no ve esa lista en absoluto.
    subs = job_dict.get("subcontractors")
    if isinstance(subs, list):
        if rol == "subcontractor":
            job_dict["subcontractors"] = [
                s for s in subs
                if isinstance(s, dict) and s.get("ID_Subcontractor") == uid]
        else:
            job_dict["subcontractors"] = []

    # Y en la lista de tecnicos del job: el tecnico se ve a si mismo; el sub ve
    # a los suyos, que son los que cuelgan de el.
    tecnicos = job_dict.get("technicians")
    if isinstance(tecnicos, list):
        if rol == "technician":
            job_dict["technicians"] = [
                t for t in tecnicos
                if isinstance(t, dict) and t.get("ID_Technician") == uid]
        else:
            mios = {s.get("ID_Technician")
                    for s in job_dict.get("subcontractors", [])
                    if isinstance(s, dict)
                    for s in (s.get("technicians") or [])
                    if isinstance(s, dict)}
            job_dict["technicians"] = [
                t for t in tecnicos
                if isinstance(t, dict) and t.get("ID_Technician") in mios]

    return job_dict
