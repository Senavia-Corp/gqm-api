from flask import Blueprint, jsonify, request
from sqlmodel import select
from ..database.db_sqlmodel import get_session
from ..models.SupplierModel import Supplier, SupplierCreate, SupplierUpdate
from pydantic import ValidationError

supplier_bp = Blueprint("supplier_blueprint", __name__,
                        url_prefix="/suppliers")

# Ruta para conseguir la lista de todos los distribuidores


@supplier_bp.get("/")
def list_suppliers():
    with get_session() as session:
        results = session.exec(select(Supplier)).all()
        return jsonify([obj.model_dump() for obj in results]), 200

# Ruta para conseguir un distruibidor por ID


@supplier_bp.get("/<id_supplier>")
def get_supplier(id_supplier):
    with get_session() as session:
        obj = session.get(Supplier, id_supplier)
        if not obj:
            return jsonify({"error": "Supplier not found"}), 404
        return jsonify(obj.model_dump()), 200

# Ruta para crear un distruibidor


@supplier_bp.post("/")
def create_supplier():
    data = request.get_json()
    create_supplier = SupplierCreate.model_validate(data)
    obj = Supplier.model_validate(create_supplier)
    with get_session() as session:
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return jsonify(obj.model_dump()), 201

# Ruta para actualizar un distruibidor


@supplier_bp.put("/<id_supplier>")
def update_supplier(id_supplier):
    data = request.get_json()
    with get_session() as session:
        obj = session.get(Supplier, id_supplier)
        if not obj:
            return jsonify({"error": "Supplier not found"}), 404

        update_supplier = SupplierUpdate.model_validate(data)
        update_data_dict = update_supplier.model_dump(
            exclude_unset=True)  # Crea dict limpio

        for key, value in update_data_dict.items():  # Recorre poniendo los datos donde van
            setattr(obj, key, value)

        session.add(obj)
        session.commit()
        session.refresh(obj)
        return jsonify(obj.model_dump()), 200

# Ruta para eliminar un distruibidor


@supplier_bp.delete("/<id_supplier>")
def delete_supplier(id_supplier):
    with get_session() as session:
        obj = session.get(Supplier, id_supplier)
        if not obj:
            return jsonify({"error": "Supplier not found"}), 404
        session.delete(obj)
        session.commit()
        return jsonify({"message": f"Deleted Supplier {id_supplier}"}), 200
