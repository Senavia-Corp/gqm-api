class Job():
    def __init__(self, id_job, project_name=None, project_location=None, job_status=None) -> None:
        self.id_job = id_job
        self.project_name = project_name
        self.project_location = project_location
        self.job_status = job_status

    def to_JSON(self):
        return {
            'id_job': self.id_job,
            'project_name': self.project_name,
            'project_location': self.project_location,
            'job_status': self.job_status
        }