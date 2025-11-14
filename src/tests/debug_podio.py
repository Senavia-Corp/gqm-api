from flask import Blueprint, request, jsonify

debug_bp = Blueprint("debug_webhook", __name__)


@debug_bp.route("/webhook/debug_podio", methods=["POST"])
def debug_podio_webhook():
    # Imprimir el payload crudo
    raw_data = request.get_data(as_text=True)
    print("🔹 Payload crudo recibido:", raw_data)

    # Intentar parsear JSON
    try:
        data = request.get_json(force=True)
        print("📩 Webhook JSON parseado:", data)
    except Exception as e:
        print("❌ Error parseando JSON:", e)
        return jsonify({"error": str(e)}), 400

    # Detectar tipo de evento
    event_type = data.get("type")
    if event_type:
        print(f"📌 Tipo de evento: {event_type}")
    else:
        print("⚠️ No se encontró 'type' en el payload")

    # Si hay item_id
    if "item_id" in data:
        print(f"🆔 item_id recibido: {data['item_id']}")

    # Podio envía ping al registrar webhook
    if event_type == "hook.verify":
        print("📬 Ping recibido de Podio (hook.verify)")

    return jsonify({"status": "ok"}), 200
