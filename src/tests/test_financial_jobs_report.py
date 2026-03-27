# test_jobs_report.py
# Corre desde la raíz: python -m src.tests.test_jobs_report
# o ajusta el import según tu estructura

from src.services.reports.financial_jobs_pdf import build_job_financial_report
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))


MOCK = {
    "filters": {
        "year": 2026, "month": None,
        "job_type": "QID", "rep": None, "client_id": None,
    },
    "summary": {
        "job_count": 312, "paid_count": 194,
        "total_quoted":    4_850_000,
        "total_formula":   3_200_000,
        "total_adj_formula": 3_100_000,
        "total_final_sold":  4_210_000,
        "total_premium":     1_110_000,
        "avg_final_pct":     86.8,
        "avg_target_ret":    22.4,
        "final_vs_quoted_pct": 86.8,
    },
    "pipeline": 1_240_000,
    "monthly": [
        {"month": f"2026-{m:02d}", "month_name": name, "jobs": jobs, "paid_jobs": paid,
         "quoted": q, "formula": q*0.67, "adj_formula": q*0.65,
         "final_sold": f, "premium": f - q*0.65, "avg_final_pct": pct, "final_pct": pct}
        for m, name, jobs, paid, q, f, pct in [
            (1, "January",   22, 18, 340000, 298000, 87.6),
            (2, "February",  28, 21, 420000, 365000, 86.9),
            (3, "March",     35, 26, 510000, 445000, 87.3),
            (4, "April",     30, 22, 460000, 400000, 86.9),
            (5, "May",       27, 19, 390000, 338000, 86.7),
            (6, "June",      32, 24, 480000, 418000, 87.1),
            (7, "July",      26, 18, 380000, 328000, 86.3),
            (8, "August",    29, 21, 430000, 374000, 87.0),
            (9, "September", 24, 17, 360000, 312000, 86.7),
            (10, "October",  31, 23, 465000, 405000, 87.1),
            (11, "November", 28, 20, 415000, 361000, 87.0),
            (12, "December", 20, 15, 300000, 262000, 87.3),
        ]
    ],
    "quarterly": [
        {"quarter": "2026-Q1", "jobs": 85,  "paid_jobs": 65, "quoted": 1270000, "formula": 851000,
            "final_sold": 1108000, "premium": 257000, "avg_final_pct": 87.2, "final_pct": 87.2},
        {"quarter": "2026-Q2", "jobs": 89,  "paid_jobs": 65, "quoted": 1330000, "formula": 892000,
            "final_sold": 1156000, "premium": 264000, "avg_final_pct": 86.9, "final_pct": 86.9},
        {"quarter": "2026-Q3", "jobs": 79,  "paid_jobs": 56, "quoted": 1170000, "formula": 784000,
            "final_sold": 1014000, "premium": 230000, "avg_final_pct": 86.7, "final_pct": 86.7},
        {"quarter": "2026-Q4", "jobs": 79,  "paid_jobs": 58, "quoted": 1180000, "formula": 791000,
            "final_sold": 1028000, "premium": 237000, "avg_final_pct": 87.1, "final_pct": 87.1},
    ],
    "rep": [
        {"rep": "Carlos Medina",   "jobs": 82,  "paid": 55, "quoted": 1280000,
            "final": 1112000, "premium": 312000, "avg_final_pct": 86.9, "final_pct": 86.9},
        {"rep": "Laura Torres",    "jobs": 76,  "paid": 50, "quoted": 1190000,
            "final": 1035000, "premium": 288000, "avg_final_pct": 87.0, "final_pct": 87.0},
        {"rep": "Miguel Vargas",   "jobs": 68,  "paid": 44, "quoted": 1050000,
            "final":  910000, "premium": 254000, "avg_final_pct": 86.7, "final_pct": 86.7},
        {"rep": "Sofía Restrepo",  "jobs": 54,  "paid": 33, "quoted":  840000,
            "final":  730000, "premium": 198000, "avg_final_pct": 86.9, "final_pct": 86.9},
        {"rep": "Andrés Ríos",     "jobs": 32,  "paid": 18, "quoted":  490000,
            "final":  423000, "premium": 118000, "avg_final_pct": 86.3, "final_pct": 86.3},
    ],
    "status": [
        {"status": "PAID",        "count": 194, "pct": 62.2,
            "quoted": 3020000, "final": 2625000, "premium": 728000},
        {"status": "PENDING",     "count":  58, "pct": 18.6,
            "quoted":  902000, "final":       0, "premium":      0},
        {"status": "IN PROGRESS", "count":  34, "pct": 10.9,
            "quoted":  527000, "final":       0, "premium":      0},
        {"status": "PARTIAL",     "count":  12, "pct":  3.8,
            "quoted":  186000, "final":   88000, "premium":  18000},
        {"status": "OVERDUE",     "count":   8, "pct":  2.6,
            "quoted":  124000, "final":       0, "premium":      0},
        {"status": "CANCELLED",   "count":   6, "pct":  1.9,
            "quoted":   91000, "final":       0, "premium":      0},
    ],
    "service": [
        {"service": "Paint",       "count": 98,  "final": 1480000,
            "premium": 412000, "avg_final_pct": 87.2},
        {"service": "Drywall",     "count": 72,  "final": 1090000,
            "premium": 298000, "avg_final_pct": 86.8},
        {"service": "Flooring",    "count": 54,  "final":  820000,
            "premium": 228000, "avg_final_pct": 86.9},
        {"service": "Roofing",     "count": 38,  "final":  580000,
            "premium": 162000, "avg_final_pct": 87.1},
        {"service": "Carpentry",   "count": 28,  "final":  420000,
            "premium": 118000, "avg_final_pct": 86.7},
        {"service": "Electrical",  "count": 12,  "final":  180000,
            "premium":  48000, "avg_final_pct": 86.5},
        {"service": "Plumbing",    "count":  8,  "final":  120000,
            "premium":  32000, "avg_final_pct": 86.4},
        {"service": "Other",       "count":  2,  "final":   30000,
            "premium":   8000, "avg_final_pct": 86.2},
    ],
    "jobs": [
        {
            "job_id":      f"QID{50000+i:05d}",
            "client":      ["Residencial Norte", "Torre Pacífico", "Conjunto Las Palmas",
                            "Club Campestre", "Edificio Coral"][i % 5],
            "rep":         ["Carlos Medina", "Laura Torres", "Miguel Vargas",
                            "Sofía Restrepo", "Andrés Ríos"][i % 5],
            "status":      ["PAID", "PAID", "PAID", "PENDING", "IN PROGRESS",
                            "PARTIAL", "OVERDUE", "CANCELLED"][i % 8],
            "service":     ["Paint", "Drywall", "Flooring", "Roofing", "Carpentry"][i % 5],
            "date":        f"2026-{(i % 12)+1:02d}-{(i % 28)+1:02d}",
            "formula":     12000 + i * 150,
            "adj_formula": 11500 + i * 148,
            "target":      14000 + i * 180,
            "final":       13800 + i * 175 if i % 8 != 7 else 0,
            "pct":         86.5 + (i % 5) * 0.2,
            "premium":     2300 + i * 27 if i % 8 not in (3, 4, 6, 7) else 0,
        }
        for i in range(60)   # 60 jobs para probar chunking
    ],
}

if __name__ == "__main__":
    output = "jobs_report_TEST.pdf"
    print("Generando PDF de prueba...")
    pdf = build_job_financial_report(
        MOCK,
        company_name="Senavia Corp",
        logo_path=None,
    )
    with open(output, "wb") as f:
        f.write(pdf)
    print(f"✅  {output}  ({len(pdf):,} bytes)")
