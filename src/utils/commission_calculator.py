from sqlmodel import select, Session
from src.models import CommissionDetail, CommissionGroup, Commission


def calculate_sell_mgmt(factor: float, premium: float) -> float:
    return round(factor * premium, 2)


def calculate_total_detail(id_comgroup: str, session: Session) -> float:
    statement = (
        select(CommissionDetail)
        .where(CommissionDetail.ID_ComGroup == id_comgroup)
    )
    details = session.exec(statement).all()
    return round(sum(d.Sell_Mgmt or 0 for d in details), 2)


def calculate_total_commission(id_commission: str, session: Session) -> float:
    statement = (
        select(CommissionGroup)
        .where(CommissionGroup.ID_Commission == id_commission)
    )
    groups = session.exec(statement).all()
    return round(sum(g.Total_detail or 0 for g in groups), 2)


def recalculate_all(detail: CommissionDetail, session: Session):

    # Usamos el valor directamente por si el objeto fue desvinculado
    id_comgroup = detail.ID_ComGroup  # ya es un string, no hace query a BD

    comgroup = session.get(CommissionGroup, id_comgroup)
    if comgroup:
        comgroup.Total_detail = calculate_total_detail(id_comgroup, session)
        session.add(comgroup)

        commission = session.get(Commission, comgroup.ID_Commission)
        if commission:
            commission.Total_commission = calculate_total_commission(
                comgroup.ID_Commission, session)
            session.add(commission)
