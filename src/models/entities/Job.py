class Job():
    def __init__(self, id_job, project_name=None, project_location=None, job_status=None, po_wtn_wo=None, service_type=None,
                 date_assigned=None, gqm_formula_pricing=None, gqm_adj_formula_pricing=None, gqm_target_sold_pricing=None,
                 gqm_premium_in_money=None, gqm_final_sold_pricing=None, gqm_final_percentage=None, 
                 gqm_total_change_orders=None, id_member=None, id_client=None) -> None:
        self.id_job = id_job
        self.project_name = project_name
        self.project_location = project_location
        self.job_status = job_status
        self.po_wtn_wo = po_wtn_wo
        self.service_type = service_type
        self.date_assigned = date_assigned
        self.gqm_formula_pricing = gqm_formula_pricing
        self.gqm_adj_formula_pricing = gqm_adj_formula_pricing
        self.gqm_target_sold_pricing = gqm_target_sold_pricing
        self.gqm_premium_in_money = gqm_premium_in_money
        self.gqm_final_sold_pricing = gqm_final_sold_pricing
        self.gqm_final_percentage = gqm_final_percentage
        self.gqm_total_change_orders = gqm_total_change_orders
        self.id_member = id_member
        self.id_client = id_client

    def to_JSON(self):
        return {
            'id_job': self.id_job,
            'project_name': self.project_name,
            'project_location': self.project_location,
            'job_status': self.job_status,
            'po_wtn_wo': self.po_wtn_wo,
            'service_type': self.service_type,
            'date_assigned': self.date_assigned,
            'gqm_formula_pricing': self.gqm_formula_pricing,
            'gqm_adj_formula_pricing': self.gqm_adj_formula_pricing,
            'gqm_target_sold_pricing': self.gqm_target_sold_pricing,
            'gqm_premium_in_money': self.gqm_premium_in_money,
            'gqm_final_sold_pricing': self.gqm_final_sold_pricing,
            'gqm_final_percentage': self.gqm_final_percentage,
            'gqm_total_change_orders': self.gqm_total_change_orders,
            'id_member': self.id_member,
            'id_client': self.id_client
        }