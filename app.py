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
        "admin_last_action": time.time()
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
init_session()

def update_admin_action():
    st.session_state['admin_last_action'] = time.time()

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

def save_item_settings(targets, divines, bank_buy_pct):
    try:
        db.collection("meta").document("item_settings").set({
            "targets": targets,
            "divines": divines,
            "bank_buy_pct": bank_buy_pct
        }, merge=True)
        log_admin("Edit Targets/Values", f"Targets: {targets}, Divines: {divines}, Bank Buy %: {bank_buy_pct}")
    except Exception as e:
        st.error(f"Error saving settings: {e}")

def log_admin(action, details=""):
    try:
        db.collection("admin_logs").add({
            "timestamp": datetime.utcnow(),
            "admin_user": ss("admin_user", "unknown"),
            "action": action,
            "details": details
        })
    except Exception as e:
        st.error(f"Error logging admin action: {e}")

def show_admin_logs(n=30):
    try:
        logs_ref = db.collection("admin_logs").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(n).stream()
        logs = [l.to_dict() for l in logs_ref]
        if logs:
            df = pd.DataFrame(logs)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp", ascending=False)
            df = df.rename(columns={"timestamp": "Timestamp", "admin_user": "Admin", "action": "Action", "details": "Details"})
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No admin logs yet.")
    except Exception as e:
        st.error(f"Could not load logs: {e}")

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

def add_normal_deposit(user, admin_user, item, qty, value):
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
        update_admin_totals(admin_user, normal_add=value * qty, instant_add=0.0)
        log_admin("Deposit Added", f"{admin_user}: {qty}x {item} for {user} (Value per: {value:.3f} Div)")
        return True
    except Exception as e:
        st.error(f"Error adding deposit: {e}")
        return False

def get_all_usernames():
    try:
        users_ref = db.collection("users").stream()
        names = set()
        for u in users_ref:
            names.add(u.id)
        return sorted(list(names))
    except Exception:
        return []

def get_deposits(user_id):
    if not user_id: return []
    try:
        deps = db.collection("users").document(user_id).collection("deposits").order_by("timestamp").stream()
        results = []
        for d in deps:
            rec = d.to_dict()
            rec["id"] = d.id
            rec["timestamp"] = rec.get("timestamp", datetime.now())
            results.append(rec)
        return results
    except Exception:
        return []

# --- LOGIN HANDLING ---
col1, col2, col3 = st.columns([1,2,1])
with col2:
    if not ss('admin_logged', False):
        if st.button("Admin login"):
            st.session_state['show_login'] = not ss('show_login', False)
            st.info("If you just enabled login, enter credentials below and press the login button in the form. You may need to press login again after entering credentials.")
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
                update_admin_action()
            else:
                st.session_state['login_failed'] = True
                st.error("Incorrect username or password.")

if ss('admin_logged', False):
    st.caption(f"**Admin mode enabled: {ss('admin_user','')}**")
else:
    st.caption("**Read only mode** (progress & deposit info only)")

# --- ADMIN PANEL: TOTALS + RESET ---
if ss('admin_logged', False):
    st.header("🔑 Admin Panel Overview")
    norm_val, inst_val = get_admin_totals(ss('admin_user'))
    combined_val = norm_val + inst_val

    st.subheader(f"Your Total Deposited Value ({ss('admin_user')})")
    colA, colB, colC = st.columns(3)
    colA.metric("Normal Deposits", f"{norm_val:.3f} Div")
    colB.metric("Instant Sells", f"{inst_val:.3f} Div")
    colC.metric("Combined Total", f"{combined_val:.3f} Div")

    if st.button("⚠️ Reset My Admin Totals (no undo)"):
        reset_admin_totals(ss('admin_user'))
        st.success(f"Your admin totals have been reset. (Before reset → Normal: {norm_val:.3f} Div, Instant: {inst_val:.3f} Div)")
        st.experimental_rerun()

    st.markdown("---")

    # --- ADMIN: ADD DEPOSIT/INSTANT SELL FORM ---
    st.subheader("Add Deposit or Instant Sell (admin-only)")
    user = st.text_input("User (for deposit, leave blank for instant sell)", key="deposit_user")
    col1, col2 = st.columns(2)
    item_qtys = {}
    for i, item in enumerate(ALL_ITEMS):
        col = col1 if i % 2 == 0 else col2
        item_qtys[item] = col.number_input(
            f"{item}",
            min_value=0,
            step=1,
            key=f"add_{item}"
        )
    instant_sell = st.checkbox("Add as Instant Sell (not visible to users)", key="instantsell_check")
    if st.button("Add Deposit(s)", key="add_deposit_btn"):
        targets, divines, _ = get_item_settings()
        added_any = False
        for item, qty in item_qtys.items():
            if qty > 0:
                value_per = divines.get(item, 0.0) / targets.get(item, 1)
                if instant_sell:
                    add_instant_sell(ss('admin_user'), item, qty, value_per)
                    added_any = True
                else:
                    if user.strip() == "":
                        st.error("Please enter a user for normal deposits, or check instant sell for admin-only.")
                        continue
                    add_normal_deposit(user.strip(), ss('admin_user'), item, qty, value_per)
                    added_any = True
        if added_any:
            st.success("Deposits processed!")

    st.markdown("---")

    # --- ITEM SETTINGS EDIT ---
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
    st.markdown("---")

# --- USER DASHBOARD/OVERVIEW ---
st.header("Deposits Overview")
targets, divines, bank_buy_pct = get_item_settings()
bank_buy_pct = bank_buy_pct or DEFAULT_BANK_BUY_PCT

for cat, items in ORIGINAL_ITEM_CATEGORIES.items():
    color = CATEGORY_COLORS.get(cat, "#FFD700")
    st.markdown(f"""
    <div style='margin-top: 38px;'></div>
    <h2 style="color:{color}; font-weight:bold; margin-bottom: 14px;">{cat}</h2>
    """, unsafe_allow_html=True)
    item_totals = []
    for item in items:
        # Sum all user deposits for item
        total = 0
        for user in get_all_usernames():
            deps = get_deposits(user)
            for dep in deps:
                if dep.get("item") == item:
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
            summary = []
            for user in get_all_usernames():
                user_deps = get_deposits(user)
                item_qty = sum(dep.get("qty", 0) for dep in user_deps if dep.get("item") == item)
                if item_qty > 0:
                    summary.append({"User": user, "Quantity": item_qty})
            if summary:
                user_summary = pd.DataFrame(summary)
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

# --- WHAT-IF CALCULATOR ---
st.markdown("---")
st.header("💡 What-If Calculator")
st.write("Estimate your payout value for any combination of items and stack sizes!")

targets, divines, bank_buy_pct = get_item_settings()
bank_buy_pct = bank_buy_pct or DEFAULT_BANK_BUY_PCT
calc_inputs = {}
col1, col2 = st.columns(2)
for i, item in enumerate(ALL_ITEMS):
    col = col1 if i % 2 == 0 else col2
    calc_inputs[item] = col.number_input(f"{item} (calc)", min_value=0, step=1, key=f"calc_{item}")

if st.button("Calculate Payout (What-If)"):
    st.subheader("Payout Calculation")
    payout_normal = 0.0
    payout_instant = 0.0
    for item, qty in calc_inputs.items():
        if qty > 0:
            tgt = targets.get(item, 1)
            div = divines.get(item, 0.0)
            per_norm = div / tgt if tgt > 0 else 0
            per_instant = per_norm * (bank_buy_pct / 100)
            st.write(
                f"{item}: {qty} → Stack value: {div:.2f} Div ({tgt} per stack). "
                f"Deposit value: {per_norm:.3f} Div each, Instant Sell: {per_instant:.3f} Div each"
            )
            payout_normal += qty * per_norm
            payout_instant += qty * per_instant
    st.success(f"**Normal Deposit Value:** {payout_normal:.3f} Divines\n\n**Instant Sell Value:** {payout_instant:.3f} Divines")

# --- ADMIN LOGS ---
st.markdown("---")
st.header("Admin Logs (last 30 actions)")
show_admin_logs(30)
