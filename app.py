import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
import hashlib
import datetime

# ===== FIREBASE INIT WITH SECRETS (SAFE METHOD) =====
if not firebase_admin._apps:
    # Parse the JSON string from secrets and write it as valid JSON to file
    service_account_info = json.loads(st.secrets["firebase_json"])
    with open("firebase_key.json", "w") as f:
        json.dump(service_account_info, f)
    cred = credentials.Certificate("firebase_key.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ===== HELPER FUNCS =====
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def check_admin(username, password):
    doc = db.collection('users').document(username).get()
    if doc.exists:
        stored_hash = doc.to_dict().get('password')
        return hash_password(password) == stored_hash
    return False

def log_action(admin, action, details):
    db.collection('logs').add({
        'admin': admin,
        'action': action,
        'details': details,
        'timestamp': datetime.datetime.utcnow()
    })

# ===== CACHED FIRESTORE FETCHES =====
@st.cache_data(ttl=5)
def get_items():
    return [doc.to_dict() for doc in db.collection('items').stream()]

@st.cache_data(ttl=5)
def get_deposits():
    return [doc.to_dict() for doc in db.collection('deposits').stream()]

# ===== UI =====
st.set_page_config(page_title="PoE Bank App", layout="wide")
st.title("PoE Item Pool Banking App")

tab1, tab2, tab3 = st.tabs(["🏦 Pool Overview", "🔎 My Deposits", "🔑 Admin Panel"])

# ==== TAB 1: POOL OVERVIEW ====
with tab1:
    st.header("Pool Overview")
    items = get_items()
    deposits = get_deposits()
    item_deposits = {item['name']: 0 for item in items}
    for dep in deposits:
        item_deposits[dep['item']] = item_deposits.get(dep['item'], 0) + dep['amount']

    cols = st.columns(4)
    for i, item in enumerate(items):
        with cols[i % 4]:
            st.subheader(item['name'])
            target = item.get('target', 100)
            deposited = item_deposits.get(item['name'], 0)
            value = item.get('divine_value', 0)
            st.progress(min(deposited / target, 1.0))
            st.write(f"Deposited: **{deposited} / {target}**")
            st.write(f"Divine Value per Stack: {value:.2f}")

    st.markdown("---")
    st.header("Deposit Value Calculator")
    if items:
        calc_item = st.selectbox("Item", [item['name'] for item in items])
        calc_qty = st.number_input("Quantity", min_value=1, value=1)
        calc_item_info = next((i for i in items if i['name'] == calc_item), None)
        if calc_item_info:
            payout = (calc_qty / calc_item_info.get('target', 100)) * calc_item_info.get('divine_value', 0)
            st.success(f"Estimated payout: **{payout:.3f} Divines**")
    else:
        st.info("No items found. Admins need to add some items first.")

# ==== TAB 2: USER DEPOSIT SEARCH ====
with tab2:
    st.header("Check My Deposits")
    user_query = st.text_input("Enter your name (IGN/Discord):")
    if user_query:
        deposits = get_deposits()
        items = get_items()
        user_deposits = [d for d in deposits if d['user'].lower() == user_query.lower()]
        if user_deposits:
            df = pd.DataFrame(user_deposits)
            def payout_row(row):
                item = next((i for i in items if i['name'] == row['item']), None)
                if not item:
                    return 0
                return (row['amount'] / item.get('target', 100)) * item.get('divine_value', 0)
            df['estimated_payout'] = df.apply(payout_row, axis=1)
            st.dataframe(df[['item', 'amount', 'estimated_payout']])
            st.success(f"Total Estimated Payout: {df['estimated_payout'].sum():.3f} Divines")
        else:
            st.info("No deposits found for that name.")

# ==== TAB 3: ADMIN PANEL ====
with tab3:
    st.header("Admin Panel")
    if "admin_logged_in" not in st.session_state:
        st.session_state['admin_logged_in'] = False

    if not st.session_state['admin_logged_in']:
        with st.form("admin_login"):
            username = st.text_input("Admin Username")
            password = st.text_input("Password", type="password")
            login = st.form_submit_button("Login")
        if login and check_admin(username, password):
            st.session_state['admin_logged_in'] = True
            st.session_state['admin_user'] = username
            st.success("Logged in!")
        elif login:
            st.error("Invalid credentials")
    else:
        admin_user = st.session_state['admin_user']
        st.success(f"Logged in as: {admin_user}")

        # Add/Edit Deposit
        with st.expander("Add/Edit Deposit"):
            dep_user = st.text_input("User Name", key="add_dep_user")
            dep_item = st.selectbox("Item", [item['name'] for item in get_items()], key="add_dep_item")
            dep_amt = st.number_input("Amount", min_value=1, value=1, key="add_dep_amt")
            if st.button("Add Deposit"):
                db.collection('deposits').add({
                    'user': dep_user,
                    'item': dep_item,
                    'amount': dep_amt,
                    'timestamp': datetime.datetime.utcnow()
                })
                log_action(admin_user, "add_deposit", f"{dep_user} - {dep_item} x{dep_amt}")
                st.success("Deposit added!")

        # Edit Items/Targets/Values
        with st.expander("Edit Items & Divine Values"):
            items = get_items()
            for item in items:
                new_target = st.number_input(f"Target stack for {item['name']}", value=int(item.get('target', 100)), key=f"target_{item['name']}")
                new_value = st.number_input(f"Divine value for {item['name']}", value=float(item.get('divine_value', 0)), key=f"value_{item['name']}")
                if st.button(f"Update {item['name']}"):
                    db.collection('items').document(item['name']).update({
                        'target': new_target,
                        'divine_value': new_value
                    })
                    log_action(admin_user, "edit_item", f"{item['name']} to {new_target} {new_value}")
                    st.success(f"Updated {item['name']}.")

        # Delete Deposit
        with st.expander("Delete Deposit"):
            del_user = st.text_input("User to delete", key="del_user")
            del_item = st.selectbox("Item to delete", [item['name'] for item in get_items()], key="del_item")
            if st.button("Delete Deposit"):
                deps = db.collection('deposits').where('user', '==', del_user).where('item', '==', del_item).stream()
                count = 0
                for d in deps:
                    d.reference.delete()
                    count += 1
                log_action(admin_user, "delete_deposit", f"{del_user} - {del_item}")
                st.success(f"Deleted {count} deposit(s) for {del_user} - {del_item}.")

        # Export CSV
        with st.expander("Export Data"):
            if st.button("Download Deposits CSV"):
                df = pd.DataFrame(get_deposits())
                st.download_button("Download CSV", df.to_csv(index=False), file_name="deposits.csv", mime="text/csv")
            if st.button("Download Items CSV"):
                df2 = pd.DataFrame(get_items())
                st.download_button("Download Items CSV", df2.to_csv(index=False), file_name="items.csv", mime="text/csv")

        # Admin Logs
        with st.expander("Admin Logs"):
            logs = [doc.to_dict() for doc in db.collection('logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).stream()]
            if logs:
                df = pd.DataFrame(logs)
                st.dataframe(df)
            else:
                st.info("No logs yet.")

        if st.button("Logout"):
            st.session_state['admin_logged_in'] = False
            st.session_state['admin_user'] = ""
            st.success("Logged out!")

# ==== END ====
