import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import time
from datetime import datetime, timedelta
import pandas as pd

# --- CONFIG ---
st.set_page_config(page_title="FundBank", layout="wide")

ADMIN_USERS = st.secrets.get("admin_users", ["Admin"])
ADMIN_PASS = st.secrets.get("admin_pw", "AdminPOEconomics")
SESSION_TIMEOUT = 20 * 60  # 20 min

# --- FIREBASE INIT ---
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase_json"]))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --- THEME SWITCH ---
if "theme" not in st.session_state:
    st.session_state["theme"] = "light"

def toggle_theme():
    st.session_state["theme"] = "dark" if st.session_state["theme"] == "light" else "light"

st.sidebar.button("🌞/🌙 Theme", on_click=toggle_theme)
st.markdown(
    f"<style>body {{background: {'#222' if st.session_state['theme']=='dark' else '#fff'}; color: {'#eee' if st.session_state['theme']=='dark' else '#222'};}}</style>",
    unsafe_allow_html=True,
)

# --- PAGE NAV ---
pages = ["🏦 User Dashboard", "🧮 What-If Calculator", "❓ FAQ/Help", "🔑 Admin Tools"]
page = st.sidebar.radio("Navigate", pages)

# --- HELPERS ---
def log_admin_action(admin_user, action, details=""):
    db.collection("admin_logs").add({
        "timestamp": datetime.now(),
        "admin": admin_user,
        "action": action,
        "details": details
    })

def get_all_usernames():
    users_ref = db.collection("users").stream()
    names = set()
    for u in users_ref:
        d = u.to_dict()
        names.add(u.id)
        if "aliases" in d:
            for a in d["aliases"]:
                names.add(a)
    return sorted(list(names))

def get_user_from_name(name):
    user_ref = db.collection("users").document(name).get()
    if user_ref.exists:
        return user_ref.id, user_ref.to_dict()
    else:
        users = db.collection("users").where("aliases", "array_contains", name).stream()
        for u in users:
            return u.id, u.to_dict()
    return None, None

# --- USER DASHBOARD ---
def user_dashboard(username):
    user_id, user = get_user_from_name(username)
    if not user:
        st.warning("No deposits found for this user or alias.")
        return

    st.header(f"User Dashboard: {username}")
    st.write(f"**All deposits and payout growth for:** `{user_id}`")
    deposits_ref = db.collection("users").document(user_id).collection("deposits").order_by("timestamp").stream()
    deposits = []
    for d in deposits_ref:
        rec = d.to_dict()
        rec["id"] = d.id
        rec["timestamp"] = rec.get("timestamp", datetime.now())
        deposits.append(rec)

    if not deposits:
        st.info("No deposits yet.")
        return

    df = pd.DataFrame(deposits)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(str))
    st.subheader("Deposit History")
    st.dataframe(df[["timestamp", "item", "qty", "value"]].sort_values("timestamp", ascending=False))

    st.subheader("Payout/Value Growth")
    growth = user.get("growth", 1.01)
    df["current_value"] = df["value"] * (growth ** ((datetime.now() - df["timestamp"]).dt.days))
    st.write(f"**Growth Rate:** {growth:.3f}x per day")
    st.metric("Total Current Value", f"{df['current_value'].sum():,.2f}")
    st.write("You can share this page by sending the link above! 👆")

# --- WHAT-IF CALCULATOR ---
def what_if_calc():
    st.header("What-If Payout Calculator")
    items = st.text_area("Items & Quantities (e.g. T16 Map x10, Breachstone x5):")
    growth = st.number_input("Current Daily Growth Rate (%)", value=1.0, min_value=0.0, max_value=100.0)
    days = st.number_input("Growth Days", value=7, min_value=1, max_value=365)
    if st.button("Estimate Payout"):
        lines = [x.strip() for x in items.split(",") if x.strip()]
        total_value = 0
        st.write("**Estimated Basket:**")
        for line in lines:
            if "x" in line:
                item, qty = line.rsplit("x", 1)
                item = item.strip()
                qty = int(qty.strip())
            else:
                item, qty = line, 1
            value = qty * 10
            st.write(f"{item}: {qty} → Value: {value}")
            total_value += value
        final_value = total_value * ((1 + growth/100) ** days)
        st.success(f"**Estimated payout after {days} days:** {final_value:,.2f}")

# --- FAQ ---
def faq_tab():
    st.header("FAQ / Help")
    st.markdown("""
    **Q: How do I see my wallet/deposits?**  
    Just type your username or IGN in the search bar!

    **Q: What if I use different names?**  
    Ask an admin to link your aliases! You'll see all deposits together.

    **Q: How is my payout calculated?**  
    Each deposit grows by the current daily % set by admins.

    **Q: Can I withdraw my items?**  
    Not yet—withdrawals coming soon!

    **Q: I found a bug/want to suggest something!**  
    Contact the admin or open an issue on our GitHub.

    **Security:**  
    - No passwords required for users, just search.  
    - Only admins can manage deposits.
    """)

# --- ADMIN TOOLS ---
def admin_tools():
    st.header("Admin Tools")

    if "admin_logged" not in st.session_state:
        username = st.text_input("Admin Username")
        pw = st.text_input("Admin Password", type="password")
        if st.button("Login"):
            if username in ADMIN_USERS and pw == ADMIN_PASS:
                st.session_state.admin_logged = True
                st.session_state.admin_user = username
                st.session_state.admin_ts = time.time()
                st.success(f"Admin logged in as {username}.")
                log_admin_action(username, "Login")
            else:
                st.error("Invalid username or password.")
        return

    if time.time() - st.session_state.get("admin_ts", 0) > SESSION_TIMEOUT:
        st.warning("Admin session timed out. Please log in again.")
        del st.session_state.admin_logged
        return

    admin_user = st.session_state.admin_user
    st.write(f"Welcome, **{admin_user}** (session active)")

    st.subheader("Add Deposit (with Duplicate Check)")
    uname = st.text_input("Username")
    item = st.text_input("Item")
    qty = st.number_input("Qty", 1)
    value = st.number_input("Value", 0.0)

    if st.button("Add Deposit"):
        if not uname.strip():
            st.error("Username cannot be empty.")
            return
        if qty <= 0:
            st.error("Quantity must be positive.")
            return

        try:
            deposits = db.collection("users").document(uname).collection("deposits")
            dupes = deposits.where("item", "==", item).where("qty", "==", qty).stream()
            found = any(True for _ in dupes)
            if found:
                db.collection("pending_duplicates").add({
                    "user": uname,
                    "item": item,
                    "qty": qty,
                    "value": value,
                    "timestamp": datetime.now(),
                    "submitted_by": admin_user
                })
                st.warning("Duplicate detected! Sent to pending duplicates.")
                log_admin_action(admin_user, "Flagged Duplicate", f"{uname} - {item} ({qty})")
            else:
                deposits.add({
                    "item": item,
                    "qty": int(qty),
                    "value": float(value),
                    "timestamp": datetime.now()
                })
                st.success("Deposit added.")
                log_admin_action(admin_user, "Add Deposit", f"{uname} - {item} ({qty})")
        except Exception as e:
            st.error(f"Error adding deposit: {e}")

    st.subheader("Pending Duplicates")
    try:
        pending_ref = db.collection("pending_duplicates").stream()
        for p in pending_ref:
            d = p.to_dict()
            col1, col2, col3 = st.columns(3)
            col1.write(f"{d['user']} - {d['item']} x{d['qty']}")
            if col2.button("Approve", key=f"approve_{p.id}"):
                db.collection("users").document(d['user']).collection("deposits").add({
                    "item": d['item'],
                    "qty": int(d['qty']),
                    "value": float(d['value']),
                    "timestamp": datetime.now()
                })
                db.collection("pending_duplicates").document(p.id).delete()
                st.success(f"Approved and added: {d['user']} - {d['item']}")
                log_admin_action(admin_user, "Approved Duplicate", f"{d['user']} - {d['item']} ({d['qty']})")
                st.experimental_rerun()
            if col3.button("Decline", key=f"decline_{p.id}"):
                db.collection("pending_duplicates").document(p.id).delete()
                st.info(f"Declined: {d['user']} - {d['item']}")
                log_admin_action(admin_user, "Declined Duplicate", f"{d['user']} - {d['item']} ({d['qty']})")
                st.experimental_rerun()
    except Exception as e:
        st.error(f"Error loading pending duplicates: {e}")

    st.subheader("Admin Logs (Last 20 Actions)")
    try:
        logs = db.collection("admin_logs").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(20).stream()
        for log in logs:
            l = log.to_dict()
            st.write(f"[{l['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] **{l['admin']}** → {l['action']} → {l.get('details', '')}")
    except Exception as e:
        st.error(f"Error loading logs: {e}")

# --- PAGE ROUTING ---
if page == pages[0]:
    st.title("FundBank: Public Wallet Lookup")
    all_names = get_all_usernames()
    q = st.text_input("Search Username or Alias", "", key="search")
    suggestions = [n for n in all_names if q.lower() in n.lower()][:10] if q else []
    if suggestions:
        st.write("Suggestions: " + ", ".join(suggestions))
    selected_user = st.selectbox("Select from suggestions", [""] + suggestions) if suggestions else ""
    show_user = selected_user if selected_user else q
    if show_user:
        user_dashboard(show_user)

elif page == pages[1]:
    what_if_calc()
elif page == pages[2]:
    faq_tab()
elif page == pages[3]:
    admin_tools()
