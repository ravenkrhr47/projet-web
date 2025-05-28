import requests, json
from .models import Product, db
from config import config

def fetch_and_cache_products():
    """Télécharge les produits distants une seule fois au démarrage."""
    r = requests.get(config.REMOTE_PRODUCTS_URL, timeout=10)
    r.raise_for_status()
    products_json = r.json()["products"]

    with db.atomic():
        for p in products_json:
            Product.insert(**p).on_conflict_replace().execute()
