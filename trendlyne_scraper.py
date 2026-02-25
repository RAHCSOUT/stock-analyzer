"""
Trendlyne Stock Data Scraper
Uses Selenium to fetch dynamically-loaded financial tables from trendlyne.com
and exports them to Excel and PDF.
"""

import os
import re
import shutil
import time
import pandas as pd
from io import BytesIO
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from fpdf import FPDF


# ── Selenium helpers ────────────────────────────────────────────────

def _make_driver() -> webdriver.Chrome:
    """Create a headless Chrome/Chromium driver.

    On Streamlit Community Cloud (Linux), uses system-installed chromium
    from packages.txt. Locally, falls back to webdriver-manager.
    """
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # Detect system-installed chromium (Streamlit Cloud / Linux)
    chromium_bin = shutil.which("chromium") or shutil.which("chromium-browser")
    chromedriver_bin = shutil.which("chromedriver") or shutil.which("chromium-driver")

    if chromium_bin and chromedriver_bin:
        opts.binary_location = chromium_bin
        driver = webdriver.Chrome(
            service=Service(chromedriver_bin), options=opts
        )
    else:
        # Local dev: use webdriver-manager
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=opts
        )

    driver.implicitly_wait(5)
    return driver


# ── Search ──────────────────────────────────────────────────────────

def search_trendlyne(query: str) -> list[dict]:
    """Search Trendlyne for a stock by typing into the navbar search.

    Returns a list of dicts with keys: name, symbol, stock_id, slug, url.
    """
    driver = _make_driver()
    try:
        driver.get("https://trendlyne.com/")
        time.sleep(3)

        search_box = driver.find_element(By.ID, "navbar-desktop-search")
        search_box.clear()
        search_box.send_keys(query)
        time.sleep(3)

        # Collect equity links that appeared after typing
        links = driver.find_elements(
            By.CSS_SELECTOR, '[class*=search] a[href*="/equity/"]'
        )

        seen = set()
        results = []
        for a in links:
            href = a.get_attribute("href") or ""
            if "/equity/" not in href or href in seen:
                continue
            seen.add(href)

            # Parse: /equity/{id}/{SYMBOL}/{slug}/
            m = re.search(r"/equity/(\d+)/([^/]+)/([^/]+)/?", href)
            if not m:
                continue

            stock_id, symbol, slug = m.group(1), m.group(2), m.group(3)
            nice_name = slug.replace("-", " ").title()

            results.append(
                {
                    "name": nice_name,
                    "symbol": symbol,
                    "stock_id": stock_id,
                    "slug": slug,
                    "url": href,
                }
            )
        return results
    finally:
        driver.quit()


# ── Scrape financials ───────────────────────────────────────────────

# The five tables on the financials page, in order
_TABLE_NAMES = [
    "Quarterly Results",
    "Annual Results",
    "Balance Sheet",
    "Ratios",
    "Cash Flow",
]


def _parse_table(table_el) -> Optional[pd.DataFrame]:
    """Parse a Selenium table WebElement into a DataFrame."""
    rows_el = table_el.find_elements(By.TAG_NAME, "tr")
    if not rows_el:
        return None

    # Header
    header_cells = rows_el[0].find_elements(By.TAG_NAME, "th")
    headers = [c.text.strip().replace("\n", " ") for c in header_cells]

    # Data rows
    data_rows = []
    for tr in rows_el[1:]:
        cells = tr.find_elements(By.TAG_NAME, "td")
        row = [c.text.strip().replace("\n", " ") for c in cells]
        if any(row):  # skip fully-empty rows
            data_rows.append(row)

    if not data_rows:
        return None

    # Drop the "Graph" column (index 1) – it contains only sparkline SVGs
    graph_idx = None
    for i, h in enumerate(headers):
        if h.lower() == "graph":
            graph_idx = i
            break

    if headers:
        max_cols = max(len(headers), max(len(r) for r in data_rows))
        headers += [""] * (max_cols - len(headers))
        data_rows = [r + [""] * (max_cols - len(r)) for r in data_rows]
        df = pd.DataFrame(data_rows, columns=headers)
    else:
        df = pd.DataFrame(data_rows)

    # Drop Graph column if found
    if graph_idx is not None and graph_idx < len(df.columns):
        df.drop(df.columns[graph_idx], axis=1, inplace=True)

    return df


def _scrape_analyst_data(driver, stock_id: str, symbol: str, slug: str) -> dict[str, pd.DataFrame]:
    """Scrape analyst / expert opinion data from the main equity page.

    Extracts: Key Metrics, Consensus Recommendation, EPS Forecast,
    Analyst Price Target, and Broker Research Reports.
    """
    url = f"https://trendlyne.com/equity/{stock_id}/{symbol}/{slug}/"
    driver.get(url)
    time.sleep(10)

    analyst_data: dict[str, pd.DataFrame] = {}

    # ── 1. Key Metrics ──────────────────────────────────────────────
    metrics_el = driver.find_elements(
        By.CSS_SELECTOR,
        "[class*=my_metrics_container], [class*=user_metric_table]",
    )
    if metrics_el:
        raw = metrics_el[0].text.strip()
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        # Metrics come in triplets: Name / Remark / Value
        # (some have only Name / Value with no remark)
        rows = []
        i = 0
        while i < len(lines):
            # Skip footer lines
            if lines[i].startswith("All financials"):
                break
            name = lines[i]
            # Peek ahead: if i+2 exists and i+2 looks like a number, it's a triplet
            if i + 2 < len(lines) and _looks_numeric(lines[i + 2]):
                rows.append([name, lines[i + 1], lines[i + 2]])
                i += 3
            elif i + 1 < len(lines) and _looks_numeric(lines[i + 1]):
                rows.append([name, "", lines[i + 1]])
                i += 2
            else:
                i += 1
        if rows:
            analyst_data["Key Metrics"] = pd.DataFrame(
                rows, columns=["Metric", "Remark", "Value"]
            )

    # ── 2. Consensus Recommendation ─────────────────────────────────
    consensus_cards = driver.find_elements(
        By.CSS_SELECTOR, ".consensus-card"
    )
    for card in consensus_cards:
        card_text = card.text.strip()
        if "CONSENSUS RECOMMENDATION" in card_text:
            lines = [l.strip() for l in card_text.split("\n") if l.strip()]
            rows = []
            for line in lines:
                if line == "CONSENSUS RECOMMENDATION":
                    continue
                rows.append([line])
            if rows:
                analyst_data["Consensus Recommendation"] = pd.DataFrame(
                    rows, columns=["Detail"]
                )

    # ── 3. EPS Forecast ─────────────────────────────────────────────
    for card in consensus_cards:
        card_text = card.text.strip()
        if "EPS FORECAST" in card_text:
            lines = [l.strip() for l in card_text.split("\n") if l.strip()]
            rows = []
            i = 0
            while i < len(lines):
                if lines[i] in ("EPS FORECAST", "QUARTER", "ANNUAL"):
                    i += 1
                    continue
                # label-value pairs
                if i + 1 < len(lines) and _looks_numeric(lines[i + 1]):
                    rows.append([lines[i], lines[i + 1]])
                    i += 2
                else:
                    rows.append([lines[i], ""])
                    i += 1
            if rows:
                analyst_data["EPS Forecast"] = pd.DataFrame(
                    rows, columns=["Indicator", "Value"]
                )
            break

    # ── 4. Revenue Forecast insight ─────────────────────────────────
    for card in consensus_cards:
        card_text = card.text.strip()
        if "REVENUE FORECAST" in card_text:
            lines = [l.strip() for l in card_text.split("\n") if l.strip()]
            # Extract the insight line at the end
            rows = []
            for line in lines:
                if line in ("REVENUE FORECAST", "QUARTER", "ANNUAL",
                            "ACTUAL REVENUE", "AVG. ESTIMATE"):
                    continue
                # skip pure numbers / chart ticks
                if re.match(r"^[\d,.kKmM]+$", line):
                    continue
                rows.append([line])
            if rows:
                analyst_data["Revenue Forecast"] = pd.DataFrame(
                    rows, columns=["Detail"]
                )
            break

    # ── 5. Analyst Price Target ─────────────────────────────────────
    fc = driver.find_elements(By.CSS_SELECTOR, ".forecaster-container")
    if fc:
        lines = [l.strip() for l in fc[0].text.strip().split("\n") if l.strip()]
        rows = []
        for line in lines:
            if "SUBSCRIBE" in line.upper():
                continue
            rows.append([line])
        if rows:
            analyst_data["Analyst Price Target"] = pd.DataFrame(
                rows, columns=["Detail"]
            )

    # ── 6. Broker Research Reports ──────────────────────────────────
    all_tables = driver.find_elements(By.TAG_NAME, "table")
    for t in all_tables:
        rows_el = t.find_elements(By.TAG_NAME, "tr")
        if rows_el and len(rows_el) > 2:
            hdr_text = rows_el[0].text.strip().lower()
            if "broker" in hdr_text and "target" in hdr_text:
                hdr_cells = rows_el[0].find_elements(By.TAG_NAME, "th")
                headers = [c.text.strip().replace("\n", " ")[:25] for c in hdr_cells]
                data_rows = []
                for r in rows_el[1:]:
                    cells = r.find_elements(By.TAG_NAME, "td")
                    vals = [c.text.strip().replace("\n", " ")[:30] for c in cells]
                    if any(vals):
                        data_rows.append(vals)
                if data_rows:
                    max_c = max(len(headers), max(len(r) for r in data_rows))
                    headers += [""] * (max_c - len(headers))
                    data_rows = [r + [""] * (max_c - len(r)) for r in data_rows]
                    analyst_data["Broker Targets"] = pd.DataFrame(
                        data_rows, columns=headers
                    )
                break

    # ── 7. SWOT counts ──────────────────────────────────────────────
    swot_map = {"swot-s": "Strengths", "swot-w": "Weaknesses",
                "swot-o": "Opportunities", "swot-t": "Threats"}
    swot_rows = []
    swot_cols = driver.find_elements(By.CSS_SELECTOR, ".swot-col")
    for col in swot_cols:
        cls = col.get_attribute("class") or ""
        for key, label in swot_map.items():
            if key in cls:
                count = col.text.strip() or "N/A"
                # Count is usually just a number inside the element
                nums = re.findall(r"\d+", count)
                val = nums[0] if nums else count
                swot_rows.append([label, val])
                break
    if swot_rows:
        analyst_data["SWOT Summary"] = pd.DataFrame(
            swot_rows, columns=["Category", "Count"]
        )

    return analyst_data


def _looks_numeric(s: str) -> bool:
    """Check if a string looks like a numeric value (allows %, commas, negatives)."""
    s = s.strip().replace(",", "").replace("%", "").replace(" ", "")
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def scrape_trendlyne_data(
    stock_id: str, symbol: str, slug: str
) -> dict[str, pd.DataFrame]:
    """Scrape financial tables + analyst data from Trendlyne.

    Visits two pages:
      1. /fundamentals/financials/ for P&L, Balance Sheet, Cash Flow, etc.
      2. /equity/ for analyst estimates, broker targets, key metrics, SWOT.

    Args:
        stock_id: Trendlyne internal numeric ID (e.g. '1372')
        symbol: NSE ticker (e.g. 'TCS')
        slug: URL slug (e.g. 'tata-consultancy-services-ltd')

    Returns:
        dict mapping section names to DataFrames.
    """
    financials_url = (
        f"https://trendlyne.com/fundamentals/financials/"
        f"{stock_id}/{symbol}/{slug}/"
    )

    driver = _make_driver()
    try:
        # ── Page 1: Financials ──────────────────────────────────────
        driver.get(financials_url)
        time.sleep(10)

        title = driver.title or ""
        company_name = title.split(" - ")[0].strip() if " - " in title else symbol

        tables = driver.find_elements(
            By.CSS_SELECTOR, "table.tl-react-table-v7"
        )

        results: dict[str, pd.DataFrame] = {}

        for i, table_el in enumerate(tables):
            name = _TABLE_NAMES[i] if i < len(_TABLE_NAMES) else f"Table {i+1}"
            df = _parse_table(table_el)
            if df is not None and not df.empty:
                results[name] = df

        if not results:
            raise ValueError(
                f"No financial data found for '{symbol}' on Trendlyne. "
                "The page may require login or the stock may be invalid."
            )

        # ── Page 2: Analyst / Expert data ───────────────────────────
        analyst_data = _scrape_analyst_data(driver, stock_id, symbol, slug)
        results.update(analyst_data)

        # ── Info sheet ──────────────────────────────────────────────
        info_rows = [
            ["Company", company_name],
            ["Symbol", symbol],
            ["Source (Financials)", financials_url],
            ["Source (Analyst)", f"https://trendlyne.com/equity/{stock_id}/{symbol}/{slug}/"],
            ["Data Sections", ", ".join(results.keys())],
        ]
        results["Info"] = pd.DataFrame(info_rows, columns=["Field", "Value"])

        return results
    finally:
        driver.quit()


# ── Export helpers (reuse same patterns as screener scraper) ────────

def export_to_excel(data: dict[str, pd.DataFrame]) -> BytesIO:
    """Write all DataFrames to an in-memory Excel workbook."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if "Info" in data:
            data["Info"].to_excel(writer, sheet_name="Info", index=False)
        for name, df in data.items():
            if name == "Info":
                continue
            safe = name[:31].replace("/", "-").replace("\\", "-")
            df.to_excel(writer, sheet_name=safe, index=False)
    buffer.seek(0)
    return buffer


def _sanitize(text: str) -> str:
    """Replace non-latin1 characters so FPDF Helvetica can render them."""
    replacements = {
        "\u2026": "...",   # ellipsis
        "\u2019": "'",     # right single quote
        "\u2018": "'",     # left single quote
        "\u201c": '"',     # left double quote
        "\u201d": '"',     # right double quote
        "\u2013": "-",     # en dash
        "\u2014": "--",    # em dash
        "\u20b9": "Rs ",   # rupee sign
        "\u2022": "*",     # bullet
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    # Drop any remaining non-latin1 chars
    return text.encode("latin-1", errors="replace").decode("latin-1")


def export_to_pdf(data: dict[str, pd.DataFrame]) -> BytesIO:
    """Render all DataFrames into a formatted landscape PDF."""
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    # Info page
    if "Info" in data:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 22)
        info_df = data["Info"]
        company_name = ""
        for _, row in info_df.iterrows():
            if row.iloc[0] == "Company":
                company_name = str(row.iloc[1])
                break
        pdf.cell(
            0, 14,
            _sanitize(company_name or "Stock Data Report"),
            new_x="LMARGIN", new_y="NEXT", align="C",
        )
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(
            0, 8, "Data sourced from trendlyne.com",
            new_x="LMARGIN", new_y="NEXT", align="C",
        )
        pdf.ln(6)
        pdf.set_font("Helvetica", "", 10)
        for _, row in info_df.iterrows():
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(50, 7, _sanitize(str(row.iloc[0])), border=1)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 7, _sanitize(str(row.iloc[1])), border=1, new_x="LMARGIN", new_y="NEXT")

    # Data sheets
    for name, df in data.items():
        if name == "Info":
            continue

        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, _sanitize(name), new_x="LMARGIN", new_y="NEXT", align="L")
        pdf.ln(2)

        n_cols = len(df.columns)
        if n_cols == 0:
            continue

        page_width = pdf.w - pdf.l_margin - pdf.r_margin
        first_col_w = min(page_width * 0.22, 60)
        remaining_w = page_width - first_col_w
        other_col_w = remaining_w / max(n_cols - 1, 1) if n_cols > 1 else remaining_w

        row_h = 7
        font_size = 7
        if n_cols > 14:
            font_size = 5.5
            row_h = 5.5
        elif n_cols > 10:
            font_size = 6
            row_h = 6

        def _print_header():
            pdf.set_font("Helvetica", "B", font_size)
            for i, col in enumerate(df.columns):
                w = first_col_w if i == 0 else other_col_w
                pdf.cell(w, row_h, _sanitize(str(col)[:18]), border=1, align="C")
            pdf.ln()

        _print_header()

        pdf.set_font("Helvetica", "", font_size)
        for _, row in df.iterrows():
            if pdf.get_y() + row_h > pdf.h - 15:
                pdf.add_page()
                _print_header()
                pdf.set_font("Helvetica", "", font_size)
            for i, val in enumerate(row):
                w = first_col_w if i == 0 else other_col_w
                align = "L" if i == 0 else "R"
                pdf.cell(w, row_h, _sanitize(str(val)[:20]), border=1, align=align)
            pdf.ln()

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer
