def build_job_data(job_id: str) -> dict:
    # Aquí iría la lógica real: DB, cálculos, integración externa, etc.
    return {
        "id": job_id,
        "Job_type": "Construction",
        "Project_Name": "Miami Residential Tower",
        "Project_Location": "1234 Biscayne Blvd, Miami, FL 33132, USA",
        "Job_Status": "In Progress",
        "PO_WTN_WO_QID": "PO-98321",
        "Service_Type": "Structural Engineering",
        "Date_Assigned": "2025-08-15",
        "Estimated_Start_Date": "2025-09-01",
        "Estimated_Project_Duration": "180 days",
        "GQM_Formula_Pricing": 1250000.00,
        "GQM_Adj_Formula_Pricing": 1285000.00,
        "GQM_Target_Sold_Pricing": 1350000.00,
        "GQM_Premium_in_$": 50000.00,
        "GQM_Final_Sold_Pricing": 1400000.00,
        "GQM_Final_%": 12.5,
        "GQM_Total_Change_Orders_QID": 3,
        "ID_Member": "MBR1022",
        "ID_Cliente": "CLI2099",
    }
