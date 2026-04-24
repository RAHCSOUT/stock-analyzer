"""
Stock Analyzer
Enter a stock name → get a single PDF with all financial data
from Screener.in and Trendlyne. Optionally run AI analysis.
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
from combined_pdf import export_combined_pdf
from analyzer import analyze_stock

st.set_page_config(
    page_title="Stock Analyzer",
    page_icon="\U0001F4C8",
    layout="wide",
)

st.title("Stock Analyzer")
st.markdown("Enter a stock name to get a combined PDF of all financial data.")

query = st.text_input(
    "Stock name or symbol",
    placeholder="e.g. Reliance, TCS, INFY, HDFC Bank...",
)

api_key = st.text_input(
    "Anthropic API Key (optional — needed only for AI analysis)",
    type="password",
    placeholder="sk-ant-...",
)

if not query:
    st.stop()

if st.button("Get Report", type="primary"):
    screener_data = None
    trendlyne_data = None
    stock_symbol = query.upper()
    stock_name = query.upper()

    with st.status("Fetching data from Screener.in and Trendlyne...", expanded=False) as status:
        # --- Screener.in ---
        st.write("Searching on Screener.in...")
        try:
            results = screener_search(query)
            if results:
                selected = results[0]
                parts = selected["url"].strip("/").split("/")
                stock_symbol = parts[1] if len(parts) >= 2 else query.upper()
                stock_name = selected["name"]
                st.write(f"Fetching Screener data for {stock_name}...")
                screener_data = screener_scrape(stock_symbol)
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
                stock_symbol = sel["symbol"]
                stock_name = sel["name"]
                st.write(f"Fetching Trendlyne data for {stock_name}...")
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

    # Generate combined PDF
    pdf_buf = export_combined_pdf(stock_name, screener_data, trendlyne_data)
    st.session_state["pdf"] = pdf_buf
    st.session_state["stock_symbol"] = stock_symbol
    st.session_state["stock_name"] = stock_name

    # Run AI analysis if API key provided
    if api_key:
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
    else:
        # Clear old analysis if no key this time
        st.session_state.pop("analysis", None)

# ── Display results ───────────────────────────────────────────────
if "pdf" in st.session_state:
    sym = st.session_state.get("stock_symbol", "STOCK")
    name = st.session_state.get("stock_name", sym)

    st.divider()
    st.download_button(
        label=f"Download PDF — {name} ({sym})",
        data=st.session_state["pdf"],
        file_name=f"{sym}_stock_report.pdf",
        mime="application/pdf",
        type="primary",
    )

if "analysis" in st.session_state:
    st.divider()
    st.subheader("AI Investment Analysis")
    st.markdown(st.session_state["analysis"])
