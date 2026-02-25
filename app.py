"""
Stock Analyzer
Enter a stock name, get a comprehensive AI-powered investment analysis.
Data is scraped from both Screener.in and Trendlyne automatically.
"""

import streamlit as st
from scraper import (
    search_company as screener_search,
    scrape_company_data as screener_scrape,
)
from trendlyne_scraper import (
    search_trendlyne,
    scrape_trendlyne_data,
)
from analyzer import analyze_stock

st.set_page_config(
    page_title="Stock Analyzer",
    page_icon="\U0001F4C8",
    layout="wide",
)

st.title("Stock Analyzer")
st.markdown("Enter a stock name and get a comprehensive AI investment analysis.")

api_key = st.text_input(
    "Anthropic API Key",
    type="password",
    placeholder="sk-ant-...",
)

query = st.text_input(
    "Stock name or symbol",
    placeholder="e.g. Reliance, TCS, INFY, HDFC Bank...",
)

if not api_key or not query:
    st.stop()

if st.button("Analyze", type="primary"):
    # ── Step 1: Search & resolve the stock on both sources ──────────
    screener_data = None
    trendlyne_data = None

    with st.status("Fetching data from Screener.in and Trendlyne...", expanded=False) as status:
        # --- Screener.in ---
        st.write("Searching on Screener.in...")
        try:
            results = screener_search(query)
            if results:
                selected = results[0]
                parts = selected["url"].strip("/").split("/")
                symbol = parts[1] if len(parts) >= 2 else query.upper()
                st.write(f"Fetching Screener data for {selected['name']}...")
                screener_data = screener_scrape(symbol)
                st.write(f"Got {len(screener_data)} sections from Screener.in")
            else:
                st.write("No results on Screener.in")
        except Exception as e:
            st.write(f"Screener.in error: {e}")

        # --- Trendlyne ---
        st.write("Searching on Trendlyne...")
        try:
            results = search_trendlyne(query)
            if results:
                sel = results[0]
                st.write(f"Fetching Trendlyne data for {sel['name']}...")
                trendlyne_data = scrape_trendlyne_data(
                    sel["stock_id"], sel["symbol"], sel["slug"],
                )
                st.write(f"Got {len(trendlyne_data)} sections from Trendlyne")
            else:
                st.write("No results on Trendlyne")
        except Exception as e:
            st.write(f"Trendlyne error: {e}")

        status.update(label="Data fetched", state="complete")

    if not screener_data and not trendlyne_data:
        st.error("Could not fetch data from either source. Try a different stock name.")
        st.stop()

    # ── Step 2: Merge data and run analysis ─────────────────────────
    combined = {}
    if screener_data:
        for k, v in screener_data.items():
            combined[f"[Screener] {k}"] = v
    if trendlyne_data:
        for k, v in trendlyne_data.items():
            combined[f"[Trendlyne] {k}"] = v

    source_label = ""
    if screener_data and trendlyne_data:
        source_label = "Screener.in and Trendlyne"
    elif screener_data:
        source_label = "Screener.in"
    else:
        source_label = "Trendlyne"

    with st.spinner("Running AI analysis — this may take up to a minute..."):
        try:
            analysis = analyze_stock(combined, source_label, api_key)
            st.session_state["analysis"] = analysis
        except Exception as e:
            st.error(f"Analysis failed: {e}")

if "analysis" in st.session_state:
    st.divider()
    st.subheader("Investment Analysis")
    st.markdown(st.session_state["analysis"])
