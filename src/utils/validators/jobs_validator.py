from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.models.JobModel import Job


# ==========================
# CONFIG / COLUMNAS A VALIDAR
# ==========================

DIRECT_COLUMNS: List[str] = [
    "podio_item_id",
    "ID_Jobs",
    "Job_type",
    "Project_name",
    "Project_location",
    "Job_status",
    "Po_wtn_wo",
    "Service_type",
    "Date_assigned",
    "Estimated_start_date",
    "Estimated_project_duration",
    "Date_Received",
    "Estimated_completion_date",
    "Additional_detail",
    "Estimated_rent",
    "Estimated_material",
    "Estimated_city",
    "Tech_formula_pricing",
    "Gqm_formula_pricing",
    "Gqm_adj_formula_pricing",
    "Gqm_target_sold_pricing",
    "Gqm_target_return",
    "Gqm_premium_in_money",
    "Gqm_final_sold_pricing",
    "Gqm_final_percentage",
    "Pricing_target",
    "Permit",
    "Gqm_total_change_orders",
    "Gqm_total_materials_fees",
    "Acc_receivable",
    "Gqm_final_form_pricing",
    "Gqm_final_adj_form_pricing",
    "Gqm_final_target_return",
    "Gqm_final_prem_in_money",
    "Ptl_Superintendent",
    "Ptl_property_id",
    "Ptl_gc_fee",
    "Gqm_paid_fees",
    "Bldg_dept_fees",
]

FLOAT_FIELDS = {
    "Estimated_rent", "Estimated_material", "Estimated_city",
    "Tech_formula_pricing", "Gqm_formula_pricing", "Gqm_adj_formula_pricing",
    "Gqm_target_sold_pricing", "Gqm_target_return", "Gqm_premium_in_money",
    "Gqm_final_sold_pricing", "Gqm_final_percentage",
    "Gqm_total_change_orders", "Gqm_total_materials_fees",
    "Acc_receivable", "Gqm_final_form_pricing", "Gqm_final_adj_form_pricing",
    "Gqm_final_target_return", "Gqm_final_prem_in_money",
    "Gqm_paid_fees"
}


# ==========================
# NORMALIZACIÓN
# ==========================

def _normalize_date(val: Any) -> Optional[str]:
    """
    Normaliza a 'YYYY-MM-DD'
    Acepta:
      - '2025-12-31'
      - '2025-12-31 00:00:00'
      - RFC1123 'Mon, 04 Dec 2023 00:00:00 GMT' (si te llega así en algún lado)
      - datetime/date
    """
    if val is None:
        return None

    if isinstance(val, date) and not isinstance(val, datetime):
        return val.isoformat()

    if isinstance(val, datetime):
        return val.date().isoformat()

    if isinstance(val, str):
        s = val.strip()

        # RFC1123 (por si algún lado te serializa así)
        try:
            dt = datetime.strptime(s, "%a, %d %b %Y %H:%M:%S GMT")
            return dt.date().isoformat()
        except ValueError:
            pass

        # ISO datetime
        try:
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            return dt.date().isoformat()
        except ValueError:
            pass

        # ISO date
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s[:10]):
            return s[:10]

    return None


def _normalize_number(val: Any) -> Optional[float]:
    if val is None:
        return None

    if isinstance(val, (int, float)):
        return float(val)

    if isinstance(val, str):
        s = val.strip()
        # quitar símbolos si aparecen
        s = re.sub(r"[^\d\.\-]", "", s)
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    return None


def normalize_value(field_name: str, val: Any) -> Any:
    # Heurística por nombre
    if field_name.lower().startswith("date_") or field_name.lower().endswith("_date"):
        return _normalize_date(val)

    if field_name in FLOAT_FIELDS:
        return _normalize_number(val)

    if isinstance(val, list):
        # Normaliza listas (multi)
        norm = []
        for v in val:
            if isinstance(v, str):
                vv = v.strip()
                norm.append(vv)
            else:
                norm.append(v)
        # Para evitar diffs por orden en multi-values (si aplica)
        # Si NO quieres ordenar, comenta la siguiente línea:
        try:
            return sorted(norm)
        except TypeError:
            return norm

    if isinstance(val, str):
        return val.strip()

    return val


def almost_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


# ==========================
# RESULTADOS / REPORTE
# ==========================

@dataclass
class DiffRow:
    ID_Jobs: str
    podio_item_id: str
    job_type: str
    field: str
    expected: Any
    actual: Any
    status: str  # DIFF | MISSING_IN_DB | ERROR


@dataclass
class ValidationSummary:
    processed: int = 0
    missing_in_db: int = 0
    with_diffs: int = 0
    perfect: int = 0
    errors: int = 0


def compare_expected_vs_job(expected: Dict[str, Any], actual_job: Job) -> List[Tuple[str, Any, Any]]:
    diffs: List[Tuple[str, Any, Any]] = []

    for field in DIRECT_COLUMNS:
        exp_v = normalize_value(field, expected.get(field))

        # attribute may not exist in model (defensivo)
        if not hasattr(actual_job, field):
            diffs.append((field, exp_v, "__FIELD_NOT_IN_MODEL__"))
            continue

        act_raw = getattr(actual_job, field)
        act_v = normalize_value(field, act_raw)

        if field in FLOAT_FIELDS:
            if not almost_equal(exp_v, act_v):
                diffs.append((field, exp_v, act_v))
        else:
            if exp_v != act_v:
                diffs.append((field, exp_v, act_v))

    return diffs


def write_reports(
    diffs: List[DiffRow],
    summary: ValidationSummary,
    report_dir: str,
    report_name_prefix: str
) -> Dict[str, str]:
    os.makedirs(report_dir, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(report_dir, f"{report_name_prefix}_{ts}.csv")
    json_path = os.path.join(report_dir, f"{report_name_prefix}_{ts}.summary.json")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["ID_Jobs", "podio_item_id", "job_type", "field", "expected", "actual", "status"]
        )
        w.writeheader()
        for r in diffs:
            w.writerow({
                "ID_Jobs": r.ID_Jobs,
                "podio_item_id": r.podio_item_id,
                "job_type": r.job_type,
                "field": r.field,
                "expected": r.expected,
                "actual": r.actual,
                "status": r.status
            })

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "processed": summary.processed,
            "missing_in_db": summary.missing_in_db,
            "with_diffs": summary.with_diffs,
            "perfect": summary.perfect,
            "errors": summary.errors,
            "diff_rows": len(diffs),
        }, f, ensure_ascii=False, indent=2)

    return {"csv": csv_path, "summary_json": json_path}


# ==========================
# VALIDACIÓN EN BATCH
# ==========================

def validate_batch_jobs(
    *,
    items: List[dict],
    session,
    mapper_fn,
    job_type: str,
    year: int,
    offset: int,
    limit: int,
    report_dir: str = "reports/jobs_validation",
    write_report: bool = True
) -> Dict[str, Any]:
    """
    Valida (Podio -> expected via mapper) vs (DB row real).
    Debe ejecutarse DENTRO del flujo de sync, con el mismo batch items.
    """
    summary = ValidationSummary()
    diff_rows: List[DiffRow] = []

    for item in items:
        try:
            expected = mapper_fn(item)

            # mapper puede devolver {} si no detecta job_type
            if not expected:
                continue

            summary.processed += 1

            podio_item_id = str(expected.get("podio_item_id") or "")
            jid = str(expected.get("ID_Jobs") or "")
            jtype = str(expected.get("Job_type") or job_type)

            if not podio_item_id or not jid:
                summary.errors += 1
                diff_rows.append(DiffRow(
                    ID_Jobs=jid or "__NO_ID__",
                    podio_item_id=podio_item_id or "__NO_PODIO_ITEM_ID__",
                    job_type=jtype,
                    field="__ROW__",
                    expected="missing podio_item_id or ID_Jobs",
                    actual=None,
                    status="ERROR"
                ))
                continue

            # Buscar en DB por podio_item_id (tu llave fuerte)
            actual_job: Optional[Job] = session.query(Job).filter(Job.podio_item_id == podio_item_id).first()  # type: ignore

            if not actual_job:
                summary.missing_in_db += 1
                diff_rows.append(DiffRow(
                    ID_Jobs=jid,
                    podio_item_id=podio_item_id,
                    job_type=jtype,
                    field="__ROW__",
                    expected="present_in_podio",
                    actual="missing_in_db",
                    status="MISSING_IN_DB"
                ))
                continue

            diffs = compare_expected_vs_job(expected, actual_job)

            if not diffs:
                summary.perfect += 1
            else:
                summary.with_diffs += 1
                for field, exp_v, act_v in diffs:
                    diff_rows.append(DiffRow(
                        ID_Jobs=jid,
                        podio_item_id=podio_item_id,
                        job_type=jtype,
                        field=field,
                        expected=exp_v,
                        actual=act_v,
                        status="DIFF"
                    ))

        except Exception as e:
            summary.errors += 1
            diff_rows.append(DiffRow(
                ID_Jobs="__UNKNOWN__",
                podio_item_id=str(item.get("item_id") or "__UNKNOWN__"),
                job_type=job_type,
                field="__EXCEPTION__",
                expected="n/a",
                actual=str(e),
                status="ERROR"
            ))

    report_paths: Dict[str, str] = {}
    if write_report:
        prefix = f"jobs_{job_type}_{year}_offset{offset}_limit{limit}"
        report_paths = write_reports(
            diffs=diff_rows,
            summary=summary,
            report_dir=report_dir,
            report_name_prefix=prefix
        )

    return {
        "summary": {
            "processed": summary.processed,
            "missing_in_db": summary.missing_in_db,
            "with_diffs": summary.with_diffs,
            "perfect": summary.perfect,
            "errors": summary.errors,
        },
        "diff_rows_count": len(diff_rows),
        "reports": report_paths
    }
