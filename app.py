import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import json
import time
from datetime import datetime, timedelta
import pandas as pd

# --- FIREBASE INIT ---
if 'firebase_init' not in st.session_state:
    cred = credentials.Certificate(json.loads(st.secrets["firebase_json"]))
    firebase_admin.initialize_app(cred)
    st.session_state.firebase_init = True

db = firestore.client()

# --- CONFIG ---
ADMIN_USER = "Admin"
ADMIN_PASS = st.secrets.get("admin_pw", "AdminPOEconomics")  # put this in your secrets!
SESSION_TIMEOUT = 20 * 60  # 20 min

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
st.set_page_config(page_title="FundBank", layout="wide")
pages = ["🏦 User Dashboard", "🧮 What-If Calculator", "❓ FAQ/Help", "🔑 Admin Tools"]
page = st.sidebar.radio("Navigate", pages)

# --- AUTOCOMPLETE SEARCH ---
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
    # Try exact username, then look up by alias
    user_ref = db.collection("users").document(name).get()
    if user_ref.exists:
        return user_ref.id, user_ref.to_dict()
    else:
        # Search by alias
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

    # Payout Calculation (simulate simple 1%/day growth for now)
    st.subheader("Payout/Value Growth")
    if "growth" in user:
        growth = user["growth"]
    else:
        growth = 1.01
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
            value = qty * 10  # Simulate item value for demo
            st.write(f"{item}: {qty} → Value: {value}")
            total_value += value
        final_value = total_value * ((1 + growth/100) ** days)
        st.success(f"**Estimated payout after {days} days:** {final_value:,.2f}")

# --- FAQ / HELP ---
def faq_tab():
    st.header("FAQ / Help")
    st.markdown("""
    **Q: How do I see my wallet/deposits?**  
    Just type your username or IGN in the search bar!

    **Q: What if I use different names?**  
    Ask an admin to link your aliases! You'll see all deposits together.

    **Q: How is my payout calculated?**  
    Each deposit grows by the current daily % set by admins. See details above.

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
    # Login
    if "admin_logged" not in st.session_state:
        pw = st.text_input("Admin password", type="password")
        if st.button("Login"):
            if pw == ADMIN_PASS:
                st.session_state.admin_logged = True
                st.session_state.admin_ts = time.time()
                st.success("Admin logged in.")
            else:
                st.error("Wrong password.")
        return
    # Session timeout
    if time.time() - st.session_state.get("admin_ts", 0) > SESSION_TIMEOUT:
        st.warning("Admin session timed out. Please log in again.")
        del st.session_state.admin_logged
        return
    st.write("Welcome, admin! (session active)")

    # Undo last admin action (simulate by storing last action in session)
    if "last_action" in st.session_state:
        if st.button("Undo Last Action"):
            act = st.session_state.pop("last_action")
            st.info(f"Undo simulated for: {act}")

    # Bulk upload
    st.subheader("Bulk Deposit Upload")
    uploaded = st.file_uploader("Upload CSV with columns: username, item, qty, value, timestamp", type="csv")
    if uploaded:
        df = pd.read_csv(uploaded)
        for i, row in df.iterrows():
            user_ref = db.collection("users").document(row['username'])
            user_ref.set({}, merge=True)
            dep = {
                "item": row["item"],
                "qty": int(row["qty"]),
                "value": float(row["value"]),
                "timestamp": row.get("timestamp", datetime.now())
            }
            db.collection("users").document(row['username']).collection("deposits").add(dep)
        st.success(f"Uploaded {len(df)} deposits!")
        st.session_state.last_action = "bulk_upload"

    # Manual add
    st.subheader("Add Single Deposit")
    uname = st.text_input("Username")
    item = st.text_input("Item")
    qty = st.number_input("Qty", 1)
    value = st.number_input("Value", 0.0)
    if st.button("Add Deposit"):
        dep = {
            "item": item,
            "qty": int(qty),
            "value": float(value),
            "timestamp": datetime.now()
        }
        db.collection("users").document(uname).set({}, merge=True)
        db.collection("users").document(uname).collection("deposits").add(dep)
        st.success("Deposit added.")
        st.session_state.last_action = "add_deposit"

    # Advanced export
    st.subheader("Export Deposits (CSV)")
    exp_user = st.text_input("Filter by user (optional)")
    exp_start = st.date_input("Start date", value=datetime.now() - timedelta(days=30))
    exp_end = st.date_input("End date", value=datetime.now())
    if st.button("Export"):
        users = [exp_user] if exp_user else get_all_usernames()
        all_deps = []
        for u in users:
            deps = db.collection("users").document(u).collection("deposits") \
                .where("timestamp", ">=", exp_start) \
                .where("timestamp", "<=", exp_end) \
                .stream()
            for d in deps:
                rec = d.to_dict()
                rec["username"] = u
                all_deps.append(rec)
        if all_deps:
            df = pd.DataFrame(all_deps)
            st.dataframe(df)
            st.download_button("Download CSV", df.to_csv(index=False), "deposits.csv")
        else:
            st.info("No records found in range.")

    # Link aliases
    st.subheader("Link Aliases")
    main_user = st.text_input("Main Username (to add alias to)")
    alias = st.text_input("Alias to link")
    if st.button("Link Alias"):
        ref = db.collection("users").document(main_user)
        doc = ref.get()
        if doc.exists:
            old = doc.to_dict().get("aliases", [])
            ref.set({"aliases": old + [alias]}, merge=True)
            st.success("Alias linked.")
        else:
            st.error("Main user not found.")

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
        st.markdown(f"🔗 **Shareable Link:** `/user/{show_user}` (feature: soon)")

elif page == pages[1]:
    what_if_calc()
elif page == pages[2]:
    faq_tab()
elif page == pages[3]:
    admin_tools()

# --- END ---
