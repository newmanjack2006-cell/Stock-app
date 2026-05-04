import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Stock Dashboard", layout="wide")

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(180deg, #08121f 0%, #0d1726 45%, #08121f 100%);
        color: #e6edf7;
    }
    h1, h2, h3, h4, h5, h6, p, div, span, label {
        color: #e6edf7 !important;
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f1a2b 0%, #101f33 100%);
        border-right: 1px solid rgba(255,255,255,0.08);
    }
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    .stMetric {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        padding: 16px;
        border-radius: 16px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.18);
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background: rgba(255,255,255,0.04);
        border-radius: 12px 12px 0 0;
        padding: 10px 16px;
        color: #c7d4e5;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(90deg, #22c55e 0%, #0ea5e9 100%);
        color: white !important;
    }
    div[data-testid="stDataFrame"] {
        background: rgba(255,255,255,0.03);
        border-radius: 14px;
        padding: 8px;
    }
</style>
""", unsafe_allow_html=True)

INDUSTRY_PE = {
    "Technology": 28.0,
    "Healthcare": 22.0,
    "Financial Services": 11.0,
    "Financial": 11.0,
    "Consumer Cyclical": 24.0,
    "Consumer Defensive": 20.0,
    "Industrials": 19.0,
    "Communication Services": 22.0,
    "Energy": 13.0,
    "Basic Materials": 16.0,
    "Real Estate": 18.0,
    "Utilities": 17.0,
}

st.title("Stock Search Dashboard")
st.caption("Search stocks, compare valuation, review analyst targets, and inspect leadership.")

with st.sidebar:
    st.header("Search")
    ticker_symbol = st.text_input("Stock ticker", value="AAPL").strip().upper()
    show_raw = st.checkbox("Show raw data", value=False)
    show_full_financials = st.checkbox("Show full financial statements", value=False)


def format_num(x, digits=2):
    try:
        return f"{x:.{digits}f}"
    except Exception:
        return "N/A"

@st.cache_data(ttl=3600)
def load_data(ticker):
    stock = yf.Ticker(ticker)
    info = stock.info or {}
    hist = stock.history(period="1y")
    recs = getattr(stock, "recommendations", None)
    if recs is None:
        recs = pd.DataFrame()
    qfin = getattr(stock, "quarterly_financials", None)
    afin = getattr(stock, "financials", None)
    qbs = getattr(stock, "quarterly_balance_sheet", None)
    return info, hist, recs, qfin, afin, qbs


def pick_leader(officers):
    if not isinstance(officers, list) or not officers:
        return None, None
    ordered = sorted(officers, key=lambda x: x.get("totalPay", 0) or 0, reverse=True)
    ceo = next((o for o in ordered if "chief executive" in str(o.get("title", "")).lower() or str(o.get("title", "")).upper() == "CEO"), None)
    if ceo is None:
        ceo = ordered[0]
    return ceo.get("name"), ceo.get("title")

if ticker_symbol:
    try:
        info, hist, recs, qfin, afin, qbs = load_data(ticker_symbol)

        company_name = info.get("longName") or ticker_symbol
        summary = info.get("longBusinessSummary") or "No company summary available."
        current_price = info.get("currentPrice")
        target_mean = info.get("targetMeanPrice")
        rec_mean = info.get("recommendationMean")
        analyst_count = info.get("numberOfAnalystOpinions")
        trailing_pe = info.get("trailingPE")
        forward_pe = info.get("forwardPE")
        industry = info.get("industry")
        sector = info.get("sector")
        industry_pe = INDUSTRY_PE.get(industry) or INDUSTRY_PE.get(sector)
        ceo_name, ceo_title = pick_leader(info.get("companyOfficers") or [])

        upside = None
        if isinstance(current_price, (int, float)) and isinstance(target_mean, (int, float)) and current_price:
            upside = (target_mean / current_price - 1) * 100

        valuation_flag = "N/A"
        valuation_delta = None
        if isinstance(trailing_pe, (int, float)) and isinstance(industry_pe, (int, float)) and industry_pe:
            valuation_delta = (trailing_pe / industry_pe - 1) * 100
            if valuation_delta < -10:
                valuation_flag = "Below industry"
            elif valuation_delta > 10:
                valuation_flag = "Above industry"
            else:
                valuation_flag = "In line"

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Current Price", f"${current_price:.2f}" if isinstance(current_price, (int, float)) else "N/A")
        k2.metric("Mean Target", f"${target_mean:.2f}" if isinstance(target_mean, (int, float)) else "N/A")
        k3.metric("Consensus Score", format_num(rec_mean) if isinstance(rec_mean, (int, float)) else "N/A")
        k4.metric("Analyst Count", f"{int(analyst_count)}" if isinstance(analyst_count, (int, float)) else "N/A")

        tabs = st.tabs(["Overview", "Valuation", "Financials", "Leadership"])

        with tabs[0]:
            left, right = st.columns(2)
            with left:
                st.subheader(company_name)
                st.write(summary)
                if industry:
                    st.caption(f"Industry: {industry}")
                if sector:
                    st.caption(f"Sector: {sector}")
                if upside is not None:
                    st.success(f"Implied upside from target price: {upside:.1f}%")
                if isinstance(rec_mean, (int, float)):
                    st.write(f"Analyst consensus score: {rec_mean:.2f}")
            with right:
                st.subheader("Price History")
                if not hist.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"], name="Close", line=dict(color="#38bdf8", width=2)))
                    if isinstance(target_mean, (int, float)):
                        fig.add_hline(y=target_mean, line_dash="dash", line_color="#22c55e")
                    fig.update_layout(height=420, margin=dict(l=20, r=20, t=30, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e6edf7"))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No price history available.")

        with tabs[1]:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Trailing P/E", format_num(trailing_pe) if isinstance(trailing_pe, (int, float)) else "N/A")
            c2.metric("Forward P/E", format_num(forward_pe) if isinstance(forward_pe, (int, float)) else "N/A")
            c3.metric("Industry Avg P/E", format_num(industry_pe) if isinstance(industry_pe, (int, float)) else "N/A")
            c4.metric("Vs Industry", f"{valuation_delta:+.1f}%" if valuation_delta is not None else "N/A")

            if valuation_flag != "N/A":
                st.success(f"Valuation view: {valuation_flag}")
            else:
                st.info("No industry average available for this stock.")

            pe_table = pd.DataFrame({
                "Metric": ["Current Price", "Trailing P/E", "Forward P/E", "Industry Avg P/E", "Vs Industry", "Valuation View"],
                "Value": [current_price, trailing_pe, forward_pe, industry_pe, f"{valuation_delta:+.1f}%" if valuation_delta is not None else "N/A", valuation_flag],
            })
            st.dataframe(pe_table, use_container_width=True, hide_index=True)

        with tabs[2]:
            st.subheader("Analyst / Consensus")
            consensus_df = pd.DataFrame({
                "Metric": ["Current Price", "Mean Target", "Consensus Score", "Analyst Opinions", "Implied Upside"],
                "Value": [current_price, target_mean, rec_mean, analyst_count, f"{upside:.1f}%" if upside is not None else "N/A"],
            })
            st.dataframe(consensus_df, use_container_width=True, hide_index=True)

            st.subheader("Quarterly Financials")
            if isinstance(qfin, pd.DataFrame) and not qfin.empty:
                st.dataframe(qfin if show_full_financials else qfin.head(), use_container_width=True)
            elif isinstance(afin, pd.DataFrame) and not afin.empty:
                st.dataframe(afin if show_full_financials else afin.head(), use_container_width=True)
            else:
                st.info("No financials available for this ticker.")

            st.subheader("Quarterly Balance Sheet")
            if isinstance(qbs, pd.DataFrame) and not qbs.empty:
                st.dataframe(qbs if show_full_financials else qbs.head(), use_container_width=True)
            else:
                st.info("No balance sheet data available.")

        with tabs[3]:
            leader_text = f"{ceo_name} â€” {ceo_title}" if ceo_name and ceo_title else (ceo_name or ceo_title or "No senior leader data available.")
            st.write(f"**Leader:** {leader_text}")
            st.write(summary)
            st.subheader("Raw leadership / company data")
            officers = info.get("companyOfficers") or []
            if officers:
                officers_df = pd.DataFrame(officers)
                cols = [c for c in ["name", "title", "totalPay", "fiscalYear", "age"] if c in officers_df.columns]
                st.dataframe(officers_df[cols] if cols else officers_df, use_container_width=True, hide_index=True)
            else:
                st.info("No officer data available.")

        if show_raw:
            st.subheader("Raw Info")
            filtered = {k: v for k, v in info.items() if any(x in k.lower() for x in ["target", "recommend", "earn", "rev", "profit", "pe", "industry", "sector", "officer", "summary"])}
            st.json(filtered)

    except Exception as e:
        st.error(f"Could not load data for {ticker_symbol}: {e}")
