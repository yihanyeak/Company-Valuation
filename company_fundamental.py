import streamlit as st
from textwrap import dedent
from html import escape


class CompanyFundamental:
    """
    Handles the fundamental analysis guidelines, user settings,
    and the visual cards shown for each metric.
    """

    KEY_PREFIX = "fs_v2"

    # Default guideline definitions
    GUIDELINES = [
        {"name": "Revenue",                      "operator": ">", "number": 8.0,  "symbol": "%", "metric": ""},
        {"name": "Gross Margin",                 "operator": ">", "number": 60.0, "symbol": "%", "metric": ""},
        {"name": "Interest Coverage",            "operator": ">", "number": 3.0,  "symbol": "x", "metric": ""},
        {"name": "Net Income",                   "operator": ">", "number": 10.0, "symbol": "%", "metric": ""},
        {"name": "Shares Outstanding",           "operator": "<", "number": 0.0,  "symbol": "%", "metric": ""},
        {"name": "Cash & Short Term Investments","operator": ">", "number": 3.0,  "symbol": "x", "metric": "Total Debt"},
        {"name": "Long Term Debt",               "operator": ">", "number": 3.0,  "symbol": "x", "metric": "FCF"},
        {"name": "Retained Earnings",            "operator": ">", "number": 5.0,  "symbol": "%", "metric": "Net Income"},
        {"name": "Stock Based Compensation",     "operator": ">", "number": 5.0,  "symbol": "%", "metric": "Revenue"},
        {"name": "Free Cash Flow",               "operator": ">", "number": 5.0,  "symbol": "%", "metric": ""},
        {"name": "Return on Invested Capital",   "operator": ">", "number": 60.0, "symbol": "%", "metric": ""},
        {"name": "PE ratio",                     "operator": "<", "number": 25.0, "symbol": "",  "metric": ""},
    ]

    OPERATORS = [">", "<"]
    SYMBOLS = ["%", "x", ""]
    REFERENCE_METRICS = ["", "Total Debt", "FCF", "Net Income", "Revenue"]

    # ──────────────────────────────────────────
    # Session-state initialization
    # ──────────────────────────────────────────
    @classmethod
    def initialize(cls):
        """Create default session-state values for all guidelines (runs once)."""
        st.session_state.setdefault("rating_sensitivity", 0.2)
        prefix = cls.KEY_PREFIX

        for i, spec in enumerate(cls.GUIDELINES):
            st.session_state.setdefault(f"{prefix}_op_{i}",  spec["operator"])
            st.session_state.setdefault(f"{prefix}_num_{i}", spec["number"])
            st.session_state.setdefault(f"{prefix}_sym_{i}", spec["symbol"])
            st.session_state.setdefault(f"{prefix}_met_{i}", spec["metric"])
            st.session_state.setdefault(f"{prefix}_rel_{i}", 5)

    # ──────────────────────────────────────────
    # Global settings (affects whole calculation)
    # ──────────────────────────────────────────
    @classmethod
    def render_global_settings(cls):
        return st.slider(
            "Rating Sensitivity",
            min_value=0.0, max_value=1.0, step=0.05,
            key="rating_sensitivity",
        )

    # ──────────────────────────────────────────
    # Guideline helpers (single source of truth)
    # ──────────────────────────────────────────
    @classmethod
    def _build_guideline(cls, idx: int) -> str:
        """Build the human-readable guideline string for a metric."""
        prefix = cls.KEY_PREFIX
        op     = st.session_state[f"{prefix}_op_{idx}"]
        num    = st.session_state[f"{prefix}_num_{idx}"]
        sym    = st.session_state[f"{prefix}_sym_{idx}"]
        metric = st.session_state[f"{prefix}_met_{idx}"]

        text = f"{op}{num:g}{sym}"
        if metric:
            text += f" {metric}"
        return text

    @classmethod
    def get_guideline_display(cls, idx: int) -> str:
        return cls._build_guideline(idx)

    @classmethod
    def get_guidelines(cls):
        """Return two lists: guideline strings + their relevance scores."""
        values, relevances = [], []
        prefix = cls.KEY_PREFIX

        for i in range(len(cls.GUIDELINES)):
            values.append(cls._build_guideline(i))
            relevances.append(st.session_state[f"{prefix}_rel_{i}"])

        return values, relevances

    # ──────────────────────────────────────────
    # Per-metric editor (inside expander)
    # ──────────────────────────────────────────
    @classmethod
    def render_metric_editor(cls, idx: int):
        # Inject custom CSS to fix dropdown overflow/sizing and streamline inputs
        st.markdown("""
            <style>
                /* Fix selectbox dropdown menu overlapping adjacent columns */
                div[data-baseweb="select"] > div {
                    min-height: 38px;
                }
                /* Prevent dropdown menus from clipping or covering text */
                .stSelectbox div[data-baseweb="popover"] {
                    width: auto !important;
                }
            </style>
        """, unsafe_allow_html=True)

        prefix = cls.KEY_PREFIX
        op_key  = f"{prefix}_op_{idx}"
        num_key = f"{prefix}_num_{idx}"
        sym_key = f"{prefix}_sym_{idx}"
        met_key = f"{prefix}_met_{idx}"
        rel_key = f"{prefix}_rel_{idx}"

        # Slightly rebalanced column weights to give breathing room and prevent overlap
        c1, c2, c3, c4 = st.columns([0.9, 1.8, 1.0, 1.8], gap="small")

        with c1:
            st.selectbox("Operator", cls.OPERATORS, key=op_key,
                        label_visibility="collapsed", help="Guideline comparison operator")
        with c2:
            st.number_input("Threshold", step=0.5, key=num_key,
                            label_visibility="collapsed", help="Guideline threshold")
        with c3:
            st.selectbox("Unit", cls.SYMBOLS, key=sym_key,
                        format_func=lambda x: x if x else "-",
                        label_visibility="collapsed", help="Percentage or multiplier")
        with c4:
            st.selectbox("Reference", cls.REFERENCE_METRICS, key=met_key,
                        format_func=lambda x: x if x else "None",
                        label_visibility="collapsed", help="Reference metric")

        st.slider("Relevance", min_value=1, max_value=10, key=rel_key,
                help="Controls how strongly recent observations are weighted")

    # ──────────────────────────────────────────
    # Metric card header (name + rating badge)
    # ──────────────────────────────────────────
    @classmethod
    def render_metric_header(cls, idx: int, name: str, rating: str):
        rating = str(rating).strip().title()

        styles = {
            "Good":    ("#123B32", "#245B4B", "#34D399"),
            "Watch":   ("#493817", "#79602D", "#FBBF24"),
            "Concern": ("#492527", "#794347", "#F87171"),
        }
        bg, border, color = styles.get(rating, ("#303030", "#555555", "#FFFFFF"))

        st.html(dedent(f"""
            <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:8px">
                <span style="font-size:13px;font-weight:600">{idx + 1:02d}. {escape(str(name))}</span>
                <span style="
                    background-color:{bg};border:1px solid {border};color:{color};
                    padding:3px 8px;border-radius:5px;font-size:10px;font-weight:600;white-space:nowrap
                ">{escape(rating)}</span>
            </div>
        """))