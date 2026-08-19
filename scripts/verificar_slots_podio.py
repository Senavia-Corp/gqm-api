"""Comprueba, contra Podio, que la posición en la base es la posición real.

## Por qué existe

La migración de relleno (`b2e5c8d16f22`) congela como verdad lo que hoy es una
deducción: que el orden de los registros en la base coincide con el orden de los
huecos en Podio. **Nada lo garantiza.** Si alguien reordenó o vació valores a
mano, el relleno congelaría una correspondencia falsa y a partir de ahí la app
escribiría importes correctos en huecos equivocados — silencioso y permanente.

Este script mira los dos lados y lo dice antes de que pase. **Sólo lectura**:
nunca escribe en Podio, y sólo toca la base con `--corregir`.

## Uso

    python scripts/verificar_slots_podio.py                 # informe
    python scripts/verificar_slots_podio.py --corregir      # ajusta podio_field

`--corregir` reasigna cada registro al hueco cuyo importe coincide; los casos
ambiguos (varios huecos con el mismo importe, o ninguno) se dejan a NULL y se
listan, porque a NULL el código cae al comportamiento de siempre.
"""
import argparse
import sys
from collections import defaultdict

from sqlmodel import select

sys.path.insert(0, ".")

from src.database.db_sqlmodel import get_session          # noqa: E402
from src.models.JobModel import Job                        # noqa: E402
from src.podio.services.job_services import podio_jobs_router  # noqa: E402
from src.utils import podio_slots                          # noqa: E402

TOLERANCIA = 0.01


def _importes_en_podio(item, fam) -> dict:
    """`{external_id: importe}` de los huecos que traen valor en el ítem."""
    from src.podio.webhook.jobs_hook_sync import _valor_money_del_item

    fuera = {}
    for ext in fam.external_ids:
        presente, val = _valor_money_del_item(item, ext)
        if presente and val is not None:
            fuera[ext] = val
    return fuera


def revisar(session, job, fam, servicio) -> dict:
    registros = podio_slots.registros(session, fam, job.ID_Jobs)
    if not registros:
        return {}

    item = servicio.get_item(int(job.podio_item_id))
    en_podio = _importes_en_podio(item, fam)

    en_bd = podio_slots.payload_por_slot(session, fam, job.ID_Jobs)
    en_bd.update(podio_slots.slots_legacy_posicionales(session, fam, job.ID_Jobs))

    coincide, difiere, solo_podio, solo_bd = [], [], [], []
    for ext in fam.external_ids:
        p, b = en_podio.get(ext), en_bd.get(ext)
        if p is None and b is None:
            continue
        if p is None:
            solo_bd.append((ext, b))
        elif b is None:
            solo_podio.append((ext, p))
        elif abs(p - b) < TOLERANCIA:
            coincide.append((ext, p))
        else:
            difiere.append((ext, b, p))

    return {"job": job.ID_Jobs, "familia": fam.clave, "registros": len(registros),
            "coincide": coincide, "difiere": difiere,
            "solo_podio": solo_podio, "solo_bd": solo_bd, "item": item}


def corregir(session, job, fam, informe) -> list:
    """Reasigna cada registro al hueco cuyo importe coincide. Lo ambiguo, a NULL."""
    en_podio = _importes_en_podio(informe["item"], fam)
    por_importe = defaultdict(list)
    for ext, val in en_podio.items():
        por_importe[round(val, 2)].append(ext)

    cambios = []
    for r in podio_slots.registros(session, fam, job.ID_Jobs):
        val = None
        for p in fam.propietarios:
            if isinstance(r, p.modelo):
                v = getattr(r, p.attr_importe, None)
                val = None if v is None else round(float(v), 2)
                break
        candidatos = por_importe.get(val, [])
        antes = getattr(r, "podio_field", None)
        if len(candidatos) == 1:
            r.podio_field = candidatos[0]
            por_importe[val] = []
        else:
            r.podio_field = None       # ambiguo: mejor el respaldo posicional
        if r.podio_field != antes:
            session.add(r)
            cambios.append((job.ID_Jobs, fam.clave, antes, r.podio_field, val,
                            "ambiguo" if len(candidatos) != 1 else "ok"))
    return cambios


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corregir", action="store_true",
                    help="ajusta podio_field en la base (por defecto sólo informa)")
    ap.add_argument("--anio", type=int, default=None, help="limitar a un año de app")
    args = ap.parse_args(argv)

    familias = [podio_slots.familia(k) for k in ("QID.bldg_dept_fees", "QID.purchases_list")]
    problemas, cambios, revisados = [], [], 0

    with get_session() as session:
        q = select(Job).where(Job.Job_type == "QID", Job.podio_item_id.is_not(None))
        if args.anio:
            q = q.where(Job.podio_app_year == args.anio)

        for job in session.exec(q).all():
            if not any(podio_slots.registros(session, f, job.ID_Jobs) for f in familias):
                continue
            anio = job.podio_app_year or args.anio
            if not anio:
                print(f"  ⚠️  {job.ID_Jobs}: sin año de app resoluble, se salta")
                continue
            servicio = podio_jobs_router.get_readonly_service("QID", anio)

            for fam in familias:
                inf = revisar(session, job, fam, servicio)
                if not inf:
                    continue
                revisados += 1
                if inf["difiere"] or inf["solo_bd"] or inf["solo_podio"]:
                    problemas.append(inf)
                    print(f"  ✗ {job.ID_Jobs} · {fam.clave}")
                    for ext, b, p in inf["difiere"]:
                        print(f"      {ext:26} base={b:>12.2f}  podio={p:>12.2f}")
                    for ext, b in inf["solo_bd"]:
                        print(f"      {ext:26} base={b:>12.2f}  podio=       (vacío)")
                    for ext, p in inf["solo_podio"]:
                        print(f"      {ext:26} base=       (nadie)  podio={p:>12.2f}")
                    if args.corregir:
                        cambios += corregir(session, job, fam, inf)
                else:
                    print(f"  ✓ {job.ID_Jobs} · {fam.clave} ({len(inf['coincide'])} huecos)")

        if args.corregir and cambios:
            session.commit()

    print(f"\n{revisados} (job, familia) revisados · {len(problemas)} con diferencias")
    if args.corregir:
        print(f"{len(cambios)} podio_field ajustados")
        for c in cambios:
            print("   ", c)
    elif problemas:
        print("Informe solamente. Con --corregir se ajusta podio_field por importe.")
    return 1 if problemas and not args.corregir else 0


if __name__ == "__main__":
    raise SystemExit(main())
