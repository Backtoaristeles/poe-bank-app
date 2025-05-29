import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import time
from datetime import datetime, timedelta
import pandas as pd
import math

# 🚨 MUST COME FIRST
st.set_page_config(page_title="PoE Bulk Item Banking App", layout="wide")

# --- FIREBASE INIT ---
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase_json"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

st.title("PoE Bulk Item Banking App")
st.caption("Bulk community banking for PoE item pooling and tracking")

# --- CONFIG ---
ALL_ITEMS = [
    "Waystone EXP + Delirious", "Waystone EXP 35%", "Waystone EXP",
    "Stellar Amulet", "Breach ring level 82", "Heavy Belt",
    "Tablet Exp 9%+10% (random)", "Grand Project Tablet",
    "Logbook level 79-80"
]
DEFAULT_BANK_BUY_PCT = 80
ADMIN_USERS = ["POEconomics", "LT_Does_it_better", "JESUS (Spector)"]
SESSION_TIMEOUT = 20 * 60

CATEGORY_COLORS = {
    "Waystones": "#FFD700",
    "White Item Bases": "#FFFFFF",
    "Tablets": "#AA66CC",
    "Various": "#42A5F5",
}

ITEM_CATEGORIES = {
    "Waystones": ["Waystone EXP + Delirious", "Waystone EXP 35%", "Waystone EXP"],
    "White Item Bases": ["Stellar Amulet", "Breach ring level 82", "Heavy Belt"],
    "Tablets": ["Tablet Exp 9%+10% (random)", "Grand Project Tablet"],
    "Various": ["Logbook level 79-80"]
}

# --- SESSION STATES ---
if 'admin_logged' not in st.session_state:
    st.session_state.admin_logged = False
if 'admin_user' not in st.session_state:
    st.session_state.admin_user = ""

# --- FUNCTIONS ---
def get_targets():
    doc = db.collection("settings").document("targets").get()
    if doc.exists:
        return doc.to_dict()
    else:
        # Initialize if missing
        base = {item: {"target": 100, "divine": 0.0} for item in ALL_ITEMS}
        base["bank_buy_pct"] = DEFAULT_BANK_BUY_PCT
        db.collection("settings").document("targets").set(base)
        return base

def save_targets(updated):
    db.collection("settings").document("targets").set(updated)

def get_deposits():
    docs = db.collection("deposits").stream()
    return [d.to_dict() for d in docs]

def add_deposit(user, item, qty):
    db.collection("deposits").add({
        "user": user, "item": item, "qty": qty,
        "timestamp": datetime.now()
    })

def log_admin(action, details=""):
    db.collection("admin_logs").add({
        "admin": st.session_state.admin_user,
        "action": action,
        "details": details,
        "timestamp": datetime.now()
    })

def get_admin_logs(limit=20):
    return [d.to_dict() for d in db.collection("admin_logs").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit).stream()]

# --- ADMIN LOGIN ---
with st.sidebar:
    if not st.session_state.admin_logged:
        st.subheader("Admin Login")
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        if st.button("Login"):
            if user in ADMIN_USERS:
                st.session_state.admin_logged = True
                st.session_state.admin_user = user
                st.success(f"Welcome, {user}!")
            else:
                st.error("Unauthorized user")
    else:
        st.write(f"Logged in as: {st.session_state.admin_user}")
        if st.button("Logout"):
            st.session_state.admin_logged = False
            st.session_state.admin_user = ""

# --- LOAD DATA ---
targets_data = get_targets()
deposit_list = get_deposits()
df = pd.DataFrame(deposit_list)
if not df.empty:
    df['timestamp'] = pd.to_datetime(df['timestamp'].astype(str))
else:
    df = pd.DataFrame(columns=["user", "item", "qty", "timestamp"])

# --- ADMIN PANEL ---
if st.session_state.admin_logged:
    st.header("Admin Panel")
    st.subheader("Update Item Targets & Divine Values")
    new_targets = {}
    for item in ALL_ITEMS:
        col1, col2 = st.columns(2)
        target = col1.number_input(f"{item} target", value=int(targets_data.get(item, {}).get("target", 100)))
        divine = col2.number_input(f"{item} stack value (Divines)", value=float(targets_data.get(item, {}).get("divine", 0.0)), format="%.2f")
        new_targets[item] = {"target": target, "divine": divine}
    bank_pct = st.number_input("Bank buy % of sell price", min_value=10, max_value=100, step=1, value=int(targets_data.get("bank_buy_pct", DEFAULT_BANK_BUY_PCT)))
    new_targets["bank_buy_pct"] = bank_pct
    if st.button("Save Targets"):
        save_targets(new_targets)
        log_admin("Updated targets and divine values")
        st.success("Targets saved!")

    st.subheader("Add Deposits")
    user = st.text_input("Username")
    item_cols = st.columns(2)
    added = False
    for i, item in enumerate(ALL_ITEMS):
        qty = item_cols[i % 2].number_input(f"{item}", min_value=0, step=1)
        if qty > 0:
            add_deposit(user, item, qty)
            log_admin("Added deposit", f"{user}: {qty}x {item}")
            added = True
    if added:
        st.success("Deposits added!")

    st.subheader("Admin Logs (Last 20)")
    logs = get_admin_logs()
    if logs:
        st.dataframe(pd.DataFrame(logs))
    else:
        st.write("No logs yet.")

# --- PUBLIC OVERVIEW ---
st.header("Community Deposits Overview")
bank_pct = targets_data.get("bank_buy_pct", DEFAULT_BANK_BUY_PCT)
for cat, items in ITEM_CATEGORIES.items():
    st.subheader(cat)
    for item in items:
        total = df[df['item'] == item]['qty'].sum()
        target = targets_data.get(item, {}).get("target", 100)
        divine_val = targets_data.get(item, {}).get("divine", 0.0)
        divine_total = (total / target * divine_val) if target > 0 else 0
        instant_sell = (divine_val / target) * bank_pct / 100 if target > 0 else 0

        st.write(f"**{item}** → Deposited: {total}/{target} | Value ≈ {divine_total:.2f} Divines | Instant Sell: {instant_sell:.3f} per item")

        with st.expander("Per-user breakdown"):
            sub_df = df[df['item'] == item].groupby('user')['qty'].sum().reset_index()
            payouts = []
            fees = []
            for _, row in sub_df.iterrows():
                qty = row['qty']
                raw = (qty / target) * divine_val if target else 0
                fee = math.floor(raw * 0.10 * 10) / 10
                final = math.floor((raw - fee) * 10) / 10
                payouts.append(final)
                fees.append(fee)
            sub_df['Fee (10%)'] = fees
            sub_df['Payout (Divines, after fee)'] = payouts
            st.dataframe(sub_df)

st.success("✅ App fully loaded")
