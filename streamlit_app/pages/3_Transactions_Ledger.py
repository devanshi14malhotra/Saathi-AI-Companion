"""
Transactions Ledger & Refunds Explorer
Direct inspection of banking transactions, merchant settlements, and refund records.
"""

from datetime import datetime, timezone
import sys
from pathlib import Path
import pandas as pd
import streamlit as st

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css
from streamlit_app.components.ui import page_header, status_chip, id_chip
from streamlit_app.components.db_helper import (
    init_app_state,
    get_all_personas,
    get_all_transactions,
    get_all_refunds,
    ledger_db,
)
from app.core.ids import next_id

st.set_page_config(page_title="Transactions Ledger | Saathi", page_icon="💳", layout="wide")
inject_custom_css()
init_app_state()

page_header(
    title="Transactions ledger",
    subtitle="Direct inspection of core banking transactions, debit confirmations, and automated refunds",
)

tab_txns, tab_refunds, tab_entry = st.tabs(["Transactions", "Refunds", "New entry"])

with tab_txns:
    txns = get_all_transactions(limit=100)

    if txns:
        df = pd.DataFrame(txns)

        # Filter Row
        c_f1, c_f2, c_f3 = st.columns([1, 1, 1.5])
        with c_f1:
            all_statuses = sorted(df["status"].dropna().unique().tolist())
            stat_filter = st.multiselect("Status", all_statuses, default=[])
        with c_f2:
            all_banks = sorted(df["bank_code"].dropna().unique().tolist())
            bank_filter = st.multiselect("Bank", all_banks, default=[])
        with c_f3:
            search_query = st.text_input("Search customer or transaction ID", placeholder="e.g. U-101 or TXN-1001")

        filtered = df.copy()
        if stat_filter:
            filtered = filtered[filtered["status"].isin(stat_filter)]
        if bank_filter:
            filtered = filtered[filtered["bank_code"].isin(bank_filter)]
        if search_query:
            q = search_query.strip().lower()
            filtered = filtered[
                filtered["user_id"].str.lower().str.contains(q, na=False)
                | filtered["id"].str.lower().str.contains(q, na=False)
                | filtered["counterparty"].str.lower().str.contains(q, na=False)
            ]

        # Format amounts and columns
        show_cols = [
            "id", "user_id", "amount", "counterparty", "status",
            "debit_status", "bank_debit_status", "credit_to_merchant", "bank_code", "created_at"
        ]
        valid_cols = [c for c in show_cols if c in filtered.columns]

        st.dataframe(
            filtered[valid_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Transaction ID", width="small"),
                "user_id": st.column_config.TextColumn("Customer", width="small"),
                "amount": st.column_config.NumberColumn("Amount (₹)", format="₹%d"),
                "counterparty": st.column_config.TextColumn("Counterparty", width="medium"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "debit_status": st.column_config.TextColumn("Debit state", width="small"),
                "bank_debit_status": st.column_config.TextColumn("Bank debit", width="small"),
                "credit_to_merchant": st.column_config.CheckboxColumn("Merchant credited"),
                "bank_code": st.column_config.TextColumn("Bank", width="small"),
                "created_at": st.column_config.TextColumn("Created at", width="medium"),
            },
        )
    else:
        st.info("No transactions found in ledger.")

with tab_refunds:
    refunds = get_all_refunds(limit=100)
    if refunds:
        df_rf = pd.DataFrame(refunds)
        cols_rf = ["id", "txn_id", "user_id", "amount", "status", "reason", "initiated_at", "eta"]
        valid_rf = [c for c in cols_rf if c in df_rf.columns]

        st.dataframe(
            df_rf[valid_rf],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Refund ID", width="small"),
                "txn_id": st.column_config.TextColumn("Transaction", width="small"),
                "user_id": st.column_config.TextColumn("Customer", width="small"),
                "amount": st.column_config.NumberColumn("Amount (₹)", format="₹%d"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "reason": st.column_config.TextColumn("Reason", width="medium"),
                "initiated_at": st.column_config.TextColumn("Initiated at", width="medium"),
                "eta": st.column_config.TextColumn("ETA", width="small"),
            },
        )
    else:
        st.info("No refunds currently registered.")

with tab_entry:
    st.markdown("### Post new ledger transaction")
    st.write("Post an actual transaction to the ledger database to simulate real customer dispute scenarios.")

    # Populate options from real data
    personas = get_all_personas()
    customer_ids = [p["id"] for p in personas] if personas else ["U-101", "U-102", "U-103", "M-201"]

    bank_rows = ledger_db.query_all("SELECT DISTINCT bank_code FROM transactions WHERE bank_code IS NOT NULL AND bank_code != ''")
    bank_options = [r["bank_code"] for r in bank_rows] if bank_rows else ["HDFC", "SBI", "ICICI", "AXIS", "PAYTM_PAYMENTS_BANK"]

    stat_rows = ledger_db.query_all("SELECT DISTINCT status FROM transactions WHERE status IS NOT NULL")
    stat_options = [r["status"] for r in stat_rows] if stat_rows else ["FAILED", "SUCCESS", "PENDING", "DEBITED_NOT_CREDITED"]

    debit_rows = ledger_db.query_all("SELECT DISTINCT debit_status FROM transactions WHERE debit_status IS NOT NULL")
    debit_options = [r["debit_status"] for r in debit_rows] if debit_rows else ["DEBITED", "NOT_DEBITED", "REVERSED"]

    with st.form("new_entry_form"):
        col_u, col_amt, col_bank = st.columns(3)
        with col_u:
            i_user = st.selectbox("Customer", customer_ids, index=0)
        with col_amt:
            i_amt = st.number_input("Amount (₹)", min_value=1, max_value=50000, value=750, step=50)
        with col_bank:
            i_bank = st.selectbox("Origin bank", bank_options, index=0)

        col_cparty, col_status, col_debit = st.columns(3)
        with col_cparty:
            i_cparty = st.text_input("Counterparty or merchant", value="Zomato")
        with col_status:
            i_stat = st.selectbox("Transaction status", stat_options, index=0)
        with col_debit:
            i_debit = st.selectbox("Debit status", debit_options, index=0)

        submitted = st.form_submit_button("Post transaction", type="primary")

        if submitted:
            new_txn_id = next_id("txn")
            now_iso = datetime.now(timezone.utc).isoformat()
            ledger_db.execute(
                """
                INSERT INTO transactions(
                    id, user_id, amount, counterparty, status, debit_status,
                    bank_debit_status, credit_to_merchant, bank_code, rail, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'UPI', ?, ?)
                """,
                (new_txn_id, i_user, int(i_amt), i_cparty, i_stat, i_debit, i_debit, i_bank, now_iso, now_iso),
            )
            st.toast(f"Transaction {new_txn_id} posted for {i_user}.")
            st.rerun()
