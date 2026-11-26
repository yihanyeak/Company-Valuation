import streamlit as st


class FinancialStatement:
    """
    Renders the three classic financial statements in tabs.
    Each tab shows a selectable number of years + TTM/latest columns.
    """

    STATEMENTS = {
        "Income Statement": "income_statement",
        "Balance Sheet":    "balance_sheet",
        "Cash Flow":        "cash_flow",
    }

    @classmethod
    def render(cls, financial_statement: dict):
        tabs = st.tabs(list(cls.STATEMENTS.keys()))

        for tab, (title, key) in zip(tabs, cls.STATEMENTS.items()):
            with tab:
                df = financial_statement.get(key)
                if df is None or df.empty:
                    st.info("No financial data available.")
                    continue
                cls.render_table(df, key)

    @staticmethod
    def render_table(df, key: str):
        df = df.copy()

        # Year columns in ascending order (oldest → newest)
        year_cols = sorted(
            [c for c in df.columns if str(c).isdigit()],
            key=lambda x: int(x),
            reverse=False,
        )
        special_cols = [c for c in ["TTM", "latest"] if c in df.columns]

        num_years = st.slider(
            "Number of years shown",
            min_value=1,
            max_value=len(year_cols),
            value=min(8, len(year_cols)),
            key=f"year_slider_{key}",
        )

        # Take the most recent N years so TTM stays on the left
        display_years = year_cols[-num_years:]
        display_cols = ["name"] + display_years + special_cols
        display_df = df[display_cols]

        numeric_cols = display_df.select_dtypes(include="number").columns

        styled = (
            display_df.style
            .format("{:,.2f}", subset=numeric_cols, na_rep="-")
            .set_properties(**{"text-align": "center"})
            .set_table_styles([{"selector": "th", "props": [("text-align", "center")]}])
        )

        st.dataframe(
            styled,
            width="stretch",
            hide_index=True,
            height=650,
            column_config={
                "name": st.column_config.TextColumn("Metric")
            },
        )