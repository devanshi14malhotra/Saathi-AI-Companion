"""
Transactions Ledger & Refunds Microservice Explorer
Direct live inspection of core banking ledger records, merchant credit states,
and downstream refund processing records.
"""

import streamlit as st
import sys
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css, render_header
from streamlit_app.components.db_helper import (
    init_app_state,
    get_all_transactions,
    get_all_refunds,
    ledger_db,
    refunds_db,
)

st.set_page_config(page_title="Transactions & Ledger | Paytm Saathi", page_icon="💳", layout="wide")
inject_custom_css()
init_app_state()

render_header(
    title="Transactions Ledger & Refunds Service",
    subtitle="Live microservice data inspection: verify double debits, merchant credit states, and refund records",
    badge="Banking Ledger",
)

tab_txns, tab_refunds, tab_inject = st.tabs(["📊 Transactions Ledger", "💸 Active Refunds", "➕ New Banking Transaction Entry"])

with tab_txns:
    st.subheader("🏦 Live Core Banking Transactions (`ledger.db`)")
    txns = get_all_transactions(limit=100)

    if txns:
        import pandas as pd
        df = pd.DataFrame(txns)

        # Filters
        c_f1, c_f2, c_f3 = st.columns(3)
        with c_f1:
            status_filter = st.multiselect("Filter by Status:", df["status"].unique().tolist(), default=[])
        with c_f2:
            bank_filter = st.multiselect("Filter by Bank:", df["bank_code"].dropna().unique().tolist(), default=[])
        with c_f3:
            user_search = st.text_input("Search by User ID (e.g. P-101):")

        filtered = df.copy()
        if status_filter:
            filtered = filtered[filtered["status"].isin(status_filter)]
        if bank_filter:
            filtered = filtered[filtered["bank_code"].isin(bank_filter)]
        if user_search:
            filtered = filtered[filtered["user_id"].str.contains(user_search, case=False, na=False)]

        st.dataframe(
            filtered[[
                "id", "user_id", "amount", "counterparty", "status",
                "debit_status", "bank_debit_status", "credit_to_merchant", "bank_code", "created_at"
            ]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Txn ID", width="small"),
                "user_id": st.column_config.TextColumn("User ID", width="small"),
                "amount": st.column_config.NumberColumn("Amount (₹)", format="₹%d"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "debit_status": st.column_config.TextColumn("Debit Status", width="small"),
                "bank_debit_status": st.column_config.TextColumn("Bank Debit Status", width="small"),
                "credit_to_merchant": st.column_config.CheckboxColumn("Merchant Credited"),
                "bank_code": st.column_config.TextColumn("Bank", width="small"),
            },
        )
    else:
        st.info("No transactions found in ledger.")

with tab_refunds:
    st.subheader("💸 Real-Time Refund Records (`refunds.db`)")
    refunds = get_all_refunds(limit=100)

    if refunds:
        import pandas as pd
        df_rf = pd.DataFrame(refunds)
        st.dataframe(
            df_rf[["id", "txn_id", "user_id", "amount", "status", "reason", "initiated_at", "eta"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Refund ID", width="small"),
                "txn_id": st.column_config.TextColumn("Linked Txn", width="small"),
                "amount": st.column_config.NumberColumn("Refund Amount", format="₹%d"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "reason": st.column_config.TextColumn("Reason", width="medium"),
            },
        )
    else:
        st.info("No refunds currently registered in refunds.db.")

with tab_inject:
    st.subheader("💳 New Transaction Entry")
    st.write("Post an actual transaction to the ledger database.")

    with st.form("inject_form"):
        col_u, col_amt, col_bank = st.columns(3)
        with col_u:
            i_user = st.selectbox("Target Customer:", ["U-101", "U-102", "U-103", "U-104", "M-201"])
        with col_amt:
            i_amt = st.number_input("Amount (₹):", min_value=1, max_value=50000, value=750)
        with col_bank:
            i_bank = st.selectbox("Origin Bank:", ["HDFC", "SBI", "ICICI", "AXIS", "PAYTM_PAYMENTS_BANK"])

        col_cparty, col_status, col_debit = st.columns(3)
        with col_cparty:
            i_cparty = st.text_input("Counterparty / Merchant:", value="Zomato")
        with col_status:
            i_stat = st.selectbox("Transaction Status:", ["FAILED", "SUCCESS", "PENDING", "DEBITED_NOT_CREDITED"])
        with col_debit:
            i_debit = st.selectbox("User Debit Status:", ["DEBITED", "NOT_DEBITED", "REVERSED"])

        submit_inject = st.form_submit_button("Create Transaction in Ledger DB 💳", type="primary")

        if submit_inject:
            from app.core.ids import next_id
            from datetime import datetime, timezone

            new_txn_id = next_id("txn")
            now_str = datetime.now(timezone.utc).isoformat()
            ledger_db.execute(
                """
                INSERT INTO transactions(
                    id, user_id, amount, counterparty, status, debit_status,
                    bank_debit_status, credit_to_merchant, bank_code, rail, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'UPI', ?, ?)
                """,
                (new_txn_id, i_user, int(i_amt), i_cparty, i_stat, i_debit, i_debit, i_bank, now_str, now_str),
            )
            st.success(f"✅ Successfully created `{new_txn_id}` in ledger.db for customer `{i_user}`! You can now test resolving it in the Customer Helpdesk.")
            st.rerun()

