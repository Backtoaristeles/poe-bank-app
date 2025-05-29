import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
from datetime import datetime
import time

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
ALL_ITEMS = sum(ITEM_CATEGORIES.values(), [])

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
DEFAULT_BANK_BUY_PCT = 80

# --- SESSION STATE ---
for k, v in {
    "admin_logged": False,
    "admin_user": "",
    "admin_ts": 0,
    "admin_tab": "Deposits"
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --- ADMIN LOGIN ---
def admin_login():
    if st.session_state.admin_logged:
        if time.time() - st.session_state.admin_ts > SESSION_TIMEOUT:
            st.session_state.admin_logged = False
            st.warning("Session expired. Please log in again.")
            return False
        st.info(f"Admin logged in as {st.session_state.admin_user}")
        return True

    uname = st.text_input("Admin Username")
    pw = st.text_input("Admin Password", type="password")
    login_clicked = st.button("Login", key="admin_login_btn")

    if login_clicked:
        if uname in ADMIN_USERS and pw == ADMIN_PASSWORDS[uname]:
            st.session_state.admin_logged = True
            st.session_state.admin_user = uname
            st.session_state.admin_ts = time.time()
            st.success(f"Logged in as admin: {uname}")
            st.experimental_rerun()
            return
        else:
            st.error("Invalid credentials.")
    return False

def admin_required():
    if not st.session_state.admin_logged:
        st.warning("Admin login required.")
        return False
    if time.time() - st.session_state.admin_ts > SESSION_TIMEOUT:
        st.session_state.admin_logged = False
        st.warning("Session expired. Please log in again.")
        return False
    st.session_state.admin_ts = time.time()
    return True

# --- ADMIN LOGGING ---
def log_admin(action, details=""):
    try:
        db.collection("admin_logs").add({
            "timestamp": datetime.utcnow(),
            "admin_user": st.session_state.get("admin_user", "unknown"),
            "action": action,
            "details": details
        })
    except Exception as e:
        st.error(f"Logging failed: {e}")

def show_admin_logs(n=20):
    try:
        logs_ref = db.collection("admin_logs").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(n).stream()
        logs = [{
            "Timestamp": l.to_dict().get("timestamp"),
            "Admin": l.to_dict().get("admin_user"),
            "Action": l.to_dict().get("action"),
            "Details": l.to_dict().get("details"),
        } for l in logs_ref]
        if logs:
            df = pd.DataFrame(logs)
            st.dataframe(df)
        else:
            st.info("No admin logs yet.")
    except Exception as e:
        st.error(f"Could not load logs: {e}")

# --- ITEM SETTINGS ---
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
        log_admin("Edit Targets/Values", f"Targets: {targets}, Divines: {divines}, Bank Buy %: {bank_buy_pct}")
    except Exception as e:
        st.error(f"Error saving settings: {e}")

# --- USER SUGGESTION ---
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

# --- DEPOSITS ---
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

def add_deposit(user, item, qty, value, allow_duplicate=False):
    try:
        doc_ref = db.collection("users").document(user)
        doc_ref.set({}, merge=True)
        deposits_ref = doc_ref.collection("deposits")
        if not allow_duplicate:
            existing = deposits_ref.where("item", "==", item).where("qty", "==", qty).stream()
            for e in existing:
                return False
        dep = {
            "item": item,
            "qty": qty,
            "value": value,
            "timestamp": datetime.utcnow()
        }
        deposits_ref.add(dep)
        log_admin("Deposit", f"{user}: {qty}x {item} (Value: {value})")
        return True
    except Exception as e:
        st.error(f"Error adding deposit: {e}")
        return False

def delete_category(item_category):
    try:
        for item in ITEM_CATEGORIES[item_category]:
            docs = db.collection_group("deposits").where("item", "==", item).stream()
            for d in docs:
                ref = d.reference
                ref.delete()
        log_admin("Delete Category", f"Deleted all deposits for category {item_category}")
    except Exception as e:
        st.error(f"Error deleting category: {e}")

def delete_deposit_by_id(user, dep_id):
    try:
        db.collection("users").document(user).collection("deposits").document(dep_id).delete()
        log_admin("Delete Deposit", f"Deleted deposit {dep_id} for {user}")
    except Exception as e:
        st.error(f"Error deleting deposit: {e}")

# --- DUPLICATES ---
def add_pending_dupe(user, item, qty, value):
    try:
        db.collection("pending_dupes").add({
            "user": user,
            "item": item,
            "qty": qty,
            "value": value,
            "timestamp": datetime.utcnow(),
            "status": "pending"
        })
        log_admin("Duplicate Detected", f"{user}: {qty}x {item}")
    except Exception as e:
        st.error(f"Error adding pending dupe: {e}")

def get_pending_dupes():
    try:
        return [
            {**doc.to_dict(), "id": doc.id}
            for doc in db.collection("pending_dupes").where("status", "==", "pending").stream()
        ]
    except Exception:
        return []

def confirm_dupe(dupe_id):
    try:
        dupe_doc = db.collection("pending_dupes").document(dupe_id).get()
        if dupe_doc.exists:
            d = dupe_doc.to_dict()
            add_deposit(d["user"], d["item"], d["qty"], d["value"], allow_duplicate=True)
            db.collection("pending_dupes").document(dupe_id).update({"status": "approved"})
            log_admin("Dupe Approved", f"{d['user']}: {d['qty']}x {d['item']}")
    except Exception as e:
        st.error(f"Error confirming dupe: {e}")

def decline_dupe(dupe_id):
    try:
        dupe_doc = db.collection("pending_dupes").document(dupe_id).get()
        if dupe_doc.exists:
            d = dupe_doc.to_dict()
            db.collection("pending_dupes").document(dupe_id).update({"status": "declined"})
            log_admin("Dupe Declined", f"{d['user']}: {d['qty']}x {d['item']}")
    except Exception as e:
        st.error(f"Error declining dupe: {e}")

# --- ADMIN DEPOSIT TRACKING ---
def get_admin_deposit_totals():
    try:
        logs_ref = db.collection("admin_logs").where("action", "==", "Deposit").stream()
        data = []
        for l in logs_ref:
            d = l.to_dict()
            # Parse format "username: qtyx item (Value: X)"
            details = d.get("details", "")
            admin = d.get("admin_user", "")
            if ":" in details and "x" in details:
                name_part, rest = details.split(":", 1)
                name = name_part.strip()
                if "x" in rest and "(" in rest:
                    qty_item, _ = rest.split("(", 1)
                    if "x" in qty_item:
                        qty_str, item = qty_item.strip().split("x", 1)
                        try:
                            qty = int(qty_str.strip())
                            item = item.strip()
                            data.append({"admin": admin, "user": name, "item": item, "qty": qty})
                        except Exception:
                            continue
        return data
    except Exception:
        return []

def reset_admin_deposit_logs():
    try:
        # Only removes "Deposit" logs, not other admin actions
        logs = db.collection("admin_logs").where("action", "==", "Deposit").stream()
        for log in logs:
            log.reference.delete()
        st.success("Admin deposit logs have been reset!")
        log_admin("Reset Deposit Logs", "All Deposit logs reset")
    except Exception as e:
        st.error(f"Error resetting logs: {e}")

# --- PAGES ---
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
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(str))
    st.subheader("Deposit History")
    st.dataframe(df[["timestamp", "item", "qty", "value"]].sort_values("timestamp", ascending=False))

    targets, divines, bank_buy_pct = get_item_settings()
    st.subheader("Payout/Value Growth")
    df["current_value"] = [
        df.iloc[i]["qty"] * divines.get(df.iloc[i]["item"], 0.0)
        for i in range(len(df))
    ]
    st.metric("Total Current Value", f"{df['current_value'].sum():,.2f} Divines")

    # --- Totals per item for this user ---
    st.subheader("Totals per Item Deposited")
    totals = df.groupby("item")["qty"].sum().reset_index()
    st.dataframe(totals)

def what_if_calc():
    st.header("What-If Payout Calculator")
    targets, divines, _ = get_item_settings()
    item_qtys = {}
    col1, col2 = st.columns(2)
    for i, item in enumerate(ALL_ITEMS):
        col = col1 if i % 2 == 0 else col2
        item_qtys[item] = col.number_input(f"{item}", min_value=0, step=1, key=f"calc_{item}")
    if st.button("Estimate Payout"):
        total_value = 0
        st.write("**Estimated Basket:**")
        for item, qty in item_qtys.items():
            if qty > 0:
                value = qty * divines.get(item, 0.0)
                st.write(f"{item}: {qty} → Value: {value:.2f} Divines")
                total_value += value
        st.success(f"**Estimated payout:** {total_value:,.2f} Divines")

def faq_tab():
    st.header("FAQ / Help")
    st.markdown("""
    **Q: How do I see my wallet/deposits?**  
    Just type your username or IGN in the search bar!

    **Q: What if I use different names?**  
    Ask an admin to link your aliases! You'll see all deposits together.

    **Q: How is my payout calculated?**  
    Each deposit grows by the current divine value (set by admin).  
    You can check all item values in the sidebar (admin only).

    **Q: Who can add deposits?**  
    Only admins can add/edit deposits, but users can see all info.

    **Security:**  
    - No passwords required for users, just search.
    - Only admins can manage deposits.
    - All admin actions are logged.
    """)

# --- ADMIN PANEL SPLIT TABS ---
def admin_tools():
    st.title("Admin Tools")

    # --- LOGIN/LOGOUT ---
    if st.session_state.admin_logged:
        if st.button("Logout"):
            st.session_state.admin_logged = False
            st.session_state.admin_user = ""
            st.success("Logged out.")
            st.experimental_rerun()
            return
    else:
        if not admin_login():
            return
    if not admin_required():
        return

    admin_tabs = ["Deposits", "Settings", "Admin Deposit Totals"]
    st.session_state.admin_tab = st.radio("Admin Tabs", admin_tabs, key="admin_tabs")

    # --- SETTINGS TAB ---
    if st.session_state.admin_tab == "Settings":
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

        st.subheader("Delete All Deposits for Category")
        category_to_del = st.selectbox("Select Category to Delete", [""] + list(ITEM_CATEGORIES.keys()))
        if category_to_del:
            st.warning(f"Are you sure you want to delete **ALL** deposits in the category **{category_to_del}**? This cannot be undone.")
            if st.button(f"Delete ALL in '{category_to_del}'", key="del_category_btn"):
                delete_category(category_to_del)
                st.success(f"All deposits for '{category_to_del}' have been deleted!")
                st.experimental_rerun()
                return

        st.subheader("Delete Individual Deposits")
        all_users = get_all_usernames()
        user_for_del = st.selectbox("Select User to Delete Deposit From", [""] + all_users)
        if user_for_del:
            deps = get_deposits(user_for_del)
            if deps:
                df = pd.DataFrame(deps)
                df["timestamp"] = pd.to_datetime(df["timestamp"].astype(str))
                for idx, row in df.iterrows():
                    c = st.columns([3, 3, 2, 1])
                    c[0].write(row["timestamp"])
                    c[1].write(row["item"])
                    c[2].write(row["qty"])
                    if c[3].button("Delete", key=f"del_{row['id']}"):
                        delete_deposit_by_id(user_for_del, row["id"])
                        st.success(f"Deleted {row['qty']}x {row['item']} for {user_for_del}")
                        st.experimental_rerun()
                        return
            else:
                st.info("No deposits for that user.")

        st.subheader("Admin Action Logs")
        show_admin_logs(30)
        return

    # --- ADMIN DEPOSIT TOTALS TAB ---
    if st.session_state.admin_tab == "Admin Deposit Totals":
        st.header("Admin Deposit Totals (sum of deposits made by each admin)")
        data = get_admin_deposit_totals()
        if not data:
            st.info("No admin deposit logs found.")
        else:
            df_admin = pd.DataFrame(data)
            summary = df_admin.groupby(["admin", "item"])["qty"].sum().unstack(fill_value=0)
            st.dataframe(summary)

        st.subheader("Reset Admin Deposit Logs")
        if st.button("Reset Admin Deposit Logs (only admin deposits; cannot be undone)", key="reset_admin_deposits"):
            if st.confirm("Are you sure you want to reset all admin deposit logs?"):
                reset_admin_deposit_logs()
                st.experimental_rerun()
                return
        return

    # --- DEPOSITS TAB ---
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
    if submitted and user:
        for item, qty in item_qtys.items():
            if qty > 0:
                user_doc = db.collection("users").document(user)
                try:
                    deps = user_doc.collection("deposits").where("item", "==", item).where("qty", "==", qty).stream()
                    if any(deps):
                        add_pending_dupe(user, item, qty, divines.get(item, 0.0))
                        st.warning(f"Duplicate found for {user} - {qty}x {item}. Sent to admin confirmation!")
                    else:
                        add_deposit(user, item, qty, divines.get(item, 0.0))
                        st.success(f"Added: {user} - {qty}x {item}")
                except Exception as e:
                    st.error(f"Error checking existing deposits: {e}")

    st.subheader("Pending Duplicate Offers (Confirm/Decline)")
    pending_dupes = get_pending_dupes()
    if pending_dupes:
        for pd in pending_dupes:
            c = st.columns([2, 2, 2, 1, 1])
            c[0].write(pd["user"])
            c[1].write(pd["item"])
            c[2].write(pd["qty"])
            if c[3].button("Confirm", key=f"dupe_confirm_{pd['id']}"):
                confirm_dupe(pd["id"])
                st.success("Duplicate confirmed & added!")
                st.experimental_rerun()
                return
            if c[4].button("Decline", key=f"dupe_decline_{pd['id']}"):
                decline_dupe(pd["id"])
                st.info("Duplicate declined.")
                st.experimental_rerun()
                return
    else:
        st.info("No pending duplicates.")

# --- MAIN ROUTER ---
pages = ["🏦 User Dashboard", "🧮 What-If Calculator", "❓ FAQ/Help", "🔑 Admin Tools"]
page = st.sidebar.radio("Navigate", pages)

if page == "🏦 User Dashboard":
    user_dashboard()
elif page == "🧮 What-If Calculator":
    what_if_calc()
elif page == "❓ FAQ/Help":
    faq_tab()
elif page == "🔑 Admin Tools":
    admin_tools()
