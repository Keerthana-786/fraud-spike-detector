"""Abuse-Ring & Coordinated Attack Detector using Graph Connected Components.

Uses NetworkX to identify suspicious transaction clusters sharing payment vectors,
tight time windows, and clustered amounts across merchant checkout rails.
Integrates directly into the existing incident management, audit log, and notification pipeline.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Optional
import uuid

import networkx as nx
import pandas as pd

from src.live_store import LiveStore
from src.notifications import send_alert_email


def detect_abuse_rings(
    transactions: list[dict[str, Any]],
    time_window_minutes: int = 30,
    amount_tolerance_pct: float = 0.15,
    min_ring_size: int = 4,
) -> list[dict[str, Any]]:
    """Group transactions using graph connected components to detect coordinated fraud rings."""
    if len(transactions) < min_ring_size:
        return []

    # Build Graph
    G = nx.Graph()
    for tx in transactions:
        tx_id = tx["transaction_id"]
        ts = pd.to_datetime(tx["timestamp"], utc=True).to_pydatetime()
        amt = float(tx["amount"])
        method = str(tx.get("payment_method", "card")).lower()
        G.add_node(tx_id, timestamp=ts, amount=amt, method=method, tx_dict=tx)

    nodes = list(G.nodes(data=True))
    for i in range(len(nodes)):
        id_a, data_a = nodes[i]
        ts_a = data_a["timestamp"]
        amt_a = data_a["amount"]
        meth_a = data_a["method"]

        for j in range(i + 1, len(nodes)):
            id_b, data_b = nodes[j]
            ts_b = data_b["timestamp"]
            amt_b = data_b["amount"]
            meth_b = data_b["method"]

            # Edge condition 1: Same payment method
            if meth_a != meth_b:
                continue

            # Edge condition 2: Tight time window
            dt_seconds = abs((ts_a - ts_b).total_seconds())
            if dt_seconds > (time_window_minutes * 60):
                continue

            # Edge condition 3: Clustered similar transaction amounts
            max_amt = max(amt_a, amt_b, 0.01)
            amt_diff_pct = abs(amt_a - amt_b) / max_amt
            if amt_diff_pct <= amount_tolerance_pct:
                G.add_edge(id_a, id_b, dt_seconds=dt_seconds, amt_diff_pct=amt_diff_pct)

    rings = []
    for component in nx.connected_components(G):
        if len(component) >= min_ring_size:
            member_nodes = [G.nodes[tx_id] for tx_id in component]
            tx_dicts = [n["tx_dict"] for n in member_nodes]
            amounts = [n["amount"] for n in member_nodes]
            timestamps = [n["timestamp"] for n in member_nodes]
            method = member_nodes[0]["method"]

            min_ts = min(timestamps).isoformat()
            max_ts = max(timestamps).isoformat()
            total_exposure = sum(amounts)
            avg_amt = total_exposure / len(amounts)

            ring_record = {
                "ring_size": len(component),
                "payment_method": method,
                "window_start": min_ts,
                "window_end": max_ts,
                "total_exposure": round(total_exposure, 2),
                "average_amount": round(avg_amt, 2),
                "transaction_ids": list(component),
                "transactions": tx_dicts,
            }
            rings.append(ring_record)

    return rings


def run_abuse_ring_pipeline(
    store: Optional[LiveStore] = None,
    lookback_hours: int = 4,
    min_ring_size: int = 4,
) -> list[dict[str, Any]]:
    """Scan recent live transactions for abuse rings and emit first-class RING incidents."""
    store = store or LiveStore()
    recent = store.recent_transactions(limit=500)
    if not recent:
        return []

    rings = detect_abuse_rings(recent, time_window_minutes=35, amount_tolerance_pct=0.15, min_ring_size=min_ring_size)
    created_incidents = []

    for ring in rings:
        window_start = ring["window_start"][:19]
        source = ring["transactions"][0].get("source", "LIVE")

        # Check if an active ring alert already covers these transactions
        existing = store.alert_exists(window_start, source)
        if existing and existing.get("incident_type") == "RING":
            continue

        alert_id = f"RING-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()

        timeline = [{
            "timestamp": now_iso,
            "event": "GRAPH_RING_DETECTED",
            "severity": "CRITICAL" if ring["ring_size"] >= 6 else "HIGH",
            "rate": 1.0,
            "exposure": ring["total_exposure"],
            "z_score": float(ring["ring_size"]),
        }]

        root_cause = [
            {
                "feature": f"Coordinated {ring['payment_method'].upper()} velocity cluster",
                "contribution": 0.85,
                "direction": "elevates risk",
            },
            {
                "feature": f"{ring['ring_size']} transactions sharing similar amounts (~₹{ring['average_amount']:,.0f})",
                "contribution": 0.72,
                "direction": "elevates risk",
            },
        ]

        slice_attr = {
            "top_slice": {
                "dimension": "payment_method",
                "value": ring["payment_method"],
                "multiplier": float(ring["ring_size"]),
            }
        }

        alert_dict = {
            "alert_id": alert_id,
            "detected_at": now_iso,
            "window_start": window_start,
            "window_end": ring["window_end"][:19],
            "source": source,
            "baseline_rate": 0.01,
            "current_rate": 0.95,
            "multiplier": float(ring["ring_size"]),
            "anomaly_score": float(ring["ring_size"]) * 1.5,
            "severity": "CRITICAL" if ring["ring_size"] >= 6 else "HIGH",
            "status": "INVESTIGATING",
            "affected_transactions": ring["ring_size"],
            "potential_exposure": ring["total_exposure"],
            "root_cause_json": json.dumps(root_cause),
            "slice_attribution_json": json.dumps(slice_attr),
            "timeline_json": json.dumps(timeline),
        }

        store.create_alert(alert_dict)
        store.record_audit(
            alert_id=alert_id,
            action="ABUSE_RING_DETECTED",
            actor="Graph Analysis Engine",
            details=json.dumps({
                "ring_size": ring["ring_size"],
                "payment_method": ring["payment_method"],
                "total_exposure": ring["total_exposure"],
                "sample_txns": ring["transaction_ids"][:5],
            }),
        )

        # Trigger notification dispatch
        recipients = store.list_recipients(enabled_only=True)
        if recipients:
            results = send_alert_email(alert_dict, recipients)
            for res in results:
                store.record_notification(alert_id, res)

        created_incidents.append(alert_dict)

    return created_incidents
