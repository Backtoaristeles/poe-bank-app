import streamlit as st
import pandas as pd
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import math

# --- FIREBASE INIT ---
st.set_page_config(page_title="PoE Bulk Item Bank", layout="wide")

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase_json"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- CONFIG ---
ADMIN_USERS = list(st.secrets["admin_passwords"].keys())
ADMIN_PASSWORDS = dict(st.secrets["admin_passwords"])
SESSION_TIMEOUT = 20 * 60

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
        "Quantity Tablet (6%+)",
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
    "Quantity Tablet (6%+)": "#B0E0E6",
    "Grand Project Tablet": "#FFDCB9",
    "Logbook level 79-80": "#42A5F5",
}
def get_item_color(item): return ITEM_COLORS.get(item, "#FFF")

# --- SESSION STATE ---
def init_session():
    defaults = {
        "admin_logged": False,
        "admin_user": "",
        "admin_ts": 0,
        "show_save_success": False,
        "show_deposit_success": False,
        "show_deposit_warning": "",
        "show_login": False,
        "login_failed": False,
        "deposit_submitted": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
init_session()

# --- FIRESTORE FUNCTIONS ---

def get_item_settings():
    try:
        settings_doc = db.collection("meta").document("item_settings").get()
        if settings_doc.exists:
            data = settings_doc.to_dict()
            targets = data.get("targets", {})
            divines = data.get("divines", {})
            bank_buy_pct = data.get("bank_buy_pct", DEFAULT_BANK_BUY_PCT)
            # -- ensure all items are present with default values --
            for item in ALL_ITEMS:
                if item not in targets:
                    targets[item] = 100
                if item not in divines:
                    divines[item] = 0.0
            return targets, divines, bank_buy_pct
    except Exception:
        pass
    # fallback if Firestore unreachable
    return ({item: 100 for item in ALL_ITEMS}, {item: 0.0 for item in ALL_ITEMS}, DEFAULT_BANK_BUY_PCT)

def save_item_settings(targets, divines, bank_buy_pct):
    try:
        db.collection("meta").document("item_settings").set({
            "targets": targets,
            "divines": divines,
            "bank_buy_pct": bank_buy_pct
        }, merge=True)
    except Exception as e:
        st.error(f"Error saving settings: {e}")

def get_all_usernames():
    try:
        users_ref = db.collection("users").stream()
        names = set()
        for u in users_ref:
            names.add(u.id)
        return sorted(list(names))
    except Exception:
        return []

def get_all_deposits():
    users = get_all_usernames()
    all_deps = []
    for user in users:
        deps = get_deposits(user)
        for dep in deps:
            all_deps.append({
                "User": user,
                "Item": dep.get("item"),
                "Quantity": dep.get("qty", 0)
            })
    return pd.DataFrame(all_deps)

def get_deposits(user_id):
    if not user_id: return []
    try:
        deps = db.collection("users").document(user_id).collection("deposits").order_by("timestamp").stream()
        results = []
        for d in deps:
            rec = d.to_dict()
            rec["id"] = d.id
            rec["timestamp"] = pd.to_datetime(rec.get("timestamp", datetime.utcnow()))
            results.append(rec)
        return results
    except Exception:
        return []

def add_deposit(user, item, qty, value):
    try:
        doc_ref = db.collection("users").document(user)
        doc_ref.set({}, merge=True)
        deposits_ref = doc_ref.collection("deposits")
        dep = {
            "item": item,
            "qty": qty,
            "value": value,
            "timestamp": datetime.utcnow()
        }
        deposits_ref.add(dep)
        return True, ""
    except Exception as e:
        st.error(f"Error adding deposit: {e}")
        return False, str(e)

# --- TOP-CENTER ADMIN LOGIN BUTTON OR LOGOUT ---
col1, col2, col3 = st.columns([1,2,1])
with col2:
    if not st.session_state['admin_logged']:
        if st.button("Admin login"):
            st.session_state['show_login'] = not st.session_state['show_login']
    else:
        if st.button("Admin logout"):
            st.session_state['admin_logged'] = False
            st.session_state['admin_user'] = ""
            st.session_state['show_login'] = False
            st.session_state['login_failed'] = False
            st.success("Logged out.")
            st.experimental_rerun()
            st.stop()

if st.session_state['show_login'] and not st.session_state['admin_logged']:
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
                st.session_state['login_failed'] = False
                st.experimental_rerun()
                st.stop()
            else:
                st.session_state['admin_logged'] = False
                st.session_state['admin_user'] = ""
                st.session_state['login_failed'] = True
    if st.session_state['login_failed']:
        st.error("Incorrect username or password.")

if st.session_state['admin_logged']:
    st.caption(f"**Admin mode enabled: {st.session_state['admin_user']}**")
else:
    st.caption("**Read only mode** (progress & deposit info only)")

# --- DATA LOADING ---
targets, divines, bank_buy_pct = get_item_settings()

with st.sidebar:
    st.header("Per-Item Targets & Divine Value")
    if st.session_state['admin_logged']:
        st.subheader("Bank Instant Buy Settings")
        bank_buy_pct_new = st.number_input(
            "Bank buy % of sell price (instant sell payout)",
            min_value=10, max_value=100, step=1,
            value=bank_buy_pct,
            key="bank_buy_pct_input"
        )
        changed = False
        if bank_buy_pct_new != bank_buy_pct:
            bank_buy_pct = bank_buy_pct_new
            changed = True
        new_targets = {}
        new_divines = {}
        st.subheader("Edit Targets and Values")
        for item in ALL_ITEMS:
            cols = st.columns([2, 2])
            tgt = cols[0].number_input(
                f"{item} target",
                min_value=1,
                value=int(targets.get(item, 100)),
                step=1,
                key=f"target_{item}"
            )
            div = cols[1].number_input(
                f"Stack Value (Divines)",
                min_value=0.0,
                value=float(divines.get(item, 0)),
                step=0.1,
                format="%.2f",
                key=f"divine_{item}"
            )
            if tgt != targets[item] or div != divines[item]:
                changed = True
            new_targets[item] = tgt
            new_divines[item] = div
        if st.button("Save Targets and Values") and changed:
            save_item_settings(new_targets, new_divines, bank_buy_pct)
            st.success("Targets, Divine values and Bank % saved! Refresh the page to see updates.")
            st.stop()
    else:
        for item in ALL_ITEMS:
            st.markdown(
                f"""
                <span style='font-weight:bold;'>{item}:</span>
                Target = {targets[item]}, Stack Value = {divines[item]:.2f} Divines<br>
                """,
                unsafe_allow_html=True
            )

# --- MULTI-ITEM DEPOSIT FORM (ADMIN ONLY) ---
if st.session_state['admin_logged']:
    with st.form("multi_item_deposit", clear_on_submit=True):
        st.subheader("Add a Deposit (multiple items per user)")
        user = st.text_input("User")
        col1, col2 = st.columns(2)
        item_qtys = {}
        for i, item in enumerate(ALL_ITEMS):
            col = col1 if i % 2 == 0 else col2
            item_qtys[item] = col.number_input(f"{item}", min_value=0, step=1, key=f"add_{item}")
        submitted = st.form_submit_button("Add Deposit(s)")
        if submitted and user:
            any_added = False
            for item, qty in item_qtys.items():
                if qty > 0:
                    value = divines.get(item, 0.0)
                    ok, reason = add_deposit(user.strip(), item, qty, value)
                    if ok:
                        any_added = True
            if any_added:
                st.success("Deposits added!")
                st.experimental_rerun()
            else:
                st.info("No new deposits added.")
        elif submitted:
            st.warning("Please enter a username.")

st.markdown("---")

# --- DEPOSITS OVERVIEW ---
st.header("Deposits Overview")

df = get_all_deposits()
for cat, items in ORIGINAL_ITEM_CATEGORIES.items():
    color = CATEGORY_COLORS.get(cat, "#FFD700")
    st.markdown(f"""
    <div style='margin-top: 38px;'></div>
    <h2 style="color:{color}; font-weight:bold; margin-bottom: 14px;">{cat}</h2>
    """, unsafe_allow_html=True)
    item_totals = []
    for item in items:
        total = df[(df["Item"] == item)]["Quantity"].sum() if not df.empty else 0
        item_totals.append((item, total))
    item_totals.sort(key=lambda x: x[1], reverse=True)
    for item, total in item_totals:
        item_color = get_item_color(item)
        target = targets[item]
        divine_val = divines[item]
        divine_total = (total / target * divine_val) if target > 0 else 0
        instant_sell_price = (divine_val / target) * bank_buy_pct / 100 if target > 0 else 0

        extra_info = ""
        if divine_val > 0 and target > 0:
            extra_info = (f"<span style='margin-left:22px; color:#AAA;'>"
                          f"[Stack = {divine_val:.2f} Divines → Current Value ≈ {divine_total:.2f} Divines | "
                          f"Instant Sell: <span style='color:#fa0;'>{instant_sell_price:.3f} Divines</span> <span style='font-size:85%; color:#888;'>(per item)</span>]</span>")
        elif divine_val > 0:
            extra_info = (f"<span style='margin-left:22px; color:#AAA;'>"
                          f"[Stack = {divine_val:.2f} Divines → Current Value ≈ {divine_total:.2f} Divines]</span>")

        st.markdown(
            f"""
            <div style='
                display:flex; 
                align-items:center; 
                border: 2px solid #222; 
                border-radius: 10px; 
                margin: 8px 0 16px 0; 
                padding: 10px 18px;
                background: #181818;
            '>
                <span style='font-weight:bold; color:{item_color}; font-size:1.18em; letter-spacing:0.5px;'>
                    [{item}]
                </span>
                <span style='margin-left:22px; font-size:1.12em; color:#FFF;'>
                    <b>Deposited:</b> {total} / {target}
                </span>
                {extra_info}
            </div>
            """,
            unsafe_allow_html=True
        )

        # Progress bar
        if total >= target:
            st.success(f"✅ {total}/{target} – Target reached!")
            st.markdown("""
            <div style='height:22px; width:100%; background:#22c55e; border-radius:7px; display:flex; align-items:center;'>
                <span style='margin-left:10px; color:white; font-weight:bold;'>FULL</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.progress(min(total / target, 1.0), text=f"{total}/{target}")

        # ---- Per-user breakdown & payout ----
        with st.expander("Per-user breakdown & payout", expanded=False):
            item_df = df[df["Item"] == item]
            if not item_df.empty:
                user_summary = (
                    item_df.groupby("User")["Quantity"]
                    .sum()
                    .sort_values(ascending=False)
                    .reset_index()
                )
                payouts = []
                fees = []
                for idx, row in user_summary.iterrows():
                    qty = row["Quantity"]
                    raw_payout = (qty / target) * divine_val if target else 0
                    fee = math.floor((raw_payout * 0.10) * 10) / 10
                    payout_after_fee = raw_payout - (raw_payout * 0.10)
                    payout_final = math.floor(payout_after_fee * 10) / 10
                    payouts.append(payout_final)
                    fees.append(fee)
                user_summary["Fee (10%)"] = fees
                user_summary["Payout (Divines, after fee)"] = payouts
                st.dataframe(
                    user_summary.style.format({"Fee (10%)": "{:.1f}", "Payout (Divines, after fee)": "{:.1f}"}),
                    use_container_width=True
                )
            else:
                st.info("No deposits for this item.")

st.markdown("---")
