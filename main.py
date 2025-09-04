# ---------------------- EJEMPLO DE API ----------------------
from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route('/')
def root():
    return "Home"

@app.route("/jobs/<job_id>")
def get_user(job_id):
    #jobs = {"id":user_id,"name":"test","telefono":"999-666-333"}
    jobs = {
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
        "ID_Cliente": "CLI2099"
        }

    # /users/2654?query=query_test
    # /jobs/QID51253?query=query_test
    query = request.args.get("query")
    if query:
        jobs["query"] = query
    return jsonify(jobs), 200

@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    data["status"]="user created"
    return jsonify(data), 201

if __name__=='__main__':
    app.run(debug=True)