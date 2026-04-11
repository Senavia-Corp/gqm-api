from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class JobBasicColumn(str, Enum):
    ID_JOBS = "ID_Jobs"
    JOB_TYPE = "Job_type"
    PROJECT_NAME = "Project_name"
    PROJECT_LOCATION = "Project_location"
    JOB_STATUS = "Job_status"
    PO_WTN_WO = "Po_wtn_wo"
    SERVICE_TYPE = "Service_type"
    DATE_ASSIGNED = "Date_assigned"
    DATE_ASSIGNED_END = "Date_assigned_end"
    ESTIMATED_START_DATE = "Estimated_start_date"
    ESTIMATED_START_DATE_END = "Estimated_start_date_end"
    ESTIMATED_PROJECT_DURATION = "Estimated_project_duration"
    DATE_RECEIVED = "Date_Received"
    ESTIMATED_COMPLETION_DATE = "Estimated_completion_date"
    ADDITIONAL_DETAIL = "Additional_detail"
    ESTIMATED_RENT = "Estimated_rent"
    ESTIMATED_MATERIAL = "Estimated_material"
    ESTIMATED_CITY = "Estimated_city"
    TECH_FORMULA_PRICING = "Tech_formula_pricing"
    GQM_FORMULA_PRICING = "Gqm_formula_pricing"
    GQM_FINAL_SOLD_PRICING = "Gqm_final_sold_pricing"
    GQM_TOTAL_CHANGE_ORDERS = "Gqm_total_change_orders"
    GQM_TOTAL_MATERIALS_FEES = "Gqm_total_materials_fees"
    ACC_RECEIVABLE = "Acc_receivable"
    PERMIT = "Permit"
    PTL_GC_FEE = "Ptl_gc_fee"
    GQM_PAID_FEES = "Gqm_paid_fees"


class JobExportFilters(BaseModel):
    """
    Filtros combinables. La fecha se aplica por tipo de Job:
      PTL       → Estimated_start_date  (AND dentro del rango)
      QID / PAR → Date_assigned         (AND dentro del rango)
    Si se mezclan tipos se aplica OR entre bloques de tipo.
    """
    statuses:           Optional[List[str]] = None
    member_ids:         Optional[List[str]] = None
    job_types:          Optional[List[str]] = None
    date_from:          Optional[datetime] = None
    date_to:            Optional[datetime] = None
    search:             Optional[str] = None
    client_id:          Optional[str] = None
    parent_mgmt_co_id:  Optional[str] = None


class JobExportColumns(BaseModel):
    basic_fields:           List[JobBasicColumn] = list(JobBasicColumn)
    include_client:         bool = True
    include_members:        bool = True
    include_subcontractors: bool = True
    include_commissions:    bool = True
    include_purchases:      bool = True
    include_estimate_costs: bool = True


class JobExportRequest(BaseModel):
    filters: JobExportFilters = JobExportFilters()
    columns: JobExportColumns = JobExportColumns()
