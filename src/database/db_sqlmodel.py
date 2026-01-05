from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.exc import SQLAlchemyError
from decouple import config

# Todos los modelos (para evitar problemas con las relaciones en la creación de las tablas en la db)
from src.models.AttachmentsModel import Attachments
# from src.models.ChangeOrderModel import ChangeOrder
from src.models.ClientModel import Client
from src.models.EstimateCostModel import EstimateCost
from src.models.JobModel import Job
from src.models.MemberModel import Member
from src.models.MultiplierRModel import MultiplierR
from src.models.OrderModel import Order
from src.models.ParentMgmtCoModel import ParentMgmtCo
from src.models.PaymentUnitModel import PaymentUnit
from src.models.PropertyManagerModel import PropertyManager
from src.models.SkillsModel import Skills
from src.models.SubcontractorModel import Subcontractor
from src.models.SupplierModel import Supplier
from src.models.TasksModel import Tasks
from src.models.TechnicianModel import Technician
# Modelos de links de las relaciones N:M
from src.models.link_models.ClientPManager import ClientPrManagerLink
from src.models.link_models.ClientMember import ClientMemberLink
from src.models.link_models.JobMember import JobMemberLink
from src.models.link_models.JobMultiplierR import JobMultiplierRLink
from src.models.link_models.JobSubcontractor import JobSubcontractorLink
from src.models.link_models.JobPaymentU import JobPaymentULink

# Configuración para PostgreSQL
DATABASE_URL = config("DATABASE_URL")
# Ver que existan las credenciales
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida en el .env")

engine = create_engine(DATABASE_URL, echo=False)


def init_sqlmodel_db(app=None):
    try:
        # Crea las tablas en la db
        SQLModel.metadata.create_all(engine)

    except SQLAlchemyError as e:  # Si la db no responde o no conecta
        print("Error CRÍTICO: Fallo al inicializar o conectar con la base de datos.")
        print(f"Detalle del error: {e}")
        raise RuntimeError(
            "No se pudo establecer una conexión inicial con la base de datos."
        ) from e  # Útil para depurar

    except Exception as e:  # Captura cualquier otro error inesperado
        print(f"Error inesperado durante la inicialización de la DB: {e}")
        raise  # raise al final del except para que la aplicación se detenga


def get_session():
    # Devuelve sesion lista para usar
    return Session(engine)
