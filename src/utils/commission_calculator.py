from sqlmodel import select, Session, func
from src.models.JobModel import Job
from src.models.CommissionModel import Commission
from src.models.ComGroupModel import CommissionGroup
from src.models.ComDetailModel import CommissionDetail
from src.models.ReimbursementModel import Reimbursement


def calculate_sell_mgmt(factor: float, premium: float) -> float:
    return round((factor or 0) * (premium or 0), 2)


def recalculate_all(detail: CommissionDetail, session: Session):
    """Recalcula totales, reembolsos, margen con regla de oro y aplicabilidad."""

    # 1. Actualizar el Total_detail del Grupo (Suma de Sell_Mgmt)
    if detail.ID_ComGroup:
        total_group = session.exec(
            select(func.sum(CommissionDetail.Sell_Mgmt))
            .where(CommissionDetail.ID_ComGroup == detail.ID_ComGroup)
        ).one() or 0

        group = session.get(CommissionGroup, detail.ID_ComGroup)
        if group:
            group.Total_detail = round(total_group, 2)
            session.add(group)
            session.flush()

            # 2. Actualizar la Comisión Principal
            main_comm = session.get(Commission, group.ID_Commission)
            if main_comm:
                # --- A. Total_commission (Suma de Grupos) ---
                total_comm = session.exec(
                    select(func.sum(CommissionGroup.Total_detail))
                    .where(CommissionGroup.ID_Commission == main_comm.ID_Commission)
                ).one() or 0
                main_comm.Total_commission = round(total_comm, 2)

                # --- B. Total_margin (Regla de Oro: Doble Rol) ---
                # Buscamos los Premiums de todos los Jobs en esta comisión
                stmt_margin = (
                    select(Job.Gqm_final_prem_in_money,
                           CommissionGroup.Jobs_type, CommissionGroup.Rol)
                    .join(CommissionDetail, CommissionDetail.ID_Jobs == Job.ID_Jobs)
                    .join(CommissionGroup, CommissionGroup.ID_ComGroup == CommissionDetail.ID_ComGroup)
                    .where(CommissionGroup.ID_Commission == main_comm.ID_Commission)
                )
                results = session.exec(stmt_margin).all()

                # Mapeo para detectar si un tipo de Job (QID, PTL, etc) tuvo 1 o 2 roles
                margin_map = {}  # { "QID": {"suma": 0, "roles": set()} }
                for premium, j_type, rol in results:
                    if j_type not in margin_map:
                        margin_map[j_type] = {"suma": 0, "roles": set()}
                    margin_map[j_type]["suma"] += (premium or 0)
                    margin_map[j_type]["roles"].add(rol)

                total_margin_acumulado = 0
                for data in margin_map.values():
                    # REGLA DE ORO: Si tuvo ambos roles para el mismo tipo, dividir suma entre 2
                    if len(data["roles"]) > 1:
                        total_margin_acumulado += (data["suma"] / 2)
                    else:
                        total_margin_acumulado += data["suma"]

                main_comm.Total_margin = round(total_margin_acumulado, 2)

                # --- C. Is_Applicable (Paola vs Resto) ---
                # Paola ID: MEM60005
                threshold = 18000 if main_comm.ID_Member == "MEM60005" else 13000
                main_comm.Applicable = main_comm.Total_margin > threshold

                session.add(main_comm)


def update_commission_reimbursement_total(commission_id: str, session: Session):
    """Recalcula y actualiza el Total_reimbursement en la tabla Commission."""
    if not commission_id:
        return

    total = session.exec(
        select(func.sum(Reimbursement.Value))
        .where(Reimbursement.ID_Commission == commission_id)
    ).one() or 0

    commission = session.get(Commission, commission_id)
    if commission:
        commission.Total_reimbursement = round(total, 2)
        session.add(commission)
        session.flush()
