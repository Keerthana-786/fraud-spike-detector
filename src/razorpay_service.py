"""Small, lazy Razorpay SDK boundary for Test Mode orders and verification."""
from __future__ import annotations

import os
from typing import Any, Dict

MAX_ORDER_AMOUNT_RUPEES = 1_000_000.0


def _client():
    try:
        import razorpay
    except ImportError as exc:
        raise RuntimeError("Razorpay SDK is not installed. Run pip install -r requirements.txt") from exc
    key_id = os.getenv("RAZORPAY_KEY_ID", "")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay Test Mode credentials are not configured")
    if not key_id.startswith("rzp_test_"):
        raise RuntimeError("Only Razorpay Test Mode keys are accepted")
    return razorpay.Client(auth=(key_id, key_secret))


def create_test_order(amount_rupees: float, currency: str = "INR", receipt: str | None = None) -> Dict[str, Any]:
    """Create a server-side Test Mode order; amount is converted to paise."""
    if currency != "INR":
        raise ValueError("Only INR orders are supported")
    amount = float(amount_rupees)
    if amount <= 0 or amount > MAX_ORDER_AMOUNT_RUPEES:
        raise ValueError(f"amount_rupees must be between 0 and {MAX_ORDER_AMOUNT_RUPEES:g}")
    options = {"amount": int(round(amount * 100)), "currency": currency, "payment_capture": 1}
    if receipt:
        options["receipt"] = receipt[:40]
    order = _client().order.create(data=options)
    return {"id": order["id"], "amount": order["amount"], "currency": order["currency"], "status": order.get("status", "created")}


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    if not order_id or not payment_id or not signature:
        return False
    try:
        _client().utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
    except Exception:
        return False
    return True
