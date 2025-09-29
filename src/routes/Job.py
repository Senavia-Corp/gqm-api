from flask import Blueprint, jsonify, request

#Entities
from models.entities.Job import Job
#Models
from models.JobModel import JobModel

main=Blueprint('movie_blueprint',__name__)

#To get all the Jobs
@main.route('/')
def get_jobs():
    try:
        jobs = JobModel.get_jobs()
        return jsonify(jobs)
    except Exception as ex:
        return jsonify({'message':str(ex)}),500

#To get only one Job
@main.route('/<id_job>')
def get_job(id_job):
    try:
        #xxxxx 
        job=JobModel.get_job(id_job)
        if job != None:
            return jsonify(job)
        else:
            return jsonify({'message':"No Job found"}), 404
    except Exception as ex:
        return jsonify({'message':str(ex)}),500

#To add a Job 
@main.route('/add',methods=['POST'])
def add_job():
    try:
        id_job = request.json['id_job']
        project_name = request.json['project_name']
        project_location = request.json['project_location']
        job_status = request.json['job_status']
        po_wtn_wo = request.json['po_wtn_wo']
        service_type = request.json['service_type']
        date_assigned = request.json['date_assigned']
        gqm_formula_pricing = request.json['gqm_formula_pricing']
        gqm_adj_formula_pricing = request.json['gqm_adj_formula_pricing']
        gqm_target_sold_pricing = request.json['gqm_target_sold_pricing']
        gqm_premium_in_money = request.json['gqm_premium_in_money']
        gqm_final_sold_pricing = request.json['gqm_final_sold_pricing']
        gqm_final_percentage = request.json['gqm_final_percentage']
        gqm_total_change_orders = request.json['gqm_total_change_orders']
        id_member = request.json['id_member']
        id_client = request.json['id_client']

        job=Job(id_job, project_name, project_location, job_status, po_wtn_wo, service_type, date_assigned,gqm_formula_pricing,
                gqm_adj_formula_pricing, gqm_target_sold_pricing, gqm_premium_in_money, gqm_final_sold_pricing, 
                gqm_final_percentage, gqm_total_change_orders, id_member,id_client)

        affected_rows=JobModel.add_job(job)

        if affected_rows==1:
            return jsonify({'message':f"Project added: {job.id_job}"})
        else:
            return jsonify({'message':"Error on insert"}),500

    except Exception as ex:
        return jsonify({'message':str(ex)}),500

#To Update a Job
#TAREA: Completar el update para todos los campos de job 
@main.route('/update/<id_job>',methods=['PUT'])
def update_job(id_job):
    try:
        project_name = request.json['project_name']
        project_location = request.json['project_location']
        job_status = request.json['job_status']

        job=Job(id_job, project_name, project_location, job_status)

        affected_rows=JobModel.update_job(job)

        if affected_rows==1:
            return jsonify(job.to_JSON())
        else:
            return jsonify({'message':"No job updated"}),404

    except Exception as ex:
        return jsonify({'message':str(ex)}),500
    

#To delete a Job
@main.route('/delete/<id_job>', methods=['DELETE'])
def delete_job(id_job):
    try:
        job=Job(id_job)

        affected_rows=JobModel.delete_job(job)

        if affected_rows==1:
            return jsonify({'message':f"Project deleted: {job.id_job}"})
        else:
            return jsonify({'message':"No job deleted"}),404

    except Exception as ex:
        return jsonify({'message':str(ex)}),500