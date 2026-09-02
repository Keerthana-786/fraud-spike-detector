# 🛡️ SentinelPay — AI Risk Manager
> **AI-Powered Payment Risk Intelligence & Real-Time Fraud Operations Platform**
> *Built for Razorpay AI Buildathon 2026 — Track 02: AI Risk Manager*

[![CI / Test Suite](https://img.shields.io/badge/Tests-20%2F20%20Passing-emerald)](https://github.com/Keerthana-786/fraud-spike-detector)
[![E2E Verification](https://img.shields.io/badge/Verification-25%2F25%20Verified-cyan)](https://github.com/Keerthana-786/fraud-spike-detector)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg)](https://react.dev/)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

---

## 1. Problem Statement

Traditional payment fraud systems evaluate transactions in isolation. This works against individual card testing but misses **coordinated fraud** — distributed credential stuffing, rings targeting specific POS terminals, or rapid cash-out campaigns — where volume alone never crosses an alarming threshold.

Two failure modes follow from volume-only detection:
- **False alarms during legitimate surges** (festival sales, flash sales) — volume-threshold systems fire on traffic they shouldn't.
- **Missed attacks that hide inside normal traffic** — a fraud ring can keep transaction *count* flat while the *proportion* of high-risk transactions surges, and a volume-only detector never sees it.

## 2. The SentinelPay Solution

SentinelPay is a **defense-only AI Risk Manager**. It monitors **fraud-risk density** — the ratio of high-risk to total transactions in a rolling statistical baseline — rather than raw volume. When density surges beyond an adaptive Z-score threshold, it opens an incident, assembles an evidence bundle, generates an AI investigation summary, **deterministically re-verifies every AI claim against the database**, and routes the decision to a human analyst. It never executes refunds, holds, or account actions on its own.

## 3. Key Differentiator: Density vs. Volume

$$D = \frac{\sum_{i=1}^{N} P(\text{fraud}_i)}{N}$$

| Scenario | Volume | Risk Density ($D$) | Response |
|---|:---:|:---:|---|
| Normal operations | Steady | Baseline (~0.8%) | ✅ No alert |
| Flash sale / surge | 10× | Baseline (~0.8%) | ✅ Legitimate — no alert |
| Coordinated fraud ring | Steady | Spikes to 18%+ | 🚨 Incident opened, $Z \ge 3.0\sigma$ |

## 4. Architecture

All ingestion sources — Razorpay Test Mode webhooks, the controlled simulator, and the REST API — flow through a single canonical pipeline:

```
Transaction Sources (Razorpay Webhook | Simulator | REST API)
        ↓
process_transaction() → schema validation & idempotency
        ↓
SQLite persistence
        ↓
Calibrated XGBoost transaction scoring
        ↓
Rolling risk-density calculation
        ↓
Adaptive Z-score spike detection
        ↓
Segment driver discovery (device / network / category)
        ↓
Persisted evidence bundle
        ↓
AI investigation (Gemini) → deterministic DB claim verification
        ↓
Safety policy engine (defense-only)
        ↓
Human analyst decision + audit note
        ↓
Financial impact calculation → notification & audit trail
```

## 5. Machine Learning Model

- **Algorithm**: Calibrated XGBoost classifier (`live_fraud_model.joblib`)
- **Data**: PaySim benchmark + normalized payment attributes (amount, type, hour, velocity, network, device, merchant category)
- **Split**: Strict chronological 80% train / held-out test — the held-out set was never used for tuning or threshold selection

### Transaction-Level Classifier — Held-Out Test Set

| Metric | Held-Out Value |
|---|:---:|
| Precision | 0.821 |
| Recall | 0.865 |
| F1 | 0.842 |
| ROC-AUC | 0.948 |
| FPR | 0.022 |

This is the *per-transaction* fraud classifier. It is a separate model from the density-spike detector below and is not directly comparable to spike-level recall.

## 6. Spike Detection — Held-Out Benchmark vs. Naive Baseline

This is the core evaluated claim of the submission: an 80/20 chronological split, evaluated on **6,841 held-out hourly buckets containing 19 ground-truth density spikes**, comparing SentinelPay's Z-score density detector against a naive volume-threshold baseline (flag if bucket transaction count ≥ 90th percentile) on the *identical* test set.

| Metric | SentinelPay (Z-score density) | Naive volume baseline | Advantage |
|---|:---:|:---:|---|
| Precision | 28.6% | 0.0% | +28.6% |
| Recall | 10.5% | 0.0% | +10.5% |
| F1 | 0.1538 | 0.0000 | +15.4% |
| False positives | 5 | 472 | −98.9% |
| False negatives | 17 | 19 | 2 fewer missed |
| FP review cost (₹50/alert) | ₹250 | ₹23,600 | ₹23,350 saved |
| Total operational cost | ₹85,250 | ₹1,18,600 | **₹33,350 saved** |

**Read plainly**: the naive baseline catches zero spikes because these attacks hold volume flat while risk concentration surges — a volume threshold is structurally blind to them by design. SentinelPay catches 2 of 19 (10.5% recall) at a fraction of the false-positive cost. Recall at this threshold is intentionally conservative to keep false positives low; we show the trade-off explicitly rather than tuning the threshold to look better on a 19-event sample. **Caveat**: n=19 ground-truth spikes is a small sample — a swing of 1–2 events changes recall by more than 5 percentage points.

A separate 4-event synthetic sanity check (used during development, not the held-out benchmark) caught 4/4 injected spikes — reported here for transparency, not as the evaluated result. The held-out benchmark above is the number we stand behind.

## 7. Evidence Bundles & Segment Discovery

Each incident carries an immutable JSON evidence bundle: `baseline_density`, `current_density`, `anomaly_score` (Z-score), transaction counts, potential exposure, and segment driver contributions (card network, device type, merchant category) isolating which concentration shift is driving the spike.

## 8. AI Investigation & Deterministic Verification

The LLM (Gemini) converts the evidence bundle into a human-readable investigation brief. Every factual claim it makes is then re-checked against SQLite ground truth before an analyst ever sees it:

```
AI claim: "₹X exposure across N transactions"
        ↓
Deterministic DB verifier: does count == N? does amount == X?
        ↓
MATCH → shown as VERIFIED   |   MISMATCH → REJECTED, not shown
```

## 9. Safety Policy — Defense-Only

- No autonomous refunds, account freezes, or fund transfers — ever.
- Every incident closure requires a human analyst decision (`CONFIRM_FRAUD` / `MARK_FALSE_POSITIVE` / `ESCALATE`) with a mandatory rationale note.
- Append-only, tamper-evident audit log for every login, setting change, and webhook event.

## 10. Razorpay Test Mode Integration

- HMAC-SHA256 signature verification over the raw request body.
- Idempotent on `x-razorpay-event-id` and transaction ID — replay-safe.
- If credentials are unset, the UI shows `NOT CONFIGURED` explicitly rather than simulating success.

## 11. Known Limitations

1. **Cold start**: needs ≥3 aggregation buckets before adaptive Z-scores stabilize; falls back to a step-trigger threshold during warm-up to avoid division-by-zero.
2. **Small held-out sample**: 19 ground-truth spikes is enough to demonstrate the density-vs-volume advantage, not enough to claim a tight confidence interval on recall.
3. **External credentials**: SMTP and live Razorpay webhooks require `.env` keys; degrades gracefully to `NOT CONFIGURED` when absent.
4. **Local store**: SQLite in WAL mode, single-node. Production would need PostgreSQL.

## 12. Environment Variables

```bash
PORT=8000
JWT_SECRET=your-secret-key

# Optional — enables live LLM investigation summaries
GEMINI_API_KEY=

# Optional — Razorpay Test Mode
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_key_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret

# Optional — SMTP notifications
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
```

## 13. Quickstart

```bash
git clone https://github.com/Keerthana-786/fraud-spike-detector.git
cd fraud-spike-detector

# Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend (separate terminal)
cd web
npm install
npm run dev

# Tests
.venv/bin/pytest -v
.venv/bin/python scratch/verify_all_sections.py
```

- Dashboard: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

## 14. Test Coverage

- Unit/integration: `pytest -v` → 20/20 passing
- E2E pipeline & security pass: `scratch/verify_all_sections.py` → 25/25 passing
- Frontend build: `tsc -b && vite build` → 0 errors

---
*Built for Razorpay AI Buildathon 2026 — Track 02: AI Risk Manager.*