"""Constructores de payloads Podio sintéticos para tests.

La forma de cada field replica lo que entrega la API de Podio (y lo que
consume `get_job_field_value`): los montos llegan como strings, las
categorías como {"value": {"text": ...}} y las fechas como
{"start_date": ..., "end_date": ...}.
"""


def field(external_id, ftype, values, field_id=0):
    return {"field_id": field_id, "external_id": external_id, "type": ftype, "values": values}


def money(external_id, amount, field_id=0):
    return field(external_id, "money", [{"value": str(amount), "currency": "USD"}], field_id)


def calc(external_id, value, field_id=0):
    return field(external_id, "calculation", [{"value": str(value)}], field_id)


def category(external_id, text_value, field_id=0):
    return field(external_id, "category", [{"value": {"status": "active", "text": text_value, "id": 1}}], field_id)


def text(external_id, value, field_id=0):
    return field(external_id, "text", [{"value": value}], field_id)


def date(external_id, start, end=None, field_id=0):
    value = {"start_date": start}
    if end:
        value["end_date"] = end
    return field(external_id, "date", [value], field_id)


def app_ref(external_id, item_id, field_id=0):
    return field(external_id, "app", [{"value": {"item_id": item_id}}], field_id)


def item(item_id, tracking_id, fields):
    return {
        "item_id": item_id,
        "app_item_id_formatted": tracking_id,
        "fields": fields,
        "current_revision": {"created_by": {"name": "pytest"}},
    }


# ── Items canónicos (la fuente de los tests de no-regresión) ──────────────

def qid_item(item_id=990100, tracking_id="QID99901"):
    """QID con los campos que HOY mapean bien por slug (app 2026).

    El orden project-name-2 → project-name replica el orden real de la app
    (field_ids 274767592 < 274767593); la colisión de slugs depende de él.
    """
    return item(item_id, tracking_id, [
        text("project-location", "123 Ocean Dr"),
        category("job-status", "In Progress"),
        date("expected-completioninvoice", "2026-09-15"),
        text("project-name-2", "Vista Lagos Ph 2"),
        text("project-name", "PO-4581"),
        category("service-type", "Screen Enclosure"),
        date("date-received", "2026-08-01", end="2026-08-02"),
        calc("tech-formula-pricing", "1000.00"),
        money("estimated-hoa-admin-total", "350.00"),
        money("estimated-material-total", "1500.50"),
        money("fees-and-cost", "80.00"),
        calc("gqm-formula-total-cost", "2930.50"),
        calc("calculation-10", "500.00"),
        calc("bldg-fees-1", "100.00"),
        calc("bldg-fees-2", "150.00"),
        calc("bldg-dept-fees-3", "250.00"),
        calc("materials-purchased-total-2", "1650.50"),
        calc("acc-receivable", "123.45"),
    ])


QID_EXPECTED = {
    "podio_item_id": "990100",
    "ID_Jobs": "QID99901",
    "Job_type": "QID",
    "Project_location": "123 Ocean Dr",
    "Job_status": "In Progress",
    "Estimated_completion_date": "2026-09-15",
    "Project_name": "Vista Lagos Ph 2",
    "Po_wtn_wo": "PO-4581",
    "Service_type": "Screen Enclosure",
    "Date_assigned": "2026-08-01",
    "Date_assigned_end": "2026-08-02",
    "Tech_formula_pricing": "1000.00",
    "Estimated_rent": "350.00",
    "Estimated_material": "1500.50",
    "Estimated_city": "80.00",
    "Gqm_formula_pricing": "2930.50",
    "Gqm_paid_fees": "500.00",
    "Bldg_dept_fees": ["100.00", "150.00", "250.00"],
    "Gqm_total_materials_fees": "1650.50",
    "Acc_receivable": "123.45",
}


def ptl_item(item_id=990200, tracking_id="PTL99901", with_payments=True):
    """PTL 2026. Incluye los campos de pagos parciales que por DECISIÓN
    confirmada NO se mapean (PTL no usa pagos parciales)."""
    fields = [
        text("location", "Lot 44 Palm Bay"),
        category("status", "In Progress"),
        text("superintendent", "J. Smith"),
        text("title", "PTL-Prop-778"),
        date("estimated-start-date", "2026-08-20"),
        money("money", "5200.00"),
        money("money-2", "800.00"),
        money("fees-and-cost", "950.00"),
        calc("gqm-total-change-orders", "0.00"),
        calc("gqm-formula-total-cost", "4300.00"),
        calc("acc-receivable", "0.00"),
    ]
    if with_payments:
        fields += [
            money("payment-received-1", "1000.00"),
            money("payment-received-2", "2000.00"),
            text("payment-date-and-check-1", "08/05 #1234"),
        ]
    return item(item_id, tracking_id, fields)


PTL_EXPECTED = {
    "podio_item_id": "990200",
    "ID_Jobs": "PTL99901",
    "Job_type": "PTL",
    "Project_location": "Lot 44 Palm Bay",
    "Job_status": "In Progress",
    "Ptl_Superintendent": "J. Smith",
    "Ptl_property_id": "PTL-Prop-778",
    "Estimated_start_date": "2026-08-20",
    "Gqm_target_sold_pricing": "5200.00",
    "Ptl_gc_fee": "800.00",
    "Estimated_material": "950.00",
    "Gqm_total_change_orders": "0.00",
    "Gqm_formula_pricing": "4300.00",
    "Acc_receivable": "0.00",
}


def par_item(item_id=990300, tracking_id="PAR99901"):
    return item(item_id, tracking_id, [
        date("date-received", "2026-07-10"),
        category("job-status", "In Progress"),
        calc("gqm-formula-total-cost", "3000.00"),
        money("gqm-target-sold-price", "3600.00"),
        calc("par-pricing-target", "1.20"),
        money("gqm-pricing-return-premium-in", "600.00"),
        calc("gross-profit-margin", "0.167"),
        calc("acc-receivable", "3600.00"),
        text("payment-date-and-number-1", "07/15 #991"),
    ])


PAR_EXPECTED = {
    "podio_item_id": "990300",
    "ID_Jobs": "PAR99901",
    "Job_type": "PAR",
    "Date_assigned": "2026-07-10",
    "Job_status": "In Progress",
    "Gqm_formula_pricing": "3000.00",
    "Gqm_target_sold_pricing": "3600.00",
    "Pricing_target": "1.20",
    "Gqm_premium_in_money": "600.00",
    "Gqm_target_return": "0.167",
    "Acc_receivable": "3600.00",
    "Po_wtn_wo": "07/15 #991",
}
