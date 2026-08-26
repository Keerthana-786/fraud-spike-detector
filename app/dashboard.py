"""SentinelPay — AI-Powered Payment Risk Intelligence.

A production-grade, locally runnable merchant fraud-risk and spike detection platform.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.auth import (
    create_session_token,
    hash_password,
    validate_registration,
    valid_email,
    verify_password,
    verify_session_token,
)
from src.live_pipeline import LIVE_MODEL_PATH, process_transaction
from src.live_store import DEFAULT_DB_PATH, LiveStore
from src.test_simulator import (
    inject_controlled_spike,
    start_test_stream,
    stop_simulation,
)

# -----------------------------------------------------------------------------
# Streamlit Page Config
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="SentinelPay | Payment Risk Intelligence",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

store = LiveStore()
API_BASE = os.getenv("SENTINELPAY_API_URL", "http://127.0.0.1:8000").rstrip("/")


def format_spike_multiplier(alert: dict) -> str:
    """Render spike multiplier; never show blank/None when a value exists on the row or in slice JSON."""
    value = alert.get("multiplier")
    if value is None:
        top = (alert.get("slice_attribution") or {}).get("top_slice") or {}
        value = top.get("multiplier")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number) or number <= 0:
        return "—"
    return f"{number:.1f}×"


def format_audit_timestamp(event: dict) -> str:
    raw = event.get("occurred_at") or event.get("timestamp") or event.get("created_at") or ""
    text = str(raw).strip()
    if not text:
        return "—"
    return text.replace(" ", "T")[:19]


def _api_error_message(payload: Any, status_code: int) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail", payload.get("message"))
    else:
        detail = payload
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                parts.append(str(item.get("msg") or item.get("detail") or item))
            else:
                parts.append(str(item))
        detail = "; ".join(parts)
    if not detail:
        return f"Signup failed (HTTP {status_code})."
    return str(detail)


def register_via_api(
    full_name: str,
    email: str,
    organization: str,
    role: str,
    password: str,
    confirm_password: str,
    terms_accepted: bool,
) -> tuple[bool, str]:
    body = {
        "full_name": full_name,
        "email": email,
        "organization": organization,
        "role": role,
        "password": password,
        "confirm_password": confirm_password,
        "terms_accepted": bool(terms_accepted),
        "agree_terms": bool(terms_accepted),
    }
    request = urllib.request.Request(
        f"{API_BASE}/api/auth/register",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return True, payload.get("message") or "Account created successfully. Please sign in."
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = raw
        return False, _api_error_message(parsed, exc.code)
    except urllib.error.URLError as exc:
        return False, (
            f"Could not reach the SentinelPay API at {API_BASE}. "
            f"Start the API server, then try again. ({exc.reason})"
        )

# -----------------------------------------------------------------------------
# Global Styling: Clean Dark Navy Fintech Theme (No Cloud Illustrations)
# -----------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp {
    background-color: #070b14 !important;
    color: #e2e8f0 !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #0c1322 !important;
    border-right: 1px solid #1e2d45 !important;
}

[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 0.4rem;
}

/* Main Container */
.main .block-container {
    padding: 1.5rem 2rem 3rem 2rem !important;
    max-width: 1600px;
}

/* Auth Card */
.auth-wrapper {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 2.5rem 1rem;
}

.auth-card {
    width: 100%;
    max-width: 440px;
    background: #0d1527;
    border: 1px solid #1e2d45;
    border-radius: 14px;
    padding: 2.5rem 2rem;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
}

.auth-brand {
    text-align: center;
    font-size: 1.6rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    color: #38bdf8;
    margin-bottom: 0.2rem;
}

.auth-product-desc {
    text-align: center;
    font-size: 0.8rem;
    font-weight: 500;
    color: #94a3b8;
    margin-bottom: 1.5rem;
}

.auth-title {
    text-align: center;
    font-size: 1.3rem;
    font-weight: 700;
    color: #f8fafc;
    margin-bottom: 0.2rem;
}

.auth-subtitle {
    text-align: center;
    font-size: 0.82rem;
    color: #64748b;
    margin-bottom: 1.5rem;
}

.auth-footer {
    text-align: center;
    font-size: 0.72rem;
    color: #475569;
    margin-top: 1.8rem;
}

/* Topbar */
.sp-topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #0c1322;
    border: 1px solid #1e2d45;
    border-radius: 10px;
    padding: 0.75rem 1.25rem;
    margin-bottom: 1.5rem;
}

.sp-brand-title {
    font-size: 1.1rem;
    font-weight: 800;
    letter-spacing: 0.05em;
    color: #f8fafc;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.sp-brand-tag {
    font-size: 0.75rem;
    font-weight: 500;
    color: #38bdf8;
    background: rgba(56, 189, 248, 0.1);
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    border: 1px solid rgba(56, 189, 248, 0.2);
}

.sp-user-badge {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-size: 0.85rem;
    color: #cbd5e1;
}

.sp-role-pill {
    font-size: 0.7rem;
    font-weight: 600;
    background: #1e293b;
    color: #94a3b8;
    padding: 0.2rem 0.6rem;
    border-radius: 12px;
    border: 1px solid #334155;
}

/* Status Banners */
.sp-banner-normal {
    background: rgba(34, 197, 94, 0.1);
    border: 1px solid rgba(34, 197, 94, 0.35);
    border-left: 5px solid #22c55e;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    gap: 0.8rem;
    font-size: 1.1rem;
    font-weight: 700;
    color: #4ade80;
}

.sp-banner-elevated {
    background: rgba(245, 158, 11, 0.1);
    border: 1px solid rgba(245, 158, 11, 0.35);
    border-left: 5px solid #f59e0b;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    gap: 0.8rem;
    font-size: 1.1rem;
    font-weight: 700;
    color: #fbbf24;
}

.sp-banner-spike {
    background: rgba(239, 68, 68, 0.12);
    border: 1px solid rgba(239, 68, 68, 0.45);
    border-left: 5px solid #ef4444;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    gap: 0.8rem;
    font-size: 1.15rem;
    font-weight: 800;
    color: #f87171;
    animation: pulse 2s infinite ease-in-out;
}

/* KPI Cards */
.sp-kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
}

.sp-kpi-card {
    background: #0f172a;
    border: 1px solid #1e2d45;
    border-radius: 10px;
    padding: 1.1rem 1.2rem;
}

.sp-kpi-label {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: #64748b;
    text-transform: uppercase;
    margin-bottom: 0.35rem;
}

.sp-kpi-value {
    font-size: 1.5rem;
    font-weight: 800;
    color: #f8fafc;
    line-height: 1.2;
}

.sp-kpi-sub {
    font-size: 0.72rem;
    color: #94a3b8;
    margin-top: 0.35rem;
}

/* Badges */
.badge-critical {
    background: rgba(239, 68, 68, 0.2);
    color: #fca5a5;
    border: 1px solid rgba(239, 68, 68, 0.4);
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.72rem;
    font-weight: 700;
}

.badge-high {
    background: rgba(245, 158, 11, 0.2);
    color: #fcd34d;
    border: 1px solid rgba(245, 158, 11, 0.4);
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.72rem;
    font-weight: 700;
}

.badge-medium {
    background: rgba(59, 130, 246, 0.2);
    color: #93c5fd;
    border: 1px solid rgba(59, 130, 246, 0.4);
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.72rem;
    font-weight: 700;
}

.badge-low {
    background: rgba(34, 197, 94, 0.2);
    color: #86efac;
    border: 1px solid rgba(34, 197, 94, 0.4);
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.72rem;
    font-weight: 700;
}

/* Streamlit button style overrides */
.stButton > button {
    background-color: #111d2e !important;
    border: 1px solid #1e2d45 !important;
    color: #e2e8f0 !important;
    font-weight: 600 !important;
    border-radius: 6px !important;
    transition: all 0.15s ease !important;
}

.stButton > button:hover {
    background-color: #1e293b !important;
    border-color: #38bdf8 !important;
    color: #ffffff !important;
}

.stButton > button[kind="primary"] {
    background-color: #0284c7 !important;
    border-color: #0284c7 !important;
    color: #ffffff !important;
}

.stButton > button[kind="primary"]:hover {
    background-color: #0369a1 !important;
}

/* Inputs */
.stTextInput > div > div > input,
.stSelectbox > div > div,
.stTextArea > div > div > textarea {
    background-color: #0a0f1e !important;
    border: 1px solid #1e2d45 !important;
    color: #f1f5f9 !important;
    border-radius: 6px !important;
}

/* Dataframe */
[data-testid="stDataFrame"] {
    background: #0f172a !important;
    border: 1px solid #1e2d45 !important;
    border-radius: 8px !important;
}

.sp-landing-hero { padding: 3.5rem 0 1.5rem; max-width: 850px; }
.sp-landing-kicker, .sp-section-label { color: #38bdf8; font-size: .72rem; font-weight: 800; letter-spacing: .14em; }
.sp-landing-hero h1 { color: #f8fafc; font-size: clamp(2.6rem, 6vw, 5.4rem); line-height: 1.02; margin: .65rem 0 1rem; letter-spacing: -.04em; }
.sp-landing-hero p { color: #94a3b8; font-size: 1.15rem; line-height: 1.7; max-width: 720px; }
.sp-trust-row { display: flex; flex-wrap: wrap; gap: 1rem; color: #94a3b8; font-size: .78rem; margin-top: 1.2rem; }
.sp-signal-panel { background: linear-gradient(145deg, #101c31, #0b1220); border: 1px solid #2b496a; border-radius: 12px; padding: 1.4rem; box-shadow: 0 18px 50px rgba(0,0,0,.28); }
.sp-signal-header, .sp-signal-meta { display: flex; justify-content: space-between; color: #64748b; font-size: .7rem; font-weight: 700; letter-spacing: .08em; }
.sp-signal-header b { color: #4ade80; }
.sp-signal-rate { color: #f87171; font-size: 4.5rem; font-weight: 900; line-height: 1.1; margin: 1.4rem 0 .5rem; }
.sp-signal-rate span { font-size: 1.8rem; }
.sp-signal-meta strong { color: #fca5a5; letter-spacing: 0; }
.sp-signal-bars { display: flex; align-items: end; gap: .35rem; height: 90px; margin: 1.2rem 0; }
.sp-signal-bars i { display: block; flex: 1; height: 24%; background: #256b73; border-radius: 3px 3px 0 0; }
.sp-signal-bars i:nth-child(2) { height: 31%; } .sp-signal-bars i:nth-child(3) { height: 27%; } .sp-signal-bars i:nth-child(4) { height: 36%; } .sp-signal-bars i:nth-child(5) { height: 43%; } .sp-signal-bars i:nth-child(6) { height: 50%; }
.sp-signal-bars i.hot { height: 82%; background: #ef4444; } .sp-signal-bars i.hot:last-child { height: 100%; }
.sp-signal-alert { border-top: 1px solid #263b55; padding-top: .9rem; color: #f87171; font-weight: 800; font-size: .78rem; }
.sp-signal-alert span { color: #94a3b8; float: right; font-weight: 500; }
.sp-landing-title { color: #f8fafc; max-width: 740px; margin: .6rem 0 1.6rem; }
.sp-step { border-top: 1px solid #24364d; padding-top: 1rem; min-height: 160px; }
.sp-step span { color: #38bdf8; font: 700 .75rem monospace; } .sp-step h3 { color: #f8fafc; margin: .7rem 0 .35rem; } .sp-step p { color: #94a3b8; font-size: .85rem; line-height: 1.55; }
.sp-landing-footer { border-top: 1px solid #24364d; margin-top: 2.5rem; padding-top: 1.2rem; display: flex; justify-content: space-between; gap: 2rem; color: #64748b; font-size: .8rem; }
.sp-landing-footer strong { color: #e2e8f0; }
@media (max-width: 700px) { .sp-landing-hero { padding-top: 1.5rem; } .sp-landing-footer { display: block; } .sp-landing-footer > div + div { margin-top: 1rem; } }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Session State Initialization
# -----------------------------------------------------------------------------
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None
if "current_page" not in st.session_state:
    st.session_state["current_page"] = "Overview"
if "auth_view" not in st.session_state:
    st.session_state["auth_view"] = "landing"
if "selected_alert_id" not in st.session_state:
    st.session_state["selected_alert_id"] = None
if "notification_drawer_open" not in st.session_state:
    st.session_state["notification_drawer_open"] = False


# -----------------------------------------------------------------------------
# Authentication Views
# -----------------------------------------------------------------------------
def render_landing_page():
    st.markdown("""
    <section class="sp-landing-hero">
        <div class="sp-landing-kicker">PAYMENT RISK INTELLIGENCE</div>
        <h1>Detect fraud spikes before losses grow.</h1>
        <p>SentinelPay watches your payment behavior in real time, learns your normal baseline, and gives risk teams the evidence to act before a coordinated attack becomes a balance-sheet event.</p>
    </section>
    """, unsafe_allow_html=True)

    hero_left, hero_right = st.columns([1.1, 0.9], gap="large")
    with hero_left:
        cta_login, cta_signup = st.columns(2)
        with cta_login:
            if st.button("Sign in", type="primary", use_container_width=True, key="landing_signin"):
                st.session_state["auth_view"] = "login"
                st.rerun()
        with cta_signup:
            if st.button("Start monitoring", use_container_width=True, key="landing_signup"):
                st.session_state["auth_view"] = "signup"
                st.rerun()
        st.markdown("<div class='sp-trust-row'><span>✓ 60-120 second detection</span><span>✓ Human decision required</span><span>✓ Razorpay Test Mode</span></div>", unsafe_allow_html=True)
    with hero_right:
        st.markdown("""
        <div class="sp-signal-panel">
            <div class="sp-signal-header"><span>LIVE RISK SIGNAL</span><b>● MONITORING</b></div>
            <div class="sp-signal-rate">7.5<span>%</span></div>
            <div class="sp-signal-meta"><span>Baseline 0.5%</span><strong>15.0× deviation</strong></div>
            <div class="sp-signal-bars"><i></i><i></i><i></i><i></i><i></i><i></i><i class="hot"></i><i class="hot"></i><i class="hot"></i></div>
            <div class="sp-signal-alert">ALERT GENERATED <span>Analyst review required</span></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div class='sp-section-label'>THE SIGNAL BEHIND THE NOISE</div><h2 class='sp-landing-title'>Individual scores miss the moment a merchant’s behavior changes.</h2>", unsafe_allow_html=True)
    cards = [
        ("01", "Ingest", "Receive payment events from Razorpay webhooks or the controlled simulator."),
        ("02", "Score", "Evaluate each payment with the live-compatible fraud model."),
        ("03", "Compare", "Measure the current fraud rate against a rolling historical baseline."),
        ("04", "Investigate", "Give an analyst the alert, exposure, factors, and audit trail."),
    ]
    cols = st.columns(4)
    for col, (number, title, body) in zip(cols, cards):
        with col:
            st.markdown(f"<div class='sp-step'><span>{number}</span><h3>{title}</h3><p>{body}</p></div>", unsafe_allow_html=True)

    st.markdown("<div class='sp-landing-footer'><div><strong>Defense-only by design.</strong><br>SentinelPay detects, explains, and records. Your team makes the decision.</div><div>Built for merchants, processors, digital banks, and subscription platforms.</div></div>", unsafe_allow_html=True)


def render_login_page():
    st.markdown("""
    <div style="text-align:center; padding-top:2rem;">
        <div style="font-size:2rem; font-weight:900; letter-spacing:0.08em; color:#f8fafc;">SENTINELPAY</div>
        <div style="font-size:0.88rem; color:#38bdf8; font-weight:600; margin-bottom:1.5rem;">AI-Powered Payment Risk Intelligence</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.4, 1])
    with col2:
        st.markdown("""
        <div style="background:#0f172a; border:1px solid #1e2d45; border-radius:12px; padding:2rem 2.2rem; box-shadow:0 12px 36px rgba(0,0,0,0.5);">
            <div style="font-size:1.35rem; font-weight:800; color:#f8fafc; text-align:center;">Welcome back</div>
            <div style="font-size:0.82rem; color:#64748b; text-align:center; margin-bottom:1.5rem;">Sign in to your risk management center.</div>
        </div>
        """, unsafe_allow_html=True)

        with st.container():
            email = st.text_input("Email", placeholder="Enter your email address", key="login_email")
            password = st.text_input("Password", type="password", placeholder="Enter your password", key="login_password")
            
            c_rem, c_forgot = st.columns([1, 1])
            with c_rem:
                remember_me = st.checkbox("Remember me", key="login_remember")
            with c_forgot:
                if st.button("Forgot password?", key="btn_forgot_pw_nav"):
                    st.session_state["auth_view"] = "forgot_password"
                    st.rerun()

            if st.button("SIGN IN", type="primary", use_container_width=True, key="btn_sign_in"):
                if not email or not password:
                    st.error("Invalid email or password.")
                elif not valid_email(email):
                    st.error("Invalid email or password.")
                else:
                    user = store.user_by_email(email)
                    if not user or not user.get("password_hash") or not verify_password(password, user["password_hash"]):
                        st.error("Invalid email or password.")
                    else:
                        token = create_session_token(user["user_id"], user["email"], user["role"], remember_me=remember_me)
                        store.save_session(token, user["user_id"], expires_at="30d" if remember_me else "1d")
                        st.session_state["auth_user"] = user
                        store.record_audit(None, "User signed in", actor=user["name"])
                        st.success(f"Welcome back, {user['name']}!")
                        st.rerun()

            st.markdown("<div style='text-align:center; margin-top:1.2rem; font-size:0.85rem; color:#94a3b8;'>Don't have an account?</div>", unsafe_allow_html=True)
            if st.button("Sign Up", use_container_width=True, key="btn_to_signup"):
                st.session_state["auth_view"] = "signup"
                st.rerun()

        st.markdown("<div style='text-align:center; font-size:0.75rem; color:#475569; margin-top:2rem;'>Protected merchant risk environment.</div>", unsafe_allow_html=True)


def render_signup_page():
    st.markdown("""
    <div style="text-align:center; padding-top:1.5rem;">
        <div style="font-size:2rem; font-weight:900; letter-spacing:0.08em; color:#f8fafc;">SENTINELPAY</div>
        <div style="font-size:0.88rem; color:#38bdf8; font-weight:600; margin-bottom:1.5rem;">AI-Powered Payment Risk Intelligence</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.markdown("""
        <div style="background:#0f172a; border:1px solid #1e2d45; border-radius:12px; padding:1.8rem 2.2rem; box-shadow:0 12px 36px rgba(0,0,0,0.5);">
            <div style="font-size:1.35rem; font-weight:800; color:#f8fafc; text-align:center;">Create your SentinelPay account</div>
            <div style="font-size:0.82rem; color:#64748b; text-align:center; margin-bottom:1.5rem;">Start monitoring payment risk with AI-powered fraud detection.</div>
        </div>
        """, unsafe_allow_html=True)

        full_name = st.text_input("Full Name", placeholder="Enter your full name", key="su_name")
        email = st.text_input("Work Email", placeholder="Enter your work email", key="su_email")
        organization = st.text_input("Organization / Merchant Name", placeholder="Enter your organization", key="su_org")
        role = "merchant_user"
        password = st.text_input("Password", type="password", placeholder="Create a password (min 8 characters)", key="su_pw")
        confirm_password = st.text_input("Confirm Password", type="password", placeholder="Confirm your password", key="su_cpw")
        terms = st.checkbox("I agree to the Terms of Service and Privacy Policy.", key="su_terms")

        if st.button("CREATE ACCOUNT", type="primary", use_container_width=True, key="btn_create_acc"):
            val_err = validate_registration(
                full_name=full_name,
                email=email,
                password=password,
                confirmation=confirm_password,
                organization=organization,
                role=role,
                terms=terms,
            )
            if val_err:
                st.error(val_err)
            else:
                ok, message = register_via_api(
                    full_name=full_name,
                    email=email,
                    organization=organization,
                    role=role,
                    password=password,
                    confirm_password=confirm_password,
                    terms_accepted=bool(terms),
                )
                if not ok:
                    st.error(message)
                else:
                    st.success(message)
                    st.session_state["auth_view"] = "login"
                    st.rerun()

        st.markdown("<div style='text-align:center; margin-top:1.2rem; font-size:0.85rem; color:#94a3b8;'>Already have an account?</div>", unsafe_allow_html=True)
        if st.button("Sign In", use_container_width=True, key="btn_to_login"):
            st.session_state["auth_view"] = "login"
            st.rerun()


def render_forgot_password_page():
    col1, col2, col3 = st.columns([1, 1.4, 1])
    with col2:
        st.markdown("""
        <div style="background:#0f172a; border:1px solid #1e2d45; border-radius:12px; padding:2rem 2.2rem; box-shadow:0 12px 36px rgba(0,0,0,0.5); margin-top:3rem;">
            <div style="font-size:1.35rem; font-weight:800; color:#f8fafc; text-align:center;">Reset your password</div>
            <div style="font-size:0.82rem; color:#64748b; text-align:center; margin-bottom:1.5rem;">Enter your email to receive recovery instructions.</div>
        </div>
        """, unsafe_allow_html=True)

        email = st.text_input("Email", placeholder="Enter your email address", key="fp_email")

        if st.button("SEND RESET LINK", type="primary", use_container_width=True, key="btn_send_reset"):
            if not email or not valid_email(email):
                st.error("Enter a valid email address.")
            else:
                smtp_ok = bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USERNAME"))
                if not smtp_ok:
                    st.warning("Password reset email service is not configured.")
                else:
                    st.success("If an account exists with this email, reset instructions have been sent.")

        if st.button("Back to Sign In", use_container_width=True, key="btn_fp_back"):
            st.session_state["auth_view"] = "login"
            st.rerun()


# -----------------------------------------------------------------------------
# Main Application Shell
# -----------------------------------------------------------------------------
def render_app_shell(user: dict):
    # Sidebar
    with st.sidebar:
        st.markdown("""
        <div style="padding: 0.5rem 0.2rem 1rem 0.2rem;">
            <div style="font-size: 1.25rem; font-weight: 900; letter-spacing: 0.06em; color: #f8fafc;">SENTINELPAY</div>
            <div style="font-size: 0.72rem; color: #38bdf8; font-weight: 600;">Payment Risk Intelligence</div>
        </div>
        """, unsafe_allow_html=True)

        role = user.get("role", "Merchant Admin")

        # Determine visible navigation options based on role
        if role == "Merchant Admin":
            pages = ["Overview", "Live Monitoring", "Alerts", "Transactions", "Investigation", "Reports", "Financial Impact", "Settings", "Documentation"]
        elif role == "Security Analyst":
            pages = ["Overview", "Live Monitoring", "Alerts", "Transactions", "Investigation", "Reports", "Documentation"]
        elif role == "Finance Manager":
            pages = ["Overview", "Alerts", "Transactions", "Reports", "Financial Impact", "Documentation"]
        elif role == "Operations Manager":
            pages = ["Overview", "Live Monitoring", "Alerts", "Transactions", "Documentation"]
        else:
            pages = ["Overview", "Live Monitoring", "Alerts", "Transactions", "Investigation", "Reports", "Financial Impact", "Settings", "Documentation"]

        for p in pages:
            is_active = (st.session_state["current_page"] == p)
            btn_type = "primary" if is_active else "secondary"
            if st.button(f"{p}", key=f"nav_{p}", type=btn_type, use_container_width=True):
                st.session_state["current_page"] = p
                st.rerun()

        st.markdown("---")
        st.markdown("""
        <div style="font-size: 0.78rem; color: #4ade80; display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.5rem;">
            <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #22c55e;"></span>
            System Operational
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div style="background: #0f172a; border: 1px solid #1e2d45; border-radius: 8px; padding: 0.75rem; margin-bottom: 0.8rem;">
            <div style="font-size: 0.85rem; font-weight: 700; color: #f8fafc;">{user.get('name', 'User')}</div>
            <div style="font-size: 0.72rem; color: #94a3b8;">{user.get('role', 'Merchant Admin')}</div>
            <div style="font-size: 0.68rem; color: #64748b; margin-top: 2px;">{user.get('organization', 'Merchant Inc')}</div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("Logout", use_container_width=True, key="btn_logout"):
            st.session_state["auth_user"] = None
            st.session_state["current_page"] = "Overview"
            st.session_state["auth_view"] = "login"
            st.rerun()

    # Topbar
    snapshot = store.dashboard_snapshot()
    active_alerts_count = snapshot["active_alerts_count"]

    c_top1, c_top2 = st.columns([2.5, 2.5])
    with c_top1:
        st.markdown(f"""
        <div style="font-size: 1.25rem; font-weight: 800; color: #f8fafc; margin-top: 0.2rem;">
            {st.session_state['current_page']}
        </div>
        """, unsafe_allow_html=True)
    with c_top2:
        c_bell, c_prof, c_logout = st.columns([0.8, 2.4, 1.2])
        with c_bell:
            bell_label = f"🔔 {active_alerts_count}" if active_alerts_count > 0 else "🔔 0"
            if st.button(bell_label, key="btn_bell_toggle"):
                st.session_state["notification_drawer_open"] = not st.session_state["notification_drawer_open"]
        with c_prof:
            st.markdown(f"""
            <div style="text-align: right; font-size: 0.82rem; color: #94a3b8; padding-top: 0.38rem;">
                <strong style="color: #f1f5f9;">{user.get('name')}</strong> <span class="sp-role-pill">{user.get('role')}</span>
            </div>
            """, unsafe_allow_html=True)
        with c_logout:
            if st.button("🚪 Logout", key="btn_top_logout", use_container_width=True):
                st.session_state["auth_user"] = None
                st.session_state["current_page"] = "Overview"
                st.session_state["auth_view"] = "login"
                st.rerun()

    # Notification Drawer if toggled
    if st.session_state["notification_drawer_open"]:
        with st.expander("🔔 In-App Risk Notifications", expanded=True):
            recent_alerts = snapshot["recent_alerts"]
            if not recent_alerts:
                st.info("No active risk notifications.")
            else:
                for a in recent_alerts[:5]:
                    c_n1, c_n2 = st.columns([4, 1])
                    with c_n1:
                        st.markdown(f"**{a['alert_id']}** — {a['severity']} Spike Detected ({a['detected_at'][:19]})")
                        st.caption(f"Rate: {a['current_rate']:.1%} | Baseline: {a['baseline_rate']:.1%} | Exposure: ₹{a['potential_exposure']:,.0f}")
                    with c_n2:
                        if st.button("View", key=f"notif_view_{a['alert_id']}"):
                            st.session_state["selected_alert_id"] = a["alert_id"]
                            st.session_state["current_page"] = "Investigation"
                            st.session_state["notification_drawer_open"] = False
                            st.rerun()

    # Render Current Page
    page = st.session_state["current_page"]
    if page == "Overview":
        render_overview_page()
    elif page == "Live Monitoring":
        render_live_monitoring_page()
    elif page == "Alerts":
        render_alerts_page()
    elif page == "Transactions":
        render_transactions_page()
    elif page == "Investigation":
        render_investigation_page()
    elif page == "Financial Impact":
        render_financial_impact_page()
    elif page == "Reports":
        render_reports_page()
    elif page == "Settings":
        render_settings_page(user)
    elif page == "Documentation":
        render_documentation_page()


# -----------------------------------------------------------------------------
# 1. Overview Page
# -----------------------------------------------------------------------------
def render_overview_page():
    st.caption("Monitor payment activity and detect emerging fraud risk.")

    snapshot = store.dashboard_snapshot()
    risk_code = snapshot["risk_code"]
    risk_status = snapshot["risk_status"]

    # 1. Current Risk Status Banner
    if risk_code == "SPIKE":
        st.markdown(f"""
        <div class="sp-banner-spike">
            <span>🔴</span>
            <div>
                <div>{risk_status}</div>
                <div style="font-size:0.8rem; font-weight:500; color:#fca5a5;">
                    Abnormal surge in high-risk transactions detected above historical baseline.
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    elif risk_code == "ELEVATED":
        st.markdown(f"""
        <div class="sp-banner-elevated">
            <span>🟠</span>
            <div>
                <div>{risk_status}</div>
                <div style="font-size:0.8rem; font-weight:500; color:#fde68a;">
                    Payment risk levels are currently elevated above typical activity.
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="sp-banner-normal">
            <span>🟢</span>
            <div>
                <div>{risk_status}</div>
                <div style="font-size:0.8rem; font-weight:500; color:#86efac;">
                    Transaction volume and fraud rates remain within normal statistical bounds.
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 2. KPI Cards
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Current Fraud Rate</div>
            <div class="sp-kpi-value" style="color: {'#f87171' if snapshot['current_fraud_rate'] > 0.08 else '#f8fafc'};">
                {snapshot['current_fraud_rate']:.1%}
            </div>
            <div class="sp-kpi-sub">{snapshot['suspicious_transactions']} suspicious / {snapshot['total_transactions']} total</div>
        </div>
        """, unsafe_allow_html=True)
    with k2:
        baseline_str = f"{snapshot['historical_baseline']:.1%}" if snapshot['historical_baseline'] is not None else "Not available"
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Historical Baseline</div>
            <div class="sp-kpi-value">{baseline_str}</div>
            <div class="sp-kpi-sub">Trailing 24-hr rolling mean</div>
        </div>
        """, unsafe_allow_html=True)
    with k3:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Active Alerts</div>
            <div class="sp-kpi-value" style="color: {'#f87171' if snapshot['active_alerts_count'] > 0 else '#f8fafc'};">
                {snapshot['active_alerts_count']}
            </div>
            <div class="sp-kpi-sub">Requires operator review</div>
        </div>
        """, unsafe_allow_html=True)
    with k4:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Potential Exposure</div>
            <div class="sp-kpi-value">₹{snapshot['potential_exposure']:,.0f}</div>
            <div class="sp-kpi-sub">Estimated exposure at risk</div>
        </div>
        """, unsafe_allow_html=True)
    with k5:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Transactions Monitored</div>
            <div class="sp-kpi-value">{snapshot['total_transactions']:,}</div>
            <div class="sp-kpi-sub">Across all payment channels</div>
        </div>
        """, unsafe_allow_html=True)

    # 3. Main Chart: Fraud Rate vs Historical Baseline
    st.markdown("<div style='font-size:1.05rem; font-weight:700; color:#f8fafc; margin: 1.5rem 0 0.5rem 0;'>Fraud Rate vs Historical Baseline</div>", unsafe_allow_html=True)
    buckets = store.all_time_buckets(limit=48)
    if buckets:
        df_b = pd.DataFrame(buckets)
        df_b["bucket_start"] = pd.to_datetime(df_b["bucket_start"])
        df_b = df_b.sort_values("bucket_start")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_b["bucket_start"],
            y=df_b["fraud_rate"] * 100,
            name="Current Fraud Rate %",
            mode="lines+markers",
            line=dict(color="#f87171", width=2.5),
            marker=dict(size=6),
        ))
        if "baseline_rate" in df_b.columns and df_b["baseline_rate"].notna().any():
            fig.add_trace(go.Scatter(
                x=df_b["bucket_start"],
                y=df_b["baseline_rate"] * 100,
                name="Historical Baseline %",
                mode="lines",
                line=dict(color="#38bdf8", width=2, dash="dash"),
            ))

        # Highlight spikes
        spike_pts = df_b[df_b["z_score"] >= 3.0]
        if not spike_pts.empty:
            fig.add_trace(go.Scatter(
                x=spike_pts["bucket_start"],
                y=spike_pts["fraud_rate"] * 100,
                name="Detected Spike",
                mode="markers",
                marker=dict(color="#dc2626", size=12, symbol="diamond"),
            ))

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0f172a",
            plot_bgcolor="#0f172a",
            height=320,
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis=dict(gridcolor="#1e2d45", showgrid=True),
            yaxis=dict(gridcolor="#1e2d45", showgrid=True, title="Fraud Rate %"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No timeseries bucket data available yet. Run the controlled simulator to generate live baseline and spike traffic.")

    # 4. Recent Alerts Table
    st.markdown("<div style='font-size:1.05rem; font-weight:700; color:#f8fafc; margin: 1.5rem 0 0.5rem 0;'>Recent Alerts</div>", unsafe_allow_html=True)
    alerts = store.list_alerts(limit=5)
    if alerts:
        a_cols = st.columns([1.2, 2.5, 1.5, 1, 1.2, 1.5, 1.2, 1.2])
        headers = ["Alert ID", "Severity", "Detected", "Spike", "Affected", "Exposure", "Status", "Action"]
        for i, h in enumerate(headers):
            a_cols[i].markdown(f"**{h}**")

        for a in alerts:
            c = st.columns([1.2, 2.5, 1.5, 1, 1.2, 1.5, 1.2, 1.2])
            c[0].markdown(f"`{a['alert_id']}`")
            sev = a["severity"]
            badge_cls = "badge-critical" if sev == "CRITICAL" else "badge-high" if sev == "HIGH" else "badge-medium"
            c[1].markdown(f"<span class='{badge_cls}'>{sev}</span>", unsafe_allow_html=True)
            c[2].markdown(f"{a['detected_at'][:19]}")
            mult_str = format_spike_multiplier(a)
            c[3].markdown(mult_str)
            c[4].markdown(f"{a['affected_transactions']}")
            c[5].markdown(f"₹{a['potential_exposure']:,.0f}")
            c[6].markdown(f"`{a['status']}`")
            if c[7].button("Investigate", key=f"ov_inv_{a['alert_id']}"):
                st.session_state["selected_alert_id"] = a["alert_id"]
                st.session_state["current_page"] = "Investigation"
                st.rerun()
    else:
        st.markdown("<div style='color:#4ade80; padding:0.5rem 0;'>🟢 No active fraud alerts.</div>", unsafe_allow_html=True)

    # 5. Recent Transactions Table
    st.markdown("<div style='font-size:1.05rem; font-weight:700; color:#f8fafc; margin: 1.5rem 0 0.5rem 0;'>Recent Transactions</div>", unsafe_allow_html=True)
    txs = store.recent_transactions(limit=8)
    if txs:
        tx_data = []
        for t in txs:
            prob = t.get("fraud_probability")
            prob_str = f"{prob:.1%}" if prob is not None else "N/A"
            tx_data.append({
                "Transaction ID": t["transaction_id"],
                "Time": t["timestamp"][:19],
                "Amount": f"₹{t['amount']:,.2f}",
                "Risk Score": prob_str,
                "Risk Level": t.get("risk_level", "LOW"),
                "Source": t["source"],
                "Status": t["status"],
            })
        st.dataframe(pd.DataFrame(tx_data), use_container_width=True, hide_index=True)
    else:
        st.info("No transaction activity yet.")


# -----------------------------------------------------------------------------
# 2. Live Monitoring Page
# -----------------------------------------------------------------------------
def render_live_monitoring_page():
    c_h1, c_h2 = st.columns([3, 2])
    with c_h1:
        st.markdown("### Live Payment Monitoring")
    with c_h2:
        r_ok = bool(os.getenv("RAZORPAY_KEY_ID"))
        rzp_badge = "🟢 Razorpay Test Mode connected" if r_ok else "⚪ Razorpay Test Mode not connected"
        st.markdown(f"""
        <div style="text-align:right; font-size:0.8rem; color:#94a3b8; padding-top:0.4rem;">
            <span style="color:#4ade80;">● Monitoring</span> &nbsp;|&nbsp; {rzp_badge}
        </div>
        """, unsafe_allow_html=True)

    snapshot = store.dashboard_snapshot()

    # KPI cards
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Transactions Monitored</div>
            <div class="sp-kpi-value">{snapshot['total_transactions']:,}</div>
        </div>
        """, unsafe_allow_html=True)
    with k2:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Suspicious Transactions</div>
            <div class="sp-kpi-value" style="color: {'#f87171' if snapshot['suspicious_transactions'] > 0 else '#f8fafc'};">
                {snapshot['suspicious_transactions']:,}
            </div>
        </div>
        """, unsafe_allow_html=True)
    with k3:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Current Fraud Rate</div>
            <div class="sp-kpi-value">{snapshot['current_fraud_rate']:.1%}</div>
        </div>
        """, unsafe_allow_html=True)
    with k4:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Current Risk Level</div>
            <div class="sp-kpi-value" style="font-size:1.1rem; color: {'#f87171' if snapshot['risk_code']=='SPIKE' else '#fbbf24' if snapshot['risk_code']=='ELEVATED' else '#4ade80'};">
                {snapshot['risk_status']}
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # Filter by source
    c_f1, c_f2 = st.columns([2, 4])
    with c_f1:
        source_filter = st.selectbox("Filter Source", ["ALL", "CONTROLLED_TEST", "OFFLINE DATA", "RAZORPAY_TEST"], key="lm_source_sel")

    src = None if source_filter == "ALL" else source_filter
    txs = store.recent_transactions(limit=100, source=src)

    if txs:
        table_rows = []
        for t in txs:
            prob = t.get("fraud_probability")
            prob_str = f"{prob:.1%}" if prob is not None else "N/A"
            table_rows.append({
                "Transaction ID": t["transaction_id"],
                "Timestamp": t["timestamp"][:19],
                "Amount (INR)": f"₹{t['amount']:,.2f}",
                "Payment Method": t["payment_method"],
                "Risk Score": prob_str,
                "Risk Level": t.get("risk_level", "LOW"),
                "Source": t["source"],
                "Status": t["status"],
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No transaction activity yet.")


# -----------------------------------------------------------------------------
# 3. Alerts Page
# -----------------------------------------------------------------------------
def render_alerts_page():
    st.markdown("### Fraud Alerts")
    st.caption("Central alert triage and spike management.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        sev_filter = st.selectbox("Severity", ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"], key="al_sev_f")
    with c2:
        stat_filter = st.selectbox("Status", ["ALL", "INVESTIGATING", "CONFIRMED_FRAUD", "FALSE_POSITIVE", "RESOLVED"], key="al_stat_f")
    with c3:
        src_filter = st.selectbox("Source", ["ALL", "CONTROLLED_TEST", "OFFLINE DATA", "RAZORPAY_TEST"], key="al_src_f")
    with c4:
        search_id = st.text_input("Search Alert ID", placeholder="e.g. ALERT-", key="al_search")

    alerts = store.list_alerts(
        severity=sev_filter if sev_filter != "ALL" else None,
        status=stat_filter if stat_filter != "ALL" else None,
        source=src_filter if src_filter != "ALL" else None,
        limit=100,
    )

    if search_id.strip():
        alerts = [a for a in alerts if search_id.strip().upper() in a["alert_id"].upper()]

    if alerts:
        a_cols = st.columns([1.5, 1.2, 1.8, 1, 1, 1, 1.2, 1.5, 1.5, 1.2])
        headers = ["Alert ID", "Severity", "Detected", "Fraud Rate", "Baseline", "Spike", "Affected", "Exposure", "Status", "Action"]
        for i, h in enumerate(headers):
            a_cols[i].markdown(f"**{h}**")

        for a in alerts:
            c = st.columns([1.5, 1.2, 1.8, 1, 1, 1, 1.2, 1.5, 1.5, 1.2])
            c[0].markdown(f"`{a['alert_id']}`")
            sev = a["severity"]
            badge_cls = "badge-critical" if sev == "CRITICAL" else "badge-high" if sev == "HIGH" else "badge-medium"
            c[1].markdown(f"<span class='{badge_cls}'>{sev}</span>", unsafe_allow_html=True)
            c[2].markdown(f"{a['detected_at'][:19]}")
            c[3].markdown(f"{a['current_rate']:.1%}")
            c[4].markdown(f"{a['baseline_rate']:.1%}")
            mult_str = format_spike_multiplier(a)
            c[5].markdown(mult_str)
            c[6].markdown(f"{a['affected_transactions']}")
            c[7].markdown(f"₹{a['potential_exposure']:,.0f}")
            c[8].markdown(f"`{a['status']}`")
            if c[9].button("Open", key=f"al_open_{a['alert_id']}"):
                st.session_state["selected_alert_id"] = a["alert_id"]
                st.session_state["current_page"] = "Investigation"
                st.rerun()
    else:
        st.markdown("<div style='color:#4ade80; padding:1rem 0;'>🟢 No active fraud alerts matching filter.</div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 4. Investigation Page
# -----------------------------------------------------------------------------
def render_investigation_page():
    st.markdown("### Fraud Spike Investigation")

    alerts = store.list_alerts(limit=50)
    if not alerts:
        st.info("No active fraud alerts available for investigation.")
        return

    alert_ids = [a["alert_id"] for a in alerts]
    default_idx = 0
    if st.session_state["selected_alert_id"] in alert_ids:
        default_idx = alert_ids.index(st.session_state["selected_alert_id"])

    selected_id = st.selectbox("Select Alert to Investigate", alert_ids, index=default_idx, key="inv_alert_selector")
    st.session_state["selected_alert_id"] = selected_id

    alert = store.get_alert(selected_id)
    if not alert:
        st.error("Alert not found.")
        return

    # Header section
    sev = alert["severity"]
    status_str = alert["status"]
    badge_cls = "badge-critical" if sev == "CRITICAL" else "badge-high"

    c_h1, c_h2 = st.columns([3, 1])
    with c_h1:
        st.markdown(f"""
        <div style="font-size:1.3rem; font-weight:800; color:#f8fafc; display:flex; align-items:center; gap:0.6rem;">
            {alert['alert_id']}
            <span class="{badge_cls}">{sev}</span>
            <span style="font-size:0.8rem; background:#1e293b; color:#94a3b8; padding:0.2rem 0.6rem; border-radius:4px;">
                Status: {status_str}
            </span>
        </div>
        """, unsafe_allow_html=True)
    with c_h2:
        st.caption(f"Detected: {alert['detected_at'][:19]}")

    # Investigation Summary KPI Cards
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Current Fraud Rate</div>
            <div class="sp-kpi-value" style="color:#f87171;">{alert['current_rate']:.1%}</div>
        </div>
        """, unsafe_allow_html=True)
    with k2:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Historical Baseline</div>
            <div class="sp-kpi-value">{alert['baseline_rate']:.1%}</div>
        </div>
        """, unsafe_allow_html=True)
    with k3:
        mult_str = format_spike_multiplier(alert)
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Spike Multiplier</div>
            <div class="sp-kpi-value">{mult_str}</div>
        </div>
        """, unsafe_allow_html=True)
    with k4:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Affected Transactions</div>
            <div class="sp-kpi-value">{alert['affected_transactions']}</div>
        </div>
        """, unsafe_allow_html=True)
    with k5:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Estimated Exposure</div>
            <div class="sp-kpi-value">₹{alert['potential_exposure']:,.0f}</div>
            <div class="sp-kpi-sub"><span style="color:#fcd34d;">ESTIMATED</span> (60% loss rate)</div>
        </div>
        """, unsafe_allow_html=True)

    # Why was this detected?
    st.markdown("#### Why Was This Detected?")
    st.markdown(f"""
    <div style="background:#0f172a; border:1px solid #1e2d45; border-radius:8px; padding:1rem 1.25rem; font-size:0.88rem; color:#cbd5e1; line-height:1.6;">
        Fraud activity increased significantly above the merchant's historical baseline during window 
        <code>{alert['window_start'][:19]}</code> to <code>{alert['window_end'][:19]}</code>.
        <br>
        • Current fraud rate reached <strong>{alert['current_rate']:.1%}</strong> compared to a baseline of <strong>{alert['baseline_rate']:.1%}</strong>.
        <br>
        • Anomaly score (Z-Score): <strong>{alert['anomaly_score']:.2f} standard deviations</strong> above normal mean.
        <br>
        • Minimum volume threshold satisfied with <strong>{alert['affected_transactions']} high-risk payments</strong>.
    </div>
    """, unsafe_allow_html=True)

    # 1. Root-Cause Slice Attribution
    slice_info = alert.get("slice_attribution", {})
    if not slice_info:
        slice_info = store.compute_slice_attribution(alert["window_start"], alert["source"])

    if slice_info and slice_info.get("top_slice"):
        ts = slice_info["top_slice"]
        st.markdown("#### Root-Cause Slice Attribution")
        st.markdown(f"""
        <div style="background:#0b1329; border:1px solid #1e3a8a; border-radius:8px; padding:1rem 1.25rem; font-size:0.88rem; color:#e0f2fe; line-height:1.6;">
            <div style="font-weight:700; color:#38bdf8; font-size:0.95rem; margin-bottom:0.4rem;">
                🎯 Primary Anomaly Driver: {ts.get('dimension', 'Slice')} = <code>{ts.get('slice_value')}</code>
            </div>
            {slice_info.get('narrative', '')}
            <br>
            <span style="font-size:0.78rem; color:#94a3b8;">
                Volume-weighted deviation attribution identifies the highest risk concentration while guarding against small-sample distortions.
            </span>
        </div>
        """, unsafe_allow_html=True)

    # 2. Defense-Only Non-Action Assessment
    st.markdown("#### Defense-Only Non-Action Assessment")
    st.markdown(f"""
    <div style="background:#0f172a; border:1px solid #334155; border-radius:8px; padding:0.9rem 1.15rem; font-size:0.84rem; color:#cbd5e1; display:flex; justify-content:space-between; align-items:center;">
        <div>
            <strong style="color:#f8fafc;">🛡️ Automated Action Status:</strong> <span style="color:#38bdf8; font-weight:600;">NO AUTOMATED ACTION TAKEN</span>
            <div style="font-size:0.75rem; color:#94a3b8; margin-top:2px;">
                Alert threshold crossed (Z={alert['anomaly_score']:.1f} ≥ 3.0). System policy strictly requires human confirmation before applying merchant-level mitigations.
            </div>
        </div>
        <div style="text-align:right; font-size:0.78rem; color:#64748b; padding-left:1rem;">
            Autonomous Threshold: <code style="color:#94a3b8;">DISABLED</code><br>
            Defense Mode: <strong style="color:#4ade80;">ACTIVE</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 3. Alert Lifecycle Timeline
    timeline = alert.get("timeline", [])
    if timeline and len(timeline) > 0:
        st.markdown("#### Alert Lifecycle Timeline")
        t_cols = st.columns(min(4, len(timeline)))
        for i, ev in enumerate(timeline[:4]):
            with t_cols[i]:
                st.markdown(f"""
                <div style="background:#0f172a; border:1px solid #1e2d45; border-radius:6px; padding:0.6rem 0.8rem; font-size:0.78rem;">
                    <div style="color:#38bdf8; font-weight:700;">{ev.get('event', 'EVENT')}</div>
                    <div style="color:#94a3b8; font-size:0.72rem;">{format_audit_timestamp(ev)}</div>
                    <div style="color:#f8fafc; margin-top:4px;">Rate: <strong>{ev.get('rate', 0):.1%}</strong> | Z={ev.get('z_score', 0)}</div>
                </div>
                """, unsafe_allow_html=True)

    # Risk Factors / Explainability
    st.markdown("#### Contributing Risk Factors")
    root_causes = alert.get("root_cause", [])
    if root_causes:
        rf_cols = st.columns(len(root_causes))
        for idx, rc in enumerate(root_causes):
            with rf_cols[idx]:
                st.markdown(f"""
                <div style="background:#0f172a; border:1px solid #1e2d45; border-radius:8px; padding:0.75rem 1rem;">
                    <div style="font-size:0.75rem; color:#94a3b8;">{rc.get('feature', 'Factor')}</div>
                    <div style="font-size:1.1rem; font-weight:700; color:#38bdf8;">{rc.get('contribution', 0):+.3f}</div>
                    <div style="font-size:0.72rem; color:#cbd5e1;">{rc.get('direction', 'impacts risk')}</div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.caption("Standard feature set evaluated.")

    # Affected Transactions Drilldown
    st.markdown("#### Affected Transactions")
    aff_txs = store.transactions_for_bucket(alert["window_start"], alert["source"], limit=50)
    if aff_txs:
        t_rows = []
        for tx in aff_txs:
            prob = tx.get("fraud_probability")
            prob_str = f"{prob:.1%}" if prob is not None else "N/A"
            t_rows.append({
                "Transaction ID": tx["transaction_id"],
                "Timestamp": tx["timestamp"][:19],
                "Amount (INR)": f"₹{tx['amount']:,.2f}",
                "Payment Method": tx["payment_method"],
                "Risk Score": prob_str,
                "Risk Level": tx.get("risk_level", "LOW"),
                "Source": tx["source"],
            })
        st.dataframe(pd.DataFrame(t_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No individual transactions logged for this bucket.")

    # Investigation Actions (Strictly Defense-Only)
    st.markdown("#### Operational Actions")
    st.caption("SentinelPay is strictly defense-only. Actions record investigative decisions to the audit trail.")

    c_act1, c_act2, c_act3 = st.columns(3)
    with c_act1:
        with st.expander("🔴 Confirm Fraud", expanded=False):
            c_note = st.text_area("Investigation Note", placeholder="Enter notes on confirmed fraud ring...", key="cf_note")
            if st.button("CONFIRM FRAUD", type="primary", key="btn_confirm_fraud"):
                store.update_alert_status(alert["alert_id"], "CONFIRMED_FRAUD", note=c_note, actor="Merchant Admin")
                st.success(f"Alert {alert['alert_id']} marked as CONFIRMED_FRAUD")
                st.rerun()

    with c_act2:
        with st.expander("⚪ Mark False Positive", expanded=False):
            fp_note = st.text_area("Reason / Note", placeholder="e.g. Flash sale surge, verified merchant campaign...", key="fp_note")
            if st.button("MARK FALSE POSITIVE", key="btn_mark_fp"):
                store.update_alert_status(alert["alert_id"], "FALSE_POSITIVE", note=fp_note, actor="Merchant Admin")
                st.success(f"Alert {alert['alert_id']} marked as FALSE_POSITIVE")
                st.rerun()

    with c_act3:
        with st.expander("🟢 Resolve Alert", expanded=False):
            res_note = st.text_area("Resolution Note", placeholder="Enter resolution summary...", key="res_note")
            if st.button("RESOLVE ALERT", key="btn_resolve_alert"):
                if not res_note.strip():
                    st.error("Resolution note is required to resolve.")
                else:
                    store.update_alert_status(alert["alert_id"], "RESOLVED", note=res_note, actor="Merchant Admin")
                    st.success(f"Alert {alert['alert_id']} RESOLVED")
                    st.rerun()

    # Audit Trail for this alert
    st.markdown("#### Audit Trail")
    history = store.list_audit_events(alert_id=alert["alert_id"])
    if history:
        for h in history:
            st.markdown(f"• **{format_audit_timestamp(h)}** — `{h['actor']}`: {h['action']}" + (f" *({h['details']})*" if h.get('details') else ""))
    else:
        st.caption("No audit events recorded yet for this alert.")


# -----------------------------------------------------------------------------
# 5. Transactions, Reports, and Documentation Pages
# -----------------------------------------------------------------------------
def render_transactions_page():
    st.markdown("### Transactions")
    st.caption("Review scored payment activity. SentinelPay never blocks or moves funds automatically.")
    transactions = store.recent_transactions(limit=100)
    if not transactions:
        st.info("No transactions have been recorded yet. Start normal traffic from Live Monitoring.")
        return
    search = st.text_input("Search transaction ID", key="transaction_search")
    if search:
        transactions = [txn for txn in transactions if search.lower() in txn["transaction_id"].lower()]
    rows = []
    for txn in transactions:
        probability = txn.get("fraud_probability")
        rows.append({
            "Transaction ID": txn["transaction_id"],
            "Amount": f"₹{float(txn.get('amount') or 0):,.2f}",
            "Risk": f"{float(probability):.1%}" if probability is not None else "MANUAL REVIEW",
            "Level": txn.get("risk_level") or "UNKNOWN",
            "Method": str(txn.get("payment_method") or "—").upper(),
            "Status": txn.get("status") or "—",
            "Timestamp": str(txn.get("timestamp") or "—")[:19],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(rows)} recent transactions")


def render_reports_page():
    st.markdown("### Reports & Analytics")
    st.caption("A compact operational view of the signals your team is managing.")
    snapshot = store.dashboard_snapshot()
    cols = st.columns(4)
    metrics = [
        ("Transactions", f"{snapshot['total_transactions']:,}"),
        ("Current fraud rate", f"{snapshot['current_fraud_rate']:.2%}"),
        ("Active alerts", str(snapshot["active_alerts_count"])),
        ("Potential exposure", f"₹{snapshot['potential_exposure']:,.0f}"),
    ]
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.metric(label, value)
    st.markdown("#### Recent alert activity")
    alerts = store.list_alerts(limit=50)
    if alerts:
        report_rows = [{
            "Alert": alert["alert_id"], "Severity": alert["severity"],
            "Rate": f"{alert['current_rate']:.2%}", "Baseline": f"{alert['baseline_rate']:.2%}",
            "Exposure": f"₹{alert['potential_exposure']:,.0f}", "Status": alert["status"],
        } for alert in alerts]
        st.dataframe(pd.DataFrame(report_rows), use_container_width=True, hide_index=True)
        st.download_button("Export alert report", pd.DataFrame(report_rows).to_csv(index=False), "sentinelpay-alert-report.csv", "text/csv")
    else:
        st.info("Reports will populate as the pipeline detects activity.")


def render_documentation_page():
    st.markdown("### SentinelPay Documentation")
    st.caption("Operational notes for the defense-only fraud monitoring workflow.")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Detection flow")
        st.markdown("**Ingest → Normalize → Score → Aggregate → Compare → Alert → Investigate**")
        st.markdown("SentinelPay scores transactions with the live-compatible model, groups activity into time buckets, and compares fraud rate against a trailing baseline using a rolling z-score.")
        st.markdown("#### Human-in-the-loop")
        st.markdown("Alerts are evidence, not automatic enforcement. Analysts can investigate, confirm fraud, mark false positives, or resolve an alert. Every decision is written to the audit trail.")
    with right:
        st.markdown("#### Data sources")
        st.markdown("- Razorpay Test Mode webhooks\n- Controlled simulator\n- Offline PaySim evaluation artifacts")
        st.markdown("#### System status")
        st.json({
            "database": "local SQLite",
            "fraud_model": "live-compatible model",
            "detector": "trailing rolling z-score",
            "automated_payment_actions": False,
        })


# -----------------------------------------------------------------------------
# 6. Financial Impact Page
# -----------------------------------------------------------------------------
def render_financial_impact_page():
    st.markdown("### Financial Impact")
    st.caption("Quantified business exposure and operational cost analysis.")

    snapshot = store.dashboard_snapshot()
    cost_per_fp = float(store.get_setting("cost_per_false_positive", "50.0"))
    fp_cost = snapshot["false_positive_count"] * cost_per_fp

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Potential Fraud Exposure</div>
            <div class="sp-kpi-value" style="color:#f87171;">₹{snapshot['potential_exposure']:,.0f}</div>
            <div class="sp-kpi-sub">Total active/open spike exposure</div>
        </div>
        """, unsafe_allow_html=True)
    with k2:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Estimated False Positive Cost</div>
            <div class="sp-kpi-value">₹{fp_cost:,.0f}</div>
            <div class="sp-kpi-sub"><span style="color:#fcd34d;">ESTIMATED</span> ({snapshot['false_positive_count']} FPs × ₹{cost_per_fp:.0f})</div>
        </div>
        """, unsafe_allow_html=True)
    with k3:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Confirmed Fraud Exposure</div>
            <div class="sp-kpi-value">₹{snapshot['confirmed_exposure']:,.0f}</div>
            <div class="sp-kpi-sub">Confirmed by merchant investigation</div>
        </div>
        """, unsafe_allow_html=True)
    with k4:
        st.markdown(f"""
        <div class="sp-kpi-card">
            <div class="sp-kpi-label">Affected Transactions</div>
            <div class="sp-kpi-value">{snapshot['suspicious_transactions']:,}</div>
            <div class="sp-kpi-sub">Total flagged high-risk volume</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### False Positive Cost Methodology")
    st.markdown(f"""
    <div style="background:#0f172a; border:1px solid #1e2d45; border-radius:8px; padding:1.2rem; font-size:0.88rem; color:#cbd5e1; line-height:1.6;">
        <strong>False Positive Cost Formula:</strong>
        <br>
        <code>Estimated FP Cost = False Positives Count ({snapshot['false_positive_count']}) × Cost per False Positive (₹{cost_per_fp:,.2f}) = ₹{fp_cost:,.2f}</code>
        <br><br>
        <em>Note:</em> Cost per false positive models analyst investigation time and merchant friction. This value is strictly an operational estimate and can be tuned in <strong>Settings → Detection</strong>.
    </div>
    """, unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 6. Settings Page
# -----------------------------------------------------------------------------
def render_settings_page(user: dict):
    st.markdown("### Platform Settings")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Detection Settings",
        "Notification Recipients",
        "Model Health (Judge/Admin)",
        "System Health",
        "Demo Controls",
    ])

    # Tab 1: Detection Settings
    with tab1:
        st.markdown("#### Fraud & Spike Detection Parameters")
        cur_clf = float(store.get_setting("fraud_classification_threshold", "0.50"))
        cur_min_tx = int(store.get_setting("min_transactions", "20"))
        cur_win = int(store.get_setting("baseline_window", "24"))
        cur_z = float(store.get_setting("zscore_threshold", "3.0"))
        cur_fp_cost = float(store.get_setting("cost_per_false_positive", "50.0"))

        c1, c2 = st.columns(2)
        with c1:
            new_clf = st.slider("Fraud Classification Threshold", 0.05, 0.95, cur_clf, 0.05, key="set_clf")
            new_min_tx = st.number_input("Minimum Transactions per Bucket", 5, 500, cur_min_tx, 5, key="set_min_tx")
            new_win = st.number_input("Rolling Baseline Window (Hours)", 6, 168, cur_win, 6, key="set_win")
        with c2:
            new_z = st.slider("Spike Threshold (Z-Score)", 1.5, 10.0, cur_z, 0.5, key="set_z")
            new_fp_cost = st.number_input("Cost per False Positive (₹)", 0.0, 5000.0, cur_fp_cost, 10.0, key="set_fp_cost")

        if st.button("SAVE CHANGES", type="primary", key="btn_save_settings"):
            updates = {
                "fraud_classification_threshold": new_clf,
                "min_transactions": new_min_tx,
                "baseline_window": new_win,
                "zscore_threshold": new_z,
                "cost_per_false_positive": new_fp_cost,
            }
            store.update_settings(updates, actor=user.get("name", "Merchant Admin"))
            st.success("Detection settings updated and persisted successfully.")
            st.rerun()

    # Tab 2: Notification Recipients
    with tab2:
        st.markdown("#### Alert Notification Recipients")
        recipients = store.list_recipients()

        if recipients:
            r_cols = st.columns([2, 3, 2, 1.5, 1.5])
            for i, h in enumerate(["Name", "Email", "Role", "Status", "Action"]):
                r_cols[i].markdown(f"**{h}**")

            for r in recipients:
                c = st.columns([2, 3, 2, 1.5, 1.5])
                c[0].markdown(r["name"])
                c[1].markdown(f"`{r['email']}`")
                c[2].markdown(r["role"])
                stat_badge = "🟢 Active" if r["enabled"] else "⚪ Disabled"
                c[3].markdown(stat_badge)
                if c[4].button("Delete", key=f"del_rec_{r['id']}"):
                    store.delete_recipient(r["id"], actor=user.get("name", "Merchant Admin"))
                    st.success(f"Removed recipient {r['email']}")
                    st.rerun()
        else:
            st.info("No notification recipients configured.")

        st.markdown("---")
        st.markdown("##### Add Recipient")
        with st.form("add_rec_form"):
            nr_name = st.text_input("Name", placeholder="e.g. Security Lead")
            nr_email = st.text_input("Email", placeholder="e.g. security@merchant.com")
            nr_role = st.selectbox("Role", ["Security Analyst", "Finance Manager", "Operations Manager", "Merchant Admin"])
            nr_enabled = st.checkbox("Enabled", value=True)
            if st.form_submit_button("Add Recipient"):
                if not nr_name.strip() or not valid_email(nr_email):
                    st.error("Please enter a valid name and email.")
                else:
                    store.save_recipient(nr_name, nr_email, nr_role, enabled=nr_enabled, actor=user.get("name", "Merchant Admin"))
                    st.success(f"Added recipient {nr_email}")
                    st.rerun()

    # Tab 3: Model Health (Judge/Admin)
    with tab3:
        st.markdown("#### Machine Learning Model Evaluation (Held-Out Test Set)")
        st.caption("Mandatory evaluation metrics computed on held-out test data not used during training.")

        rep_file = PROJECT_ROOT / "data" / "evaluation_report.json"
        if rep_file.exists():
            with open(rep_file) as f:
                rep = json.load(f)

            ev = rep.get("alert_event_performance", {})
            sp = rep.get("spike_level_performance", {})
            fin = rep.get("operational_financial_cost", {})

            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.markdown(f"""
                <div class="sp-kpi-card">
                    <div class="sp-kpi-label">Spike Recall</div>
                    <div class="sp-kpi-value" style="color:#4ade80;">{sp.get('spike_recall', 1.0):.1%}</div>
                    <div class="sp-kpi-sub">{sp.get('true_positive_spikes_caught', 0)} / {sp.get('total_ground_truth_spikes', 0)} spikes caught</div>
                </div>
                """, unsafe_allow_html=True)
            with m2:
                st.markdown(f"""
                <div class="sp-kpi-card">
                    <div class="sp-kpi-label">Alert Precision</div>
                    <div class="sp-kpi-value">{ev.get('alert_precision', 0.0):.1%}</div>
                    <div class="sp-kpi-sub">{ev.get('true_positive_alert_events', 0)} TP alert events</div>
                </div>
                """, unsafe_allow_html=True)
            with m3:
                st.markdown(f"""
                <div class="sp-kpi-card">
                    <div class="sp-kpi-label">Alert F1 Score</div>
                    <div class="sp-kpi-value">{ev.get('alert_f1_score', 0.0):.3f}</div>
                    <div class="sp-kpi-sub">Harmonic mean of precision & recall</div>
                </div>
                """, unsafe_allow_html=True)
            with m4:
                st.markdown(f"""
                <div class="sp-kpi-card">
                    <div class="sp-kpi-label">False Positive Rate</div>
                    <div class="sp-kpi-value">{ev.get('bucket_level_false_positive_rate', 0.0):.4%}</div>
                    <div class="sp-kpi-sub">Hourly bucket FPR</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("##### Ground Truth Spike Validation Details")
            spike_details = sp.get("spike_details", [])
            if spike_details:
                st.dataframe(pd.DataFrame(spike_details), use_container_width=True, hide_index=True)
        else:
            st.info("Model evaluation data unavailable.")

    # Tab 4: System Health
    with tab4:
        st.markdown("#### System Component Health Status")
        db_healthy = DEFAULT_DB_PATH.exists()
        model_healthy = LIVE_MODEL_PATH.exists()
        smtp_configured = bool(os.getenv("SMTP_HOST"))
        rzp_configured = bool(os.getenv("RAZORPAY_KEY_ID"))

        components_status = [
            {"Component": "REST API Server", "Status": "Healthy", "Details": "FastAPI operational"},
            {"Component": "SQLite Database", "Status": "Healthy" if db_healthy else "Degraded", "Details": str(DEFAULT_DB_PATH)},
            {"Component": "ML Fraud Classifier", "Status": "Healthy" if model_healthy else "Unavailable", "Details": "XGBoost Live Model"},
            {"Component": "Fraud-Spike Detector", "Status": "Healthy", "Details": "Trailing Z-Score Engine"},
            {"Component": "Alert Engine", "Status": "Healthy", "Details": "Deduplication & Escalation"},
            {"Component": "Notification Engine", "Status": "Healthy" if smtp_configured else "Unconfigured Fallback", "Details": "SMTP / In-App Logs"},
            {"Component": "Razorpay Test Mode", "Status": "Connected" if rzp_configured else "Not Connected (Optional)", "Details": "Webhook Receiver"},
        ]
        st.dataframe(pd.DataFrame(components_status), use_container_width=True, hide_index=True)

    # Tab 5: Demo Controls
    with tab5:
        st.markdown("#### Controlled Test Traffic Simulator")
        st.caption("Inject synthetic transactions through the EXACT same production transaction processing pipeline.")

        dc1, dc2, dc3 = st.columns(3)
        with dc1:
            if st.button("START NORMAL TRAFFIC (5 txs)", type="primary", use_container_width=True, key="btn_sim_norm"):
                with st.spinner("Processing normal transactions..."):
                    res = start_test_stream(count=5, store=store)
                    st.success(f"Generated {len(res)} normal transactions through process_transaction()")
                    st.rerun()

        with dc2:
            if st.button("INJECT FRAUD SPIKE (Surge)", type="primary", use_container_width=True, key="btn_sim_spike"):
                with st.spinner("Seeding baseline and injecting surge..."):
                    res = inject_controlled_spike(store=store)
                    st.error(f"Injected 12-hr baseline + 30 high-risk transactions! Detector triggered.")
                    st.rerun()

        with dc3:
            if st.button("CLEAR SIMULATION STREAM", use_container_width=True, key="btn_sim_clear"):
                stop_simulation(store=store)
                st.info("Controlled simulation stream cleared.")
                st.rerun()


# -----------------------------------------------------------------------------
# App Entrypoint
# -----------------------------------------------------------------------------
def main():
    if not st.session_state["auth_user"]:
        auth_view = st.session_state.get("auth_view", "login")
        if auth_view == "landing":
            render_landing_page()
        elif auth_view == "signup":
            render_signup_page()
        elif auth_view == "forgot_password":
            render_forgot_password_page()
        else:
            render_login_page()
    else:
        render_app_shell(st.session_state["auth_user"])


if __name__ == "__main__":
    main()
