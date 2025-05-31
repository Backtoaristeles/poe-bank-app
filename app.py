import streamlit as st
import pandas as pd
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

# --- APP LOGIC ---

def user_dashboard():
    st.title("FundBank: Public Wallet Lookup")
    all_names = get_all_usernames()
    q = st.text_input("Search Username", "", key="search")
    suggestions = [n for n in all_names if q.lower() in n.lower()][:20] if q else []
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
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype(str))
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
    st.title("Admin Panel")

    if not st.session_state.admin_logged:
        with st.form("admin_login_form"):
            uname = st.text_input("Admin Username")
            pw = st.text_input("Admin Password", type="password")
            submitted = st.form_submit_button("Login")
        if submitted:
            if uname in ADMIN_USERS and pw == ADMIN_PASSWORDS[uname]:
                st.session_state.admin_logged = True
                st.session_state.admin_user = uname
                st.session_state.admin_ts = time.time()
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

    if st.session_state.get("show_save_success", False):
        st.success("Saved!")
        st.session_state.show_save_success = False
    if st.session_state.get("show_deposit_success", False):
        st.success("Deposit(s) added!")
        st.session_state.show_deposit_success = False
    if st.session_state.get("show_deposit_warning", ""):
        st.warning(st.session_state.show_deposit_warning)
        st.session_state.show_deposit_warning = ""

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
                f"{item} stack value (Divines)", min_value=0.01,
                value=float(divines.get(item, 0.0)), step=0.1, format="%.2f", key=f"div_{item}"
            )
            new_targets[item] = tgt
            new_divines[item] = div
        if st.form_submit_button("Save All Targets & Values"):
            for v in new_targets.values():
                if v <= 0:
                    st.error("All targets must be positive numbers.")
                    return
            for v in new_divines.values():
                if v <= 0:
                    st.error("All stack values must be positive numbers.")
                    return
            save_item_settings(new_targets, new_divines, bank_buy_pct_new)
            st.session_state.show_save_success = True
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
            st.session_state.show_deposit_warning = "Please select a user before adding deposits."
            st.experimental_rerun()
            return
        any_added = False
        for item, qty in item_qtys.items():
            if qty > 0:
                value = divines.get(item, 0.0)
                ok, reason = add_deposit(user, item, qty, value)
                if ok:
                    any_added = True
        if any_added:
            st.session_state.show_deposit_success = True
        st.experimental_rerun()
        return

# --- PAGE ROUTER ---
pages = ["🏦 User Dashboard", "🔑 Admin Panel"]
page = st.sidebar.radio("Navigate", pages)

if page == "🏦 User Dashboard":
    user_dashboard()
elif page == "🔑 Admin Panel":
    admin_tools()

# --- CATEGORY OVERVIEW, PROGRESS, BREAKDOWN ---
st.header("Deposits Overview")
targets, divines, bank_buy_pct = get_item_settings()
for cat, items in ORIGINAL_ITEM_CATEGORIES.items():
    color = CATEGORY_COLORS.get(cat, "#FFD700")
    st.markdown(f"<h2 style='color:{color}; font-weight:bold; margin-bottom: 14px;'>{cat}</h2>", unsafe_allow_html=True)
    # Aggregate per item
    all_users = get_all_usernames()
    item_totals = []
    for item in items:
        total = 0
        for user in all_users:
            user_deps = get_deposits(user)
            for dep in user_deps:
                if dep["item"] == item:
                    total += dep.get("qty", 0)
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
        # Build per-user summary for this item
        user_summary = []
        for user in all_users:
            user_deps = get_deposits(user)
            qty = sum(dep["qty"] for dep in user_deps if dep["item"] == item)
            if qty > 0:
                user_summary.append({"User": user, "Quantity": qty})
        if user_summary:
            with st.expander("Per-user breakdown & payout", expanded=False):
                summary_df = pd.DataFrame(user_summary)
                payouts = []
                fees = []
                for idx, row in summary_df.iterrows():
                    qty = row["Quantity"]
                    raw_payout = (qty / target) * divine_val if target else 0
                    fee = round(raw_payout * 0.10, 1)
                    payout_after_fee = raw_payout - fee
                    payouts.append(payout_after_fee)
                    fees.append(fee)
                summary_df["Fee (10%)"] = fees
                summary_df["Payout (Divines, after fee)"] = payouts
                st.dataframe(
                    summary_df.style.format({"Fee (10%)": "{:.1f}", "Payout (Divines, after fee)": "{:.1f}"}),
                    use_container_width=True
                )
