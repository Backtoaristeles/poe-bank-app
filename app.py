import streamlit as st
import pandas as pd
import math
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# --- FIREBASE INIT ---
st.set_page_config(page_title="PoE Bulk Item Bank", layout="wide")
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase_json"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- CONFIG ---
ADMIN_USERS = ["Diablo", "JESUS", "LT"]
ADMIN_PASSWORDS = {
    "Diablo": "DiabloSecret123",
    "JESUS": "JesusPass456",
    "LT": "LtCool789"
}
SESSION_TIMEOUT = 15 * 60

ORIGINAL_ITEM_CATEGORIES = {
    "Waystones": [
        "Waystone EXP + Delirious",
        "Waystone EXP 35%",
        "Waystone EXP"
    ],
    "White Item Bases": [
        "Stellar Amulet",
        "Breach ring level 82",
        "Heavy Belt"
    ],
    "Tablets": [
        "Tablet Exp 9%+10% (random)",
        "Grand Project Tablet"
    ],
    "Various": [
        "Logbook level 79-80"
    ]
}
ALL_ITEMS = sum(ORIGINAL_ITEM_CATEGORIES.values(), [])
DEFAULT_BANK_BUY_PCT = 80

CATEGORY_COLORS = {
    "Waystones": "#FFD700",
    "White Item Bases": "#FFFFFF",
    "Tablets": "#AA66CC",
    "Various": "#42A5F5",
}
ITEM_COLORS = {
    "Breach ring level 82": "#D6A4FF",
    "Stellar Amulet": "#FFD700",
    "Heavy Belt": "#A4FFA3",
    "Waystone EXP + Delirious": "#FF6961",
    "Waystone EXP 35%": "#FFB347",
    "Waystone EXP": "#FFB347",
    "Tablet Exp 9%+10% (random)": "#7FDBFF",
    "Grand Project Tablet": "#FFDCB9",
    "Logbook level 79-80": "#42A5F5",
}
def get_item_color(item): return ITEM_COLORS.get(item, "#FFF")

def ss(key, default=None):
    return st.session_state[key] if key in st.session_state else default

def init_session():
    defaults = {
        "admin_logged": False,
        "admin_user": "",
        "show_login": False,
        "login_failed": False,
        "deposit_in_progress": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
init_session()

def check_admin_timeout():
    if ss('admin_logged', False):
        now = time.time()
        last = ss('admin_last_action', now)
        if now - last > SESSION_TIMEOUT:
            st.session_state['admin_logged'] = False
            st.session_state['admin_user'] = ""
            st.warning("Admin session expired. Please log in again.")
check_admin_timeout()

# --- FIRESTORE HELPERS ---
def get_item_settings():
    try:
        settings_doc = db.collection("meta").document("item_settings").get()
        targets = {item: 100 for item in ALL_ITEMS}
        divines = {item: 0.0 for item in ALL_ITEMS}
        bank_buy_pct = DEFAULT_BANK_BUY_PCT
        if settings_doc.exists:
            data = settings_doc.to_dict()
            targets.update(data.get("targets", {}))
            divines.update(data.get("divines", {}))
            bank_buy_pct = data.get("bank_buy_pct", DEFAULT_BANK_BUY_PCT)
        return targets, divines, bank_buy_pct
    except:
        return ({item: 100 for item in ALL_ITEMS}, {item: 0.0 for item in ALL_ITEMS}, DEFAULT_BANK_BUY_PCT)

def log_admin(action, details=""):
    try:
        db.collection("admin_logs").add({
            "timestamp": datetime.utcnow(),
            "admin_user": ss("admin_user", "unknown"),
            "action": action,
            "details": details
        })
    except:
        pass

def get_admin_totals(admin_user):
    doc = db.collection("admin_totals").document(admin_user).get()
    if doc.exists:
        data = doc.to_dict()
        return data.get("total_normal_value", 0.0), data.get("total_instant_value", 0.0)
    else:
        return 0.0, 0.0

def update_admin_totals(admin_user, normal_add=0.0, instant_add=0.0):
    norm, inst = get_admin_totals(admin_user)
    db.collection("admin_totals").document(admin_user).set({
        "total_normal_value": norm + normal_add,
        "total_instant_value": inst + instant_add
    })

def reset_admin_totals(admin_user):
    norm, inst = get_admin_totals(admin_user)
    db.collection("admin_totals").document(admin_user).set({
        "total_normal_value": 0.0,
        "total_instant_value": 0.0
    })
    log_admin("Reset Totals", f"Admin: {admin_user} | Before Reset: Normal = {norm:.3f} Div, Instant = {inst:.3f} Div")

def add_instant_sell(admin_user, item, qty, value):
    try:
        doc_ref = db.collection("instant_sells").document(admin_user)
        doc_ref.collection("entries").add({
            "item": item,
            "qty": qty,
            "value": value,
            "timestamp": datetime.utcnow()
        })
        update_admin_totals(admin_user, normal_add=0.0, instant_add=value * qty)
        log_admin("Instant Sell Added", f"{admin_user}: {qty}x {item} (Value per: {value:.3f} Div)")
        return True
    except Exception as e:
        st.error(f"Error adding instant sell: {e}")
        return False

# --- LOGIN HANDLING ---
col1, col2, col3 = st.columns([1,2,1])
with col2:
    if not ss('admin_logged', False):
        if st.button("Admin login"):
            st.session_state['show_login'] = not ss('show_login', False)
            st.info("If you just enabled login, enter credentials below and press the login button in the form.")
    else:
        if st.button("Admin logout"):
            st.session_state['admin_logged'] = False
            st.session_state['admin_user'] = ""
            st.session_state['show_login'] = False
            st.session_state['login_failed'] = False
            st.success("Logged out. Press login again to sign in.")

if ss('show_login', False) and not ss('admin_logged', False):
    col_spacer1, col_login, col_spacer2 = st.columns([1,2,1])
    with col_login:
        with st.form("admin_login_form"):
            st.write("**Admin Login**")
            uname = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
        if submitted:
            if uname in ADMIN_USERS and pw == ADMIN_PASSWORDS[uname]:
                st.session_state['admin_logged'] = True
                st.session_state['admin_user'] = uname
                st.session_state['show_login'] = False
                st.success("Login success! Press the login button again to confirm.")
                log_admin("Admin Login", f"Admin {uname} logged in.")
            else:
                st.session_state['login_failed'] = True
                st.error("Incorrect username or password.")

if ss('admin_logged', False):
    st.caption(f"**Admin mode enabled: {ss('admin_user','')}**")
else:
    st.caption("**Read only mode** (progress & deposit info only)")

# --- LOADING SETTINGS ---
targets, divines, bank_buy_pct = get_item_settings()

# --- ADMIN PANEL: TOTALS ---
if ss('admin_logged', False):
    st.header("🔑 Admin Panel: Your Totals")
    norm_val, inst_val = get_admin_totals(ss('admin_user'))
    st.info(f"Normal Deposits Total Value: **{norm_val:.3f} Divines**")
    st.info(f"Instant Sell Total Value: **{inst_val:.3f} Divines**")
    st.success(f"Combined Total: **{norm_val + inst_val:.3f} Divines**")

    if st.button("⚠️ Reset My Admin Totals (no undo)"):
        reset_admin_totals(ss('admin_user'))
        st.success("Your admin totals have been reset.")

# (Remaining UI & logic for deposit form, instant sell, user dashboard, logs, etc. would follow here)

