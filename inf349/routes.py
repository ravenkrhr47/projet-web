from flask import Blueprint, jsonify, request, url_for
from playhouse.shortcuts import model_to_dict
from .models import Product, Order, OrderLine, db
from .utils import calculate_shipping, calculate_tax, calculate_total, error

shop_bp = Blueprint("shop", __name__)

# ---------- GET / (liste des produits) ----------
@shop_bp.route("/", methods=["GET"])
def list_products():
    return jsonify({"products": [model_to_dict(p) for p in Product.select()]})

# ---------- POST /order ----------
@shop_bp.route("/order", methods=["POST"])
def create_order():
    data = request.get_json(force=True)
    product_info = data.get("product")
    if not product_info or "id" not in product_info or "quantity" not in product_info:
        error("missing-fields", "La création d'une commande nécessite un produit")

    try:
        prod = Product.get_by_id(product_info["id"])
    except Product.DoesNotExist:
        error("out-of-inventory", "Le produit demandé n'existe pas")

    if not prod.in_stock:
        error("out-of-inventory", "Le produit demandé n'est pas en inventaire")

    qty = int(product_info["quantity"])
    if qty < 1:
        error("missing-fields", "La quantité doit être ≥ 1")

    total = calculate_total(prod.price, qty)
    shipping = calculate_shipping(prod.weight * qty)

    with db.atomic():
        order = Order.create(
            total_price=total,
            total_price_tax=0,  # sera calculé lors du PUT shipping_information
            shipping_price=shipping
        )
        OrderLine.create(order=order, product=prod, quantity=qty)

    resp = jsonify()
    resp.status_code = 302
    resp.headers["Location"] = url_for("shop.get_order", order_id=order.id)
    return resp

# ---------- GET /order/<id> ----------
@shop_bp.route("/order/<int:order_id>", methods=["GET"])
def get_order(order_id):
    order = Order.get_or_none(Order.id == order_id)
    if not order:
        return jsonify({"errors": {"order": {"code": "not-found", "name": "Commande introuvable"}}}), 404
    return jsonify({"order": serialize_order(order)})

# ---------- PUT /order/<id> (client info OU carte de crédit) ----------
@shop_bp.route("/order/<int:order_id>", methods=["PUT"])
def update_order(order_id):
    order = Order.get_or_none(Order.id == order_id)
    if not order:
        return jsonify({"errors": {"order": {"code": "not-found", "name": "Commande introuvable"}}}), 404

    data = request.get_json(force=True)

    # 1) Mise à jour des infos client ---------------------------------------
    if "order" in data:
        info = data["order"]
        required = {"email", "shipping_information"}
        if not required.issubset(info):
            error("missing-fields", "Il manque un ou plusieurs champs qui sont obligatoires")
        ship = info["shipping_information"]
        ship_required = {"country", "address", "postal_code", "city", "province"}
        if not ship_required.issubset(ship):
            error("missing-fields", "Il manque un ou plusieurs champs qui sont obligatoires")

        total_tax = order.total_price + calculate_tax(order.total_price, ship["province"])

        Order.update(
            email=info["email"],
            country=ship["country"],
            address=ship["address"],
            postal_code=ship["postal_code"],
            city=ship["city"],
            province=ship["province"],
            total_price_tax=total_tax
        ).where(Order.id == order.id).execute()

        order.refresh()  # peewee >= 3.17 : recharge l’instance
        return jsonify({"order": serialize_order(order)})

    # 2) Paiement par carte -------------------------------------------------
    if "credit_card" in data:
        if order.paid:
            error("already-paid", "La commande a déjà été payée.")

        if not (order.email and order.country):
            error("missing-fields", "Les informations du client sont nécessaire avant d'appliquer une carte de crédit")

        credit = data["credit_card"]
        amount = order.total_price_tax + order.shipping_price

        from .payment_service import pay_credit_card
        payment_resp = pay_credit_card(credit, amount)

        cc = payment_resp["credit_card"]
        tr = payment_resp["transaction"]

        Order.update(
            paid=True,
            credit_card_first=cc["first_digits"],
            credit_card_last=cc["last_digits"],
            credit_card_name=cc["name"],
            credit_exp_month=cc["expiration_month"],
            credit_exp_year=cc["expiration_year"],
            transaction_id=tr["id"],
            transaction_success=tr["success"],
            transaction_amount=tr["amount_charged"]
        ).where(Order.id == order.id).execute()

        order.refresh()
        return jsonify({"order": serialize_order(order)})

    # 3) Ni l’un ni l’autre
    error("missing-fields", "Aucune donnée exploitable envoyée.")

# ---------- Helpers ----------
def serialize_order(order):
    """Retourne un dict strictement conforme à l’énoncé."""
    order_dict = {
        "id": order.id,
        "total_price": order.total_price,
        "total_price_tax": order.total_price_tax,
        "email": order.email,
        "shipping_information": {
            "country": order.country,
            "address": order.address,
            "postal_code": order.postal_code,
            "city": order.city,
            "province": order.province,
        } if order.country else {},
        "credit_card": {
            "name": order.credit_card_name,
            "first_digits": order.credit_card_first,
            "last_digits": order.credit_card_last,
            "expiration_year": order.credit_exp_year,
            "expiration_month": order.credit_exp_month,
        } if order.credit_card_first else {},
        "paid": order.paid,
        "transaction": {
            "id": order.transaction_id,
            "success": order.transaction_success,
            "amount_charged": order.transaction_amount,
        } if order.transaction_id else {},
        "product": {
            "id": order.lines[0].product.id,
            "quantity": order.lines[0].quantity,
        },
        "shipping_price": order.shipping_price,
    }
    return order_dict
