from database.db import get_connection
from .entities.Job import Job

class JobModel():

    @classmethod
    def get_jobs(self):
        try:
            connection=get_connection()           
            jobs=[]

            with connection.cursor() as cursor:
                cursor.execute("SELECT id_job, project_name, project_location, job_status FROM job ORDER BY project_name ASC") #A esta sentencia se le puede agregar más comandos SQL para hacerla más específica
                resultset=cursor.fetchall()
                
                for row in resultset:
                    job=Job(row[0],row[1],row[2],row[3])
                    jobs.append(job.to_JSON())

            connection.close()
            return jobs
        except Exception as ex:
            raise Exception(ex)
        
    #to obtain a single job using the ID
    @classmethod
    def get_job(self,id_job):
        try:
            connection=get_connection()

            with connection.cursor() as cursor:
                cursor.execute("SELECT id_job, project_name, project_location, job_status FROM job WHERE id_job = %s",(id_job,))
                row = cursor.fetchone()
                
                job=None
                if row != None:
                    job = Job(row[0],row[1],row[2],row[3])
                    job = job.to_JSON()

            connection.close()
            return job
        except Exception as ex:
            raise Exception(ex)
        
    #to add a single job using the ID
    @classmethod
    def add_job(self, job):
        try:
            connection=get_connection()

            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO job(id_job, project_name, project_location, job_status) 
                               VALUES (%s,%s,%s,%s)""", (job.id_job, job.project_name, job.project_location, job.job_status))
                affected_rows=cursor.rowcount
                connection.commit()

            connection.close()
            return affected_rows
        except Exception as ex:
            raise Exception(ex)
        
    #to Update a Job
    @classmethod
    def update_job(self, job):
        try:
            connection=get_connection()

            with connection.cursor() as cursor:
                cursor.execute("""UPDATE job SET project_name = %s,project_location = %s,job_status = %s 
                               WHERE id_job = %s""", (job.project_name, job.project_location, job.job_status, job.id_job))
                affected_rows=cursor.rowcount
                connection.commit()

            connection.close()
            return affected_rows
        except Exception as ex:
            raise Exception(ex)
        
    #to Delete a job
    @classmethod
    def delete_job(self, job):
        try:
            connection=get_connection()

            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM job WHERE id_job = %s", (job.id_job,))
                affected_rows=cursor.rowcount
                connection.commit()

            connection.close()
            return affected_rows
        except Exception as ex:
            raise Exception(ex)