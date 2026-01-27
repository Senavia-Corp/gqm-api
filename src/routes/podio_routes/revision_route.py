from flask import Blueprint, request, jsonify
from sqlmodel import select

from src.database.db_sqlmodel import get_session
from src.podio.services.podio_base_services import PodioBaseService
from src.podio.sync.sync_revision import PODIO_SYNC_REGISTRY

sync_revision_bp = Blueprint(
    "sync_revision", __name__, url_prefix="/sync_revision")


@sync_revision_bp.post("/podio")
def reconcile_podio():
    data = request.get_json()

    app_id = data.get("app_id")
    model_key = data.get("model")
    limit = data.get("limit", 30)
    offset = data.get("offset", 0)
    dry_run = data.get("dry_run", False)

    print("\n🔄 PODIO RECONCILE START")
    print(f"   • app_id: {app_id}")
    print(f"   • model: {model_key}")
    print(f"   • limit: {limit}")
    print(f"   • offset: {offset}")
    print("-" * 50)

    cfg = PODIO_SYNC_REGISTRY.get(model_key)
    if not cfg:
        print("❌ Model no registrado")
        return jsonify({"error": "Model no registrado"}), 400

    service = PodioBaseService(
        app_type=cfg["app_type"],
        app_id=app_id
    )
    items = service.get_items(limit=limit, offset=offset)

    print(f"\n📥 Batch recibido: {len(items)} items desde Podio\n")

    if not items:
        print("✅ No hay más items")
        return jsonify({"message": "No hay más items"}), 200

    created = updated = skipped = 0

    with get_session() as session:
        for idx, item in enumerate(items, start=1):
            mapped = cfg["mapper"](item)
            podio_item_id = mapped.get("podio_item_id")

            print(f"➡️ [{idx}/{len(items)}] podio_item_id={podio_item_id}")

            db_obj = session.exec(
                select(cfg["model"]).where(
                    cfg["model"].podio_item_id == podio_item_id
                )
            ).first()

            # ---------------- CREATE ----------------
            if not db_obj:
                created += 1
                print("   🟢 NO EXISTE en DB → CREATE")

                if not dry_run:
                    session.add(cfg["model"](**mapped))
                continue

            # ---------------- COMPARE ----------------
            changes = {
                k: v for k, v in mapped.items()
                if v is not None and getattr(db_obj, k) != v
            }

            if not changes:
                skipped += 1
                print("   ⚪ SIN CAMBIOS → skip")
                continue

            updated += 1
            print(f"   🟡 EXISTE en DB")
            print(f"   🔍 Cambios detectados: {list(changes.keys())}")

            if not dry_run:
                for k, v in changes.items():
                    setattr(db_obj, k, v)
                print("   🔧 PATCH aplicado")

        if not dry_run:
            session.commit()

    print("-" * 50)
    print("✅ BATCH FINALIZADO")
    print(f"   • processed: {len(items)}")
    print(f"   • created: {created}")
    print(f"   • updated: {updated}")
    print(f"   • skipped: {skipped}")
    print(f"   • dry_run: {dry_run}")
    print("-" * 50)

    return jsonify({
        "processed": len(items),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "limit": limit,
        "offset": offset,
        "dry_run": dry_run
    }), 200
