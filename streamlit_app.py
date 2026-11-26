import pandas as pd
import streamlit as st
import st_yled
from html import escape

from streamlit_searchbox import st_searchbox
from company_fundamental import CompanyFundamental
from financial_statement import FinancialStatement
import utils


# ──────────────────────────────────────────────
# PAGE SETUP
# ──────────────────────────────────────────────
st.set_page_config(page_title="Stock Flow", layout="wide")
st_yled.init()


# ──────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────
# with st_yled.sticky_header(height="80px", background_color="#000000", padding="0 20px"):
#     _, center, _ = st.columns([1, 2, 1])
#     with center:
#         st.markdown("## Stock Flow")


# ──────────────────────────────────────────────
# 1. STOCK SEARCH
# ──────────────────────────────────────────────
selected_label = st_searchbox(
    utils.search_stocks,
    placeholder="Search Magnificent 7 (AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA)...",
    key="stock_search",
    clear_on_submit=False,
)

if selected_label:
    ticker, company_name = selected_label.split(" - ", 1)

    # ──────────────────────────────────────────────
    # 2. TIMEFRAME SELECTOR
    # ──────────────────────────────────────────────
    _, center, _ = st.columns([1, 2, 1])
    with center:
        selected_timeframe = st.segmented_control(
            "Timeframe",
            options=["MAX", "5Y", "2Y", "1Y", "6M", "3M"],
            default="1Y",
            label_visibility="collapsed",
            width="stretch",
        ) or "1Y"

    # ──────────────────────────────────────────────
    # 3. PRICE CHART
    # ──────────────────────────────────────────────
    price_df = utils.fetch_price_action(ticker)
    st.plotly_chart(
        utils.plot_price_chart(price_df, selected_timeframe),
        width="stretch",
        config={"displayModeBar": False, "scrollZoom": True},
    )

    # ──────────────────────────────────────────────
    # 4. COMPANY FUNDAMENTALS
    # ──────────────────────────────────────────────
    CompanyFundamental.initialize()
    st.subheader("Fundamental Results")
    rating_sensitivity = CompanyFundamental.render_global_settings()

    user_input_value, user_input_relevance = CompanyFundamental.get_guidelines()
    fundamentals_df = utils.cal_fundamentals(
        ticker, rating_sensitivity, user_input_value, user_input_relevance
    )

    # --- Metric cards (4 per row) ---
    for start in range(0, len(fundamentals_df), 4):
        cols = st.columns(4, gap="small")
        for i, col in enumerate(cols):
            idx = start + i
            if idx >= len(fundamentals_df):
                break

            row = fundamentals_df.iloc[idx]
            with col, st.container(border=True):
                CompanyFundamental.render_metric_header(idx, row["Name"], row["Rating"])

                guideline = CompanyFundamental.get_guideline_display(idx)
                st.html(f"""
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px 8px;margin:4px 0 10px 0">
                        <div>
                            <div style="color:#999;font-size:11px">YoY Growth</div>
                            <div style="font-size:16px;font-weight:600">{escape(str(row['YoY Growth']))}</div>
                        </div>
                        <div>
                            <div style="color:#999;font-size:11px">Current Year</div>
                            <div style="font-size:14px;font-weight:500">{escape(str(row['Current Year']))}</div>
                        </div>
                        <div>
                            <div style="color:#999;font-size:11px">Blended Growth</div>
                            <div style="font-size:14px;font-weight:600">{escape(str(row['Blended Growth']))}</div>
                            <div style="color:#999;font-size:11px">({escape(str(row['Blended Value']))})</div>
                        </div>
                    </div>
                    <div style="border-top:1px solid #333;padding-top:8px;margin-bottom:8px;color:#999;font-size:11px">
                        Guideline: <span style="color:#ddd;font-weight:600">{escape(guideline)}</span>
                    </div>
                """)

                with st.expander("Edit Guideline", expanded=False):
                    CompanyFundamental.render_metric_editor(idx)

    # ──────────────────────────────────────────────
    # 5. FINANCIAL STATEMENTS
    # ──────────────────────────────────────────────
    st.divider()
    st.subheader("Financial Statements")
    
    # 1. Fetch the dictionary of statements
    financial_statement = utils.fetch_financial_statement(ticker, price_df)
    
    # 2. Clean each individual DataFrame inside the dictionary
    cleaned_statements = {}
    if isinstance(financial_statement, dict):
        for key, df in financial_statement.items():
            if df is not None and not df.empty:
                cleaned_statements[key] = utils.clean_financial_value(df)
            else:
                cleaned_statements[key] = df
    else:
        # Fallback if it returns a single dataframe directly
        cleaned_statements = utils.clean_financial_value(financial_statement)

    # 3. Render the cleaned statements
    for stmt_name, df in cleaned_statements.items():
        if isinstance(df, pd.DataFrame):
            if df.index.has_duplicates:
                df = df[~df.index.duplicated(keep="first")]
            if df.columns.has_duplicates:
                df = df.loc[:, ~df.columns.duplicated(keep="first")]
            cleaned_statements[stmt_name] = df

    FinancialStatement.render(cleaned_statements)
