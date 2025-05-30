import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
from datetime import datetime
import time
import hashlib

# --- CONFIGURATION ---
st.set_page_config(page_title="PoE Bulk Item Bank", layout="wide")
SESSION_TIMEOUT = 20 * 60

def init_firebase():
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(dict(st.secrets["firebase_json"]))
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"Firebase initialization failed: {e}")
        st.stop()
db = init_firebase()

ADMIN_USERS = list(st.secrets["admin_passwords"].keys())
ADMIN_PASSWORDS = {user: st.secrets["admin_passwords"][user] for user in ADMIN_USERS}

ITEM_CATEGORIES = {
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
ALL_ITEMS = [item for sublist in ITEM_CATEGORIES.values() for item in sublist]
DEFAULT_BANK_BUY_PCT = 80

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def safe_to_datetime(val):
    if isinstance(val, datetime):
        return val
    try:
        return pd.to_datetime(val)
    except Exception:
        return pd.NaT

def init_session_state():
    defaults = {
        "admin_logged": False,
        "admin_user": "",
        "admin_ts": 0,
        "just_logged_in": False
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
init_session_state()

# --- DB Functions ---
def get_item_settings():
    try:
        settings_doc = db.collection("meta").document("item_settings").get()
        if settings_doc.exists:
            data = settings_doc.to_dict()
            return (
                data.get("targets", {item: 100 for item in ALL_ITEMS}),
                data.get("divines", {item: 0.0 for item in ALL_ITEMS}),
                data.get("bank_buy_pct", DEFAULT_BANK_BUY_PCT)
            )
    except Exception:
        pass
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

def get_user_from_name(name):
    name = (name or "").strip()
    if not name:
        return None, None
    try:
        user_ref = db.collection("users").document(name).get()
        if user_ref.exists:
            return user_ref.id, user_ref.to_dict()
    except Exception:
        pass
    return None, None

def get_deposits(user_id):
    if not user_id: return []
    try:
        deps = db.collection("users").document(user_id).collection("deposits").order_by("timestamp").stream()
        results = []
        for d in deps:
            rec = d.to_dict()
            rec["id"] = d.id
            rec["timestamp"] = safe_to_datetime(rec.get("timestamp", datetime.utcnow()))
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
        return True
    except Exception as e:
        st.error(f"Error adding deposit: {e}")
        return False

# --- APP LOGIC ---

def user_dashboard():
    st.title("FundBank: Public Wallet Lookup")
    all_names = get_all_usernames()
    q = st.text_input("Search Username", "", key="search")
    suggestions = [n for n in all_names if q.lower() in n.lower()][:10] if q else []
    if suggestions:
        st.write("Suggestions: " + ", ".join(suggestions))
    selected_user = st.selectbox("Select from suggestions", [""] + suggestions) if suggestions else ""
    show_user = selected_user if selected_user else q
    show_user = (show_user or "").strip()
    if not show_user:
        st.info("Search for your username to view your dashboard.")
        return
    user_id, user = get_user_from_name(show_user)
    if not user_id:
        st.warning("No deposits found for this user.")
        return

    st.header(f"User Dashboard: {user_id}")
    st.write(f"**All deposits and payout growth for:** `{user_id}`")
    deposits = get_deposits(user_id)
    if not deposits:
        st.info("No deposits yet.")
        return

    df = pd.DataFrame(deposits)
    if not df.empty and "timestamp" in df.columns:
        df["timestamp"] = df["timestamp"].apply(safe_to_datetime)
        st.subheader("Deposit History")
        st.dataframe(df[["timestamp", "item", "qty", "value"]].sort_values("timestamp", ascending=False), use_container_width=True)

        targets, divines, bank_buy_pct = get_item_settings()
        st.subheader("Payout/Value Growth")
        df["current_value"] = [
            df.iloc[i]["qty"] * divines.get(df.iloc[i]["item"], 0.0)
            for i in range(len(df))
        ]
        st.metric("Total Current Value", f"{df['current_value'].sum():,.2f} Divines")

        st.subheader("Totals per Item Deposited")
        totals = df.groupby("item")["qty"].sum().reset_index()
        st.dataframe(totals, use_container_width=True)
    else:
        st.info("No deposit data available.")

def admin_tools():
    # --- Rerun Handler: For login only, triggers once, then disables itself ---
    if st.session_state.get("just_logged_in", False):
        st.session_state.just_logged_in = False
        st.experimental_rerun()
        return

    st.title("Admin Panel")

    # --- Admin Login ---
    if not st.session_state.admin_logged:
        with st.form("admin_login_form"):
            uname = st.text_input("Admin Username")
            pw = st.text_input("Admin Password", type="password")
            submitted = st.form_submit_button("Login")
        if submitted:
            if uname in ADMIN_USERS:
                correct = ADMIN_PASSWORDS[uname]
                if (pw == correct) or (hash_pw(pw) == correct):
                    st.session_state.admin_logged = True
                    st.session_state.admin_user = uname
                    st.session_state.admin_ts = time.time()
                    st.session_state.just_logged_in = True
                    st.success(f"Logged in as admin: {uname}")
                    return
            st.error("Invalid credentials.")
        return

    if time.time() - st.session_state.admin_ts > SESSION_TIMEOUT:
        st.session_state.admin_logged = False
        st.warning("Session expired. Please log in again.")
        return
    st.session_state.admin_ts = time.time()
    st.info(f"Admin: {st.session_state.admin_user}")

    if st.button("Logout"):
        st.session_state.admin_logged = False
        st.session_state.admin_user = ""
        st.success("Logged out.")
        st.experimental_rerun()
        return

    # --- Settings ---
    st.subheader("Edit Per-Item Targets, Values, Bank Buy %")
    targets, divines, bank_buy_pct = get_item_settings()
    with st.form("edit_targets_form"):
        bank_buy_pct_new = st.number_input(
            "Bank buy % of sell price (instant sell payout)",
            min_value=10, max_value=100, step=1,
            value=bank_buy_pct
        )
        new_targets = {}
        new_divines = {}
        for item in ALL_ITEMS:
            cols = st.columns([2, 2])
            tgt = cols[0].number_input(
                f"{item} target", min_value=1, value=int(targets.get(item, 100)), step=1, key=f"target_{item}"
            )
            div = cols[1].number_input(
                f"{item} stack value (Divines)", min_value=0.0,
                value=float(divines.get(item, 0.0)), step=0.1, format="%.2f", key=f"div_{item}"
            )
            new_targets[item] = tgt
            new_divines[item] = div
        if st.form_submit_button("Save All Targets & Values"):
            save_item_settings(new_targets, new_divines, bank_buy_pct_new)
            st.success("Saved!")
            st.experimental_rerun()
            return

    # --- Add Deposits ---
    st.subheader("Add a Deposit (multiple items per user)")
    all_users = get_all_usernames()
    user = st.selectbox("User", all_users, key="deposit_user_select")
    item_qtys = {}
    col1, col2 = st.columns(2)
    _, divines, _ = get_item_settings()
    for i, item in enumerate(ALL_ITEMS):
        col = col1 if i % 2 == 0 else col2
        item_qtys[item] = col.number_input(f"{item}", min_value=0, step=1, key=f"add_{item}")
    submitted = st.button("Add Deposit(s)", key="add_deposit_btn")
    if submitted:
        if not user:
            st.warning("Please select a user before adding deposits.")
            return
        for item, qty in item_qtys.items():
            if qty > 0:
                add_deposit(user, item, qty, divines.get(item, 0.0))
                st.success(f"Added: {user} - {qty}x {item}")

# --- PAGE ROUTER ---
pages = ["🏦 User Dashboard", "🔑 Admin Panel"]
page = st.sidebar.radio("Navigate", pages)

if page == "🏦 User Dashboard":
    user_dashboard()
elif page == "🔑 Admin Panel":
    admin_tools()
