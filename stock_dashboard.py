import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
import requests
import base64

st.set_page_config(page_title="Stock Dashboard", layout="wide")

st.markdown("""
<style>
.stApp { background: linear-gradient(180deg, #08121f 0%, #0d1726 45%, #08121f 100%); color: #e6edf7; }
h1,h2,h3,h4,h5,h6,p,div,span,label { color: #e6edf7 !important; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #0f1a2b 0%, #101f33 100%); border-right: 1px solid rgba(255,255,255,0.08); }
.block-container { padding-top: 2rem; padding-bottom: 2rem; }
.stMetric { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); padding: 16px; border-radius: 16px; }
.stTabs [data-baseweb="tab"] { background: rgba(255,255,255,0.04); border-radius: 12px 12px 0 0; padding: 10px 16px; color: #c7d4e5; }
.stTabs [aria-selected="true"] { background: linear-gradient(90deg, #22c55e 0%, #0ea5e9 100%); color: white !important; }
</style>
""", unsafe_allow_html=True)

st.title("Stock Search Dashboard")
st.caption("Search stocks, compare valuation, review analyst targets, inspect leadership, and view your Trading 212 portfolio.")

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

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
st.sidebar.header("Stock Analysis")
finnhub_key = st.sidebar.text_input("Finnhub API key (optional)", type="password")
ticker_raw  = st.sidebar.text_input("Stock ticker", value="AAPL").strip().upper()
show_raw    = st.sidebar.checkbox("Show raw data", value=False)
show_full   = st.sidebar.checkbox("Show full financial statements", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("DCF assumptions")
dcf_growth   = st.sidebar.slider("Revenue growth rate (%)", 0, 50, 10) / 100
dcf_margin   = st.sidebar.slider("Free cash flow margin (%)", 1, 50, 15) / 100
dcf_discount = st.sidebar.slider("Discount rate / WACC (%)", 1, 20, 10) / 100
dcf_terminal = st.sidebar.slider("Terminal growth rate (%)", 0, 5, 3) / 100
dcf_years    = st.sidebar.slider("Projection years", 5, 15, 10)

st.sidebar.markdown("---")
st.sidebar.subheader("Trading 212 Portfolio")
t212_api_key = st.sidebar.text_input("Trading 212 API Key", type="password")
t212_api_secret = st.sidebar.text_input(
    "Trading 212 API Secret",
    type="password",
    help="Shown only once when you generate the Trading 212 key pair."
)
t212_env  = st.sidebar.radio("Account environment", ["Live", "Demo"], horizontal=True)
t212_base = "https://live.trading212.com/api/v0" if t212_env == "Live" else "https://demo.trading212.com/api/v0"

# ── SESSION STATE ─────────────────────────────────────────────────────────────
if "jump_to_ticker" not in st.session_state:
    st.session_state["jump_to_ticker"] = None

active_ticker = st.session_state["jump_to_ticker"] or ticker_raw

# ── HELPERS ───────────────────────────────────────────────────────────────────
def fmt(x, d=2):
    try:
        return f"{x:.{d}f}"
    except Exception:
        return "NA"

def sn(x):
    try:
        v = float(x)
        return v if v == v else None
    except Exception:
        return None

def build_t212_headers(api_key, api_secret):
    credentials = f"{api_key}:{api_secret}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}

def t212_ticker_to_yf(t212_ticker):
    if not t212_ticker:
        return t212_ticker
    parts = t212_ticker.split("_")
    symbol = parts[0]
    suffix_map = {
        "UK": ".L", "GB": ".L",
        "DE": ".DE", "FR": ".PA", "NL": ".AS",
        "ES": ".MC", "IT": ".MI",
        "SE": ".ST", "DK": ".CO", "NO": ".OL", "FI": ".HE",
        "CH": ".SW",
        "AU": ".AX",
        "CA": ".TO",
        "HK": ".HK",
        "JP": ".T",
    }
    if len(parts) >= 2:
        return symbol + suffix_map.get(parts[1], "")
    return symbol

@st.cache_data(ttl=30)
def load_t212_portfolio(api_key, api_secret, base_url):
    out = {"summary": {}, "positions": [], "error": None}
    if not api_key or not api_secret:
        out["error"] = "Please enter both your Trading 212 API key and secret."
        return out

    headers = build_t212_headers(api_key, api_secret)

    try:
        r = requests.get(f"{base_url}/equity/account/summary", headers=headers, timeout=20)
        if r.status_code == 401:
            out["error"] = "401 Unauthorized — check your API key, secret, and Live/Demo environment."
            return out
        if r.status_code == 403:
            out["error"] = "403 Forbidden — API access may not be enabled for this account, or the account type is unsupported."
            return out
        r.raise_for_status()
        out["summary"] = r.json()
    except Exception as e:
        out["error"] = f"Could not load account summary: {e}"
        return out

    try:
        r2 = requests.get(f"{base_url}/equity/positions", headers=headers, timeout=20)
        if r2.status_code == 401:
            out["error"] = "401 Unauthorized on positions endpoint — credentials or environment mismatch."
            return out
        if r2.status_code == 403:
            out["error"] = "403 Forbidden on positions endpoint."
            return out
        r2.raise_for_status()
        out["positions"] = r2.json() if isinstance(r2.json(), list) else []
    except Exception as e:
        out["error"] = f"Could not load positions: {e}"

    return out

@st.cache_data(ttl=3600)
def load_yf(ticker):
    s = yf.Ticker(ticker)
    info = s.info or {}
    hist = s.history(period="1y")
    recs = getattr(s, "recommendations", None)
    qfin = getattr(s, "quarterly_financials", None)
    afin = getattr(s, "financials", None)
    qbs = getattr(s, "quarterly_balancesheet", None)
    cf = getattr(s, "cashflow", None)
    return info, hist, recs, qfin, afin, qbs, cf

@st.cache_data(ttl=3600)
def load_finnhub(ticker, api_key):
    out = {"targets": pd.DataFrame(), "recs": pd.DataFrame()}
    if not api_key:
        return out
    headers = {"X-Finnhub-Token": api_key}
    base = "https://finnhub.io/api/v1"
    try:
        q = requests.get(f"{base}/stock/price-target?symbol={ticker}", headers=headers, timeout=15).json()
        out["targets"] = pd.DataFrame([q]) if isinstance(q, dict) and q else pd.DataFrame()
    except Exception:
        pass
    try:
        q = requests.get(f"{base}/stock/recommendation?symbol={ticker}", headers=headers, timeout=15).json()
        out["recs"] = pd.DataFrame(q) if isinstance(q, list) else pd.DataFrame()
    except Exception:
        pass
    return out

def dcf_valuation(revenue, shares, growth, margin, discount, terminal, years):
    if not revenue or not shares or shares == 0 or discount <= terminal:
        return None
    fcfs = []
    rev = revenue
    for y in range(1, years + 1):
        rev = rev * (1 + growth)
        pv = (rev * margin) / ((1 + discount) ** y)
        fcfs.append(pv)
    terminal_pv = ((rev * margin * (1 + terminal)) / (discount - terminal)) / ((1 + discount) ** years)
    return round((sum(fcfs) + terminal_pv) / shares, 2)

def valuation_table(info, current_price, industry_pe, growth, margin, discount, terminal, years, cf_stmt):
    trailing_eps = sn(info.get("trailingEps"))
    forward_eps = sn(info.get("forwardEps"))
    trailing_pe = sn(info.get("trailingPE"))
    forward_pe = sn(info.get("forwardPE"))
    price_to_sales = sn(info.get("priceToSalesTrailing12Months"))
    price_to_book = sn(info.get("priceToBook"))
    ev_to_ebitda = sn(info.get("enterpriseToEbitda"))
    shares = sn(info.get("sharesOutstanding"))
    revenue = sn(info.get("totalRevenue"))
    book_value = sn(info.get("bookValue"))
    ebitda = sn(info.get("ebitda"))
    op_cf = sn(info.get("operatingCashflow"))
    earnings_growth = sn(info.get("earningsGrowth"))

    if op_cf is None and cf_stmt is not None and not cf_stmt.empty:
        for label in ["Operating Cash Flow", "Total Cash From Operating Activities"]:
            matches = [c for c in cf_stmt.index if label.lower() in str(c).lower()]
            if matches:
                try:
                    op_cf = float(cf_stmt.loc[matches[0]].iloc[0])
                    break
                except Exception:
                    pass

    rows, missed = [], []

    if forward_eps and industry_pe:
        rows.append({"Method": "P/E Ratio", "Inputs": f"Fwd EPS {forward_eps:.2f} x Ind P/E {industry_pe:.1f}", "Implied ($)": round(forward_eps * industry_pe, 2), "Basis": "Industry avg P/E"})
    else:
        missed.append("P/E Ratio — need forward EPS + industry P/E")

    if trailing_eps and forward_pe and earnings_growth is not None:
        g = max(min(earnings_growth, 1.0), -0.95)
        rows.append({"Method": "EPS Growth", "Inputs": f"EPS {trailing_eps:.2f}, g {g*100:.1f}%, Fwd P/E {forward_pe:.1f}", "Implied ($)": round(trailing_eps * (1 + g) * forward_pe, 2), "Basis": "1yr EPS growth"})
    else:
        missed.append("EPS Growth — need trailing EPS, forward P/E, earnings growth")

    if current_price and trailing_pe and forward_pe and forward_pe != 0:
        rows.append({"Method": "P/E Rerating", "Inputs": f"Price {current_price:.2f}, T.P/E {trailing_pe:.1f}, F.P/E {forward_pe:.1f}", "Implied ($)": round(current_price * trailing_pe / forward_pe, 2), "Basis": "Multiple rerating"})
    else:
        missed.append("P/E Rerating — need current price, trailing and forward P/E")

    if price_to_sales and revenue and shares and shares != 0:
        sps = revenue / shares
        rows.append({"Method": "P/S Multiple", "Inputs": f"Sales/sh {sps:.2f}, P/S {price_to_sales:.2f}", "Implied ($)": round(sps * price_to_sales, 2), "Basis": "Revenue multiple"})
    else:
        missed.append("P/S — need revenue, shares, P/S ratio")

    if price_to_book and book_value:
        rows.append({"Method": "P/B Multiple", "Inputs": f"Book/sh {book_value:.2f}, P/B {price_to_book:.2f}", "Implied ($)": round(book_value * price_to_book, 2), "Basis": "Book-value multiple"})
    else:
        missed.append("P/B — need book value and P/B ratio")

    if op_cf and shares and shares != 0 and current_price:
        cf_ps = op_cf / shares
        if cf_ps and cf_ps != 0:
            pcf = current_price / cf_ps
            rows.append({"Method": "P/CF Multiple", "Inputs": f"CF/sh {cf_ps:.2f}, P/CF {pcf:.2f}", "Implied ($)": round(cf_ps * pcf, 2), "Basis": "Operating CF multiple"})
    else:
        missed.append("P/CF — need operating cashflow + shares")

    if ev_to_ebitda and ebitda and shares and shares != 0:
        rows.append({"Method": "EV/EBITDA", "Inputs": f"EV/EBITDA {ev_to_ebitda:.2f}, EBITDA {ebitda/1e9:.2f}B", "Implied ($)": round((ev_to_ebitda * ebitda) / shares, 2), "Basis": "Enterprise value"})
    else:
        missed.append("EV/EBITDA — need EBITDA, EV/EBITDA, shares")

    dcf_price = dcf_valuation(revenue, shares, growth, margin, discount, terminal, years)
    if dcf_price is not None:
        rows.append({"Method": f"DCF ({years}yr)", "Inputs": f"Rev {revenue/1e9:.1f}B, g {growth*100:.0f}%, FCF {margin*100:.0f}%, WACC {discount*100:.0f}%", "Implied ($)": dcf_price, "Basis": "Discounted cash flow"})
    else:
        missed.append("DCF — need total revenue + shares outstanding")

    df = pd.DataFrame(rows)
    if not df.empty and current_price:
        df["Upside %"] = (((df["Implied ($)"] / current_price) - 1) * 100).round(1)
    return df, missed

def leader_name(officers):
    if not isinstance(officers, list) or not officers:
        return None, None
    ordered = sorted(officers, key=lambda x: x.get("totalPay", 0) or 0, reverse=True)
    ceo = next((o for o in ordered if "chief executive" in str(o.get("title", "")).lower()), None)
    if ceo is None:
        ceo = ordered[0]
    return ceo.get("name"), ceo.get("title")

# ── MAIN TABS ─────────────────────────────────────────────────────────────────
main_tabs = st.tabs(["📊 Stock Analysis", "💼 T212 Portfolio"])

# TAB 1
with main_tabs[0]:
    if st.session_state["jump_to_ticker"]:
        st.info(f"Showing analysis for **{active_ticker}** (jumped from Portfolio).")
        if st.button("← Back to manual search"):
            st.session_state["jump_to_ticker"] = None
            st.rerun()

    ticker = active_ticker
    if ticker:
        try:
            info, hist, recs, qfin, afin, qbs, cf = load_yf(ticker)
            finnhub_data = load_finnhub(ticker, finnhub_key)

            company = info.get("longName") or ticker
            summary = info.get("longBusinessSummary") or "No company summary available."
            current = sn(info.get("currentPrice"))
            target = sn(info.get("targetMeanPrice"))
            recmean = sn(info.get("recommendationMean"))
            analyst_count = info.get("numberOfAnalystOpinions")
            trailing_pe = sn(info.get("trailingPE"))
            forward_pe = sn(info.get("forwardPE"))
            industry = info.get("industry")
            sector = info.get("sector")
            industry_pe = INDUSTRY_PE.get(industry) or INDUSTRY_PE.get(sector)
            ceo_name, ceo_title = leader_name(info.get("companyOfficers") or [])

            upside = None
            if current and target and current != 0:
                upside = (target / current - 1) * 100

            valuation_delta = None
            valuation_flag = "NA"
            if trailing_pe and industry_pe and industry_pe != 0:
                valuation_delta = (trailing_pe / industry_pe - 1) * 100
                if valuation_delta < -10:
                    valuation_flag = "Below industry"
                elif valuation_delta > 10:
                    valuation_flag = "Above industry"
                else:
                    valuation_flag = "In line"

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Current Price", f"${current:.2f}" if current else "NA")
            c2.metric("Mean Analyst Target", f"${target:.2f}" if target else "NA")
            c3.metric("Consensus Score", fmt(recmean))
            c4.metric("Analyst Count", str(int(analyst_count)) if analyst_count else "NA")

            atabs = st.tabs(["Overview", "Valuation", "Consensus Targets", "Analyst History", "Financials", "Leadership"])

            with atabs[0]:
                left, right = st.columns(2)
                with left:
                    st.subheader(company)
                    st.write(summary)
                    if industry:
                        st.caption(f"Industry: {industry}")
                    if sector:
                        st.caption(f"Sector: {sector}")
                    if upside is not None:
                        st.success(f"Implied upside from analyst mean target: {upside:.1f}%")
                    if recmean:
                        labels = {1: "Strong Buy", 2: "Buy", 3: "Hold", 4: "Sell", 5: "Strong Sell"}
                        st.write(f"Consensus score: {recmean:.2f} — {labels.get(round(recmean), '')}")

                with right:
                    st.subheader("Price History (1Y)")
                    if not hist.empty:
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"], name="Close", line=dict(color="#38bdf8", width=2)))
                        if target:
                            fig.add_hline(y=target, line_dash="dash", line_color="#22c55e", annotation_text=f"Target ${target:.2f}", annotation_position="right")
                        fig.update_layout(
                            height=420,
                            margin=dict(l=20, r=20, t=30, b=20),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#e6edf7"),
                            xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                            yaxis=dict(gridcolor="rgba(255,255,255,0.05)")
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No price history available.")

            with atabs[1]:
                st.subheader("Valuation multiples")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Trailing P/E", fmt(trailing_pe))
                m2.metric("Forward P/E", fmt(forward_pe))
                m3.metric("Industry P/E", fmt(industry_pe))
                m4.metric("Vs Industry", f"{valuation_delta:.1f}%" if valuation_delta is not None else "NA")

                if valuation_flag != "NA":
                    st.success(f"Valuation vs industry: {valuation_flag}")
                else:
                    st.info("No industry average available for this stock.")

                st.divider()
                st.subheader("Automatic price target calculations")
                val_df, missed = valuation_table(
                    info, current, industry_pe,
                    dcf_growth, dcf_margin, dcf_discount, dcf_terminal, dcf_years, cf
                )

                if not val_df.empty:
                    st.dataframe(val_df, use_container_width=True, hide_index=True)
                    prices = pd.to_numeric(val_df["Implied ($)"], errors="coerce").dropna()
                    if not prices.empty:
                        r1, r2, r3 = st.columns(3)
                        r1.metric("Valuation Low", f"${prices.min():.2f}")
                        r2.metric("Valuation Mean", f"${prices.mean():.2f}")
                        r3.metric("Valuation High", f"${prices.max():.2f}")
                else:
                    st.warning("No valuation methods could run.")

                if missed:
                    with st.expander("Skipped methods"):
                        for m in missed:
                            st.caption(f"⚠️ {m}")

            with atabs[2]:
                st.subheader("Consensus price targets")
                rows_c = []
                fin = finnhub_data["targets"]
                if isinstance(fin, pd.DataFrame) and not fin.empty:
                    r = fin.iloc[0].to_dict()
                    rows_c.append({
                        "Source": "Finnhub",
                        "Low": r.get("targetLow"),
                        "Median": r.get("targetMedian"),
                        "Mean": r.get("targetMean"),
                        "High": r.get("targetHigh"),
                        "Last updated": r.get("lastUpdated", ""),
                    })
                rows_c.append({
                    "Source": "Yahoo Finance",
                    "Low": sn(info.get("targetLowPrice")),
                    "Median": sn(info.get("targetMedianPrice")),
                    "Mean": sn(info.get("targetMeanPrice")),
                    "High": sn(info.get("targetHighPrice")),
                    "Last updated": "",
                })
                st.dataframe(pd.DataFrame(rows_c), use_container_width=True, hide_index=True)

            with atabs[3]:
                st.subheader("Analyst recommendation history")
                recdf = pd.DataFrame()
                if isinstance(recs, pd.DataFrame) and not recs.empty:
                    recdf = recs.reset_index() if recs.index.name else recs.copy()
                    recdf["Source"] = "Yahoo Finance"
                fr = finnhub_data["recs"].copy()
                if not fr.empty:
                    fr["Source"] = "Finnhub"
                combined = pd.concat([x for x in [recdf, fr] if not x.empty], ignore_index=True, sort=False)
                if combined.empty:
                    st.info("No analyst history available.")
                else:
                    show_cols = [c for c in ["Source", "period", "strongBuy", "buy", "hold", "sell", "strongSell"] if c in combined.columns]
                    st.dataframe(combined[show_cols] if show_cols else combined, use_container_width=True, hide_index=True)

            with atabs[4]:
                st.subheader("Income statement")
                ds = qfin if isinstance(qfin, pd.DataFrame) and not qfin.empty else (afin if isinstance(afin, pd.DataFrame) and not afin.empty else None)
                if ds is not None:
                    st.dataframe(ds if show_full else ds.head(), use_container_width=True)
                else:
                    st.info("No income statement data available.")

                st.subheader("Quarterly balance sheet")
                if isinstance(qbs, pd.DataFrame) and not qbs.empty:
                    st.dataframe(qbs if show_full else qbs.head(), use_container_width=True)
                else:
                    st.info("No balance sheet data available.")

                st.subheader("Cash flow statement")
                if isinstance(cf, pd.DataFrame) and not cf.empty:
                    st.dataframe(cf if show_full else cf.head(), use_container_width=True)
                else:
                    st.info("No cash flow data available.")

            with atabs[5]:
                leader = f"{ceo_name} — {ceo_title}" if ceo_name and ceo_title else ceo_name or "No senior leader data available."
                st.write(f"**Leader:** {leader}")
                st.write(summary)

        except Exception as e:
            st.error(f"Could not load data for {ticker}: {e}")

# TAB 2
with main_tabs[1]:
    if not t212_api_key or not t212_api_secret:
        st.info("Enter both your Trading 212 API key and API secret in the sidebar.")
    else:
        with st.spinner("Loading your Trading 212 portfolio..."):
            portfolio = load_t212_portfolio(t212_api_key, t212_api_secret, t212_base)

        if portfolio["error"]:
            st.error(portfolio["error"])
            st.caption("If you still get 401, regenerate a new key pair and make sure Live/Demo matches the environment where the key was created.")
        else:
            summary_data = portfolio["summary"]
            positions = portfolio["positions"]

            st.subheader("Account Summary")
            cash_data = summary_data.get("cash", {})
            inv_data = summary_data.get("investments", {})
            currency = summary_data.get("currency", "")
            total_value = sn(summary_data.get("totalValue"))
            avail_cash = sn(cash_data.get("availableToTrade"))
            invested = sn(inv_data.get("totalCost"))
            unreal_pl = sn(inv_data.get("unrealizedProfitLoss"))
            real_pl = sn(inv_data.get("realizedProfitLoss"))

            s1, s2, s3, s4, s5 = st.columns(5)
            s1.metric("Total Value", f"{currency} {total_value:,.2f}" if total_value else "NA")
            s2.metric("Available Cash", f"{currency} {avail_cash:,.2f}" if avail_cash else "NA")
            s3.metric("Total Invested", f"{currency} {invested:,.2f}" if invested else "NA")
            s4.metric(
                "Unrealised P&L",
                f"{currency} {unreal_pl:+,.2f}" if unreal_pl is not None else "NA",
                delta=f"{(unreal_pl / invested * 100):.1f}%" if unreal_pl and invested else None
            )
            s5.metric("Realised P&L", f"{currency} {real_pl:+,.2f}" if real_pl is not None else "NA")

            st.divider()

            if not positions:
                st.info("No open positions found.")
            else:
                rows = []
                for p in positions:
                    inst = p.get("instrument") or {}
                    t212_tick = inst.get("ticker") or p.get("ticker", "")
                    name = inst.get("name") or t212_tick
                    yf_tick = t212_ticker_to_yf(t212_tick)
                    qty = sn(p.get("quantity"))
                    avg_price = sn(p.get("averagePricePaid"))
                    curr_px = sn(p.get("currentPrice"))
                    wallet = p.get("walletImpact") or {}
                    pnl = sn(wallet.get("unrealizedPnl") or wallet.get("ppl"))
                    mkt_val = round(qty * curr_px, 2) if qty and curr_px else None
                    cost = round(qty * avg_price, 2) if qty and avg_price else None
                    pnl_pct = round((pnl / cost) * 100, 2) if pnl and cost and cost != 0 else None

                    rows.append({
                        "Name": name,
                        "T212 Ticker": t212_tick,
                        "YF Ticker": yf_tick,
                        "Qty": qty,
                        "Avg Price": avg_price,
                        "Current": curr_px,
                        "Market Value": mkt_val,
                        "P&L": pnl,
                        "P&L %": pnl_pct,
                    })

                pos_df = pd.DataFrame(rows).sort_values("Market Value", ascending=False).reset_index(drop=True)

                st.subheader("Portfolio Breakdown")
                ch1, ch2 = st.columns(2)

                with ch1:
                    pie_df = pos_df.dropna(subset=["Market Value"])
                    if not pie_df.empty:
                        fig_pie = px.pie(
                            pie_df,
                            values="Market Value",
                            names="Name",
                            title="Allocation by Market Value",
                            color_discrete_sequence=px.colors.sequential.Teal
                        )
                        fig_pie.update_layout(
                            paper_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#e6edf7"),
                            legend=dict(font=dict(size=11))
                        )
                        st.plotly_chart(fig_pie, use_container_width=True)

                with ch2:
                    pnl_df = pos_df.dropna(subset=["P&L"]).sort_values("P&L")
                    if not pnl_df.empty:
                        fig_bar = go.Figure(go.Bar(
                            x=pnl_df["Name"],
                            y=pnl_df["P&L"],
                            marker_color=["#22c55e" if v >= 0 else "#f87171" for v in pnl_df["P&L"]],
                            text=[f"{currency}{v:+,.2f}" for v in pnl_df["P&L"]],
                            textposition="outside"
                        ))
                        fig_bar.update_layout(
                            title="Unrealised P&L per holding",
                            height=380,
                            margin=dict(l=20, r=20, t=50, b=80),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#e6edf7"),
                            yaxis=dict(gridcolor="rgba(255,255,255,0.05)")
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)

                st.divider()
                st.subheader("Holdings — click a row then press Analyse")

                selected = st.dataframe(
                    pos_df[["Name", "T212 Ticker", "YF Ticker", "Qty", "Avg Price", "Current", "Market Value", "P&L", "P&L %"]],
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                )

                sel_rows = selected.selection.rows if hasattr(selected, "selection") else []
                if sel_rows:
                    sel_row = pos_df.iloc[sel_rows[0]]
                    sel_name = sel_row["Name"]
                    sel_yf = sel_row["YF Ticker"]
                    st.info(f"Selected: **{sel_name}** — Yahoo Finance ticker: `{sel_yf}`")
                    if st.button(f"📈 Analyse {sel_name} →", type="primary"):
                        st.session_state["jump_to_ticker"] = sel_yf
                        st.rerun()
