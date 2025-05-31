"""
inf349/payment_service.py
-------------------------

Couche d’accès au service de paiement distant fourni par l’énoncé.

• Tous les montants sont envoyés en CENTIMES (int) comme demandé par l’API.
• Lève PaymentError si la transaction échoue ou si le service est inaccessible.
"""

from __future__ import annotations

import requests
from typing import Any, Dict

# URL du service de paiement (donnée dans l'énoncé)
PAY_ENDPOINT = "https://dimensweb.uqac.ca/~jgnault/shops/pay/"

# --------------------------------------------------------------------------- #
#  Exceptions
# --------------------------------------------------------------------------- #
class PaymentError(Exception):
    """Erreur levée si l’API distante refuse la carte ou répond 4xx/5xx.

    L’exception transporte toujours un dict JSON « propre » (le même format que
    renvoyé par l’API), accessible dans `err.args[0]`.
    """

# --------------------------------------------------------------------------- #
#  Fonction publique : pay_credit_card
# --------------------------------------------------------------------------- #
def pay_credit_card(card: Dict[str, Any], amount_cents: int) -> Dict[str, Any]:
    """
    Envoie `card` + `amount_cents` (int) au service distant, retourne la réponse
    JSON décodée.

    Parameters
    ----------
    card : dict
        {
          "name": "John Doe",
          "number": "4242 4242 4242 4242",
          "expiration_year": 2024,
          "expiration_month": 9,
          "cvv": "123"
        }
    amount_cents : int
        Montant total à débiter (produit + taxes + shipping) exprimé en centimes.

    Returns
    -------
    dict
        {
          "credit_card": {...},
          "transaction": {...}
        }

    Raises
    ------
    PaymentError
        • Si le service renvoie un statut != 200.
        • Si la connexion échoue / time-out.
        • `err.args[0]` contiendra toujours un JSON de la forme :
          {"errors": {...}} ou {"errors": {"network": "..."}}
    """
    payload = {
        "credit_card": card,
        "amount_charged": amount_cents,
    }

    try:
        resp = requests.post(PAY_ENDPOINT, json=payload, timeout=10)
    except requests.RequestException as exc:
        raise PaymentError(
            {"errors": {"network": str(exc)}}
        ) from exc

    if resp.status_code == 200:
        # Succès : on renvoie le JSON (lève si JSON mal-formé)
        return resp.json()

    # Le service renvoie 422 pour carte refusée ou données invalides
    try:
        error_json = resp.json()
    except ValueError:
        error_json = {
            "errors": {
                "payment": {
                    "code": "invalid-response",
                    "name": "Réponse inattendue du service de paiement",
                }
            }
        }
    raise PaymentError(error_json)
