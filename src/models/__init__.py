# Todos los modelos principales
from src.models.AttachmentsModel import Attachments
from src.models.BldgDeptModel import BuildingDept
from src.models.ChangeOrderModel import ChangeOrder
from src.models.ChatModel import ChatMessage
from src.models.ClientModel import Client
from src.models.EstimateCostModel import EstimateCost
from src.models.FinancialDocItemModel import FinancialDoc_Item
from src.models.FinancialDocModel import FinancialDocument
from src.models.FinancialTransModel import FinancialTransaction
from src.models.JobModel import Job
from src.models.ManagerModel import Manager
from src.models.MemberModel import Member
from src.models.MultiplierRModel import MultiplierR
from src.models.OpportunitiesModel import Opportunities
from src.models.OrderModel import Order
from src.models.ParentMgmtCoModel import ParentMgmtCo
from src.models.PaymentUnitModel import PaymentUnit
from src.models.PermissionModel import Permission
from src.models.PurchaseModel import Purchase
from src.models.PurchaseOrderModel import PurchaseOrder
from src.models.PurchaseOrderItemModel import PurchaseOrderItem
from src.models.RoleModel import Role
from src.models.SkillsModel import Skills
from src.models.StandardPSModel import StandardPS
from src.models.SubcontractorModel import Subcontractor
from src.models.SupplierModel import Supplier
from src.models.TasksModel import Tasks
from src.models.TechnicianModel import Technician
from src.models.TLActivityModel import TLActivity

# Modelos de links de las relaciones N:M
from src.models.link_models.ClientLinks import ClientMemberLink, ClientManagerLink
from src.models.link_models.FinancialLink import FinancialLink
from src.models.link_models.JobMember import JobMemberLink
from src.models.link_models.JobMultiplierR import JobMultiplierRLink
from src.models.link_models.JobSubcontractor import JobSubcontractorLink
from src.models.link_models.JobPaymentU import JobPaymentULink
from src.models.link_models.OpportunitiesLinks import OpportSkillsLink, OpportSubcLink
from src.models.link_models.PermissionLinks import PermissionRoleLink, PermissionMemberLink, PermissionTechLink
from src.models.link_models.PurchaseSupplier import PurchaseSupplierLink
from src.models.link_models.SkillsSubcontractor import SkillsSubcLink

# Modelo para guardar autenticación de QBO
from src.models.QBOTokensModel import QuickBooksToken
