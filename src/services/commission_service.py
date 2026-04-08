from sqlmodel import Session, select
from datetime import datetime
from src.models.JobModel import Job
from src.models.link_models.JobMember import JobMemberLink
from src.models.ComDetailModel import CommissionDetail
from src.models.ComGroupModel import CommissionGroup
from src.models.CommissionModel import Commission
from src.utils.commission_calculator import recalculate_all
from src.utils.id_generator import generate_custom_id
from src.utils.middleware.logs.logs import logger


def process_job_to_commissions(job: Job, session: Session):
    """
    Se dispara cuando el Job pasa a PAID. 
    Usa el timestamp del momento de ejecución para definir Mes y Año.
    """

    # 🛡️ VALIDACIÓN ANTI-DUPLICADOS
    existing_check = session.exec(
        select(CommissionDetail).where(CommissionDetail.ID_Jobs == job.ID_Jobs)
    ).first()

    if existing_check:
        logger.info(
            "⚠️ Comisiones ya existentes para Job %s. Omitiendo.", job.ID_Jobs)
        return

    # --- 1. Definir Periodo (Timestamp del cambio de estado) ---
    now = datetime.now()
    month_str = now.strftime("%B")  # Ej: "March"
    year_int = now.year

    # --- 2. Lógica de Type ---
    target = job.Gqm_target_return or 0
    final = job.Gqm_final_percentage or 0
    calc_type = "Standard" if target < final else "Non-Comp"

    # --- 3. Buscar Miembros en JobMemberLink ---
    members_stmt = select(JobMemberLink).where(
        JobMemberLink.job_id == job.ID_Jobs)
    members_links = session.exec(members_stmt).all()

    for link in members_links:
        # --- 3.5 Filtro de Roles Excluidos ---
        if link.rol == "Lead Member":
            logger.info(
                "⏭️ Omitiendo comisiones para Lead Member: %s", link.member_id)
            continue  # Salta al siguiente miembro sin hacer nada

        # --- 4. Obtener/Crear Commission (Cabecera Mensual) ---
        comm_obj = session.exec(
            select(Commission).where(
                Commission.ID_Member == link.member_id,
                Commission.Month == month_str,
                Commission.Year == year_int
            )
        ).first()

        if not comm_obj:
            comm_obj = Commission(
                ID_Member=link.member_id,
                Month=month_str,
                Year=year_int,
                Total_commission=0
            )

            comm_obj.ID_Commission = generate_custom_id(
                session, Commission, "ID_Commission", "COM")

            session.add(comm_obj)
            session.flush()

        # --- 5. Obtener/Crear CommissionGroup (Por Rol y Tipo de Job) ---
        group_stmt = select(CommissionGroup).where(
            CommissionGroup.ID_Commission == comm_obj.ID_Commission,
            CommissionGroup.Rol == link.rol,
            CommissionGroup.Jobs_type == job.Job_type
        )
        group_obj = session.exec(group_stmt).first()

        if not group_obj:
            group_obj = CommissionGroup(
                ID_Commission=comm_obj.ID_Commission,
                Rol=link.rol,
                Jobs_type=job.Job_type,
                Jobs_year=year_int,
                Total_detail=0
            )

            group_obj.ID_ComGroup = generate_custom_id(
                session, CommissionGroup, "ID_ComGroup", "CGR")

            session.add(group_obj)
            session.flush()

        # --- 6. Calcular Factor según Matriz ---
        factor = 0.0
        if calc_type == "Standard":
            if link.rol == "Acc Rep Selling":
                factor = 0.036
            elif link.rol == "Mgmt Member":
                factor = 0.018

        # El dinero base para la multiplicación
        money_base = job.Gqm_final_prem_in_money or 0
        sell_mgmt = round(money_base * factor, 2)

        # --- 7. Crear el Detail ---
        new_detail = CommissionDetail(
            ID_ComGroup=group_obj.ID_ComGroup,
            ID_Jobs=job.ID_Jobs,
            Type=calc_type,
            Factor=factor,
            Sell_Mgmt=sell_mgmt
        )
        new_detail.ID_ComDetail = generate_custom_id(
            session, CommissionDetail, "ID_ComDetail", "CDT")

        session.add(new_detail)
        session.flush()

        # --- 8. Recalcular la cadena de totales ---
        recalculate_all(new_detail, session)

    session.commit()
