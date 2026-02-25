"""
Screener.in Stock Data Scraper
Fetches financial data tables from screener.in company pages
and exports them to a single Excel workbook with multiple sheets.
"""

import requests
import pandas as pd
from bs4 import BeautifulSoup
from fpdf import FPDF
from io import BytesIO
from typing import Optional


SEARCH_API = "https://www.screener.in/api/company/search/?q={}"
COMPANY_URL = "https://www.screener.in/company/{}/"
CONSOLIDATED_URL = "https://www.screener.in/company/{}/consolidated/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def search_company(query: str) -> list[dict]:
    """Search for a company on screener.in by name or symbol.
    Returns a list of matching companies with id, name, and url.
    """
    url = SEARCH_API.format(requests.utils.quote(query))
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _parse_section(section) -> Optional[pd.DataFrame]:
    """Parse a single data section from the screener page into a DataFrame."""
    table = section.find("table")
    if table is None:
        return None

    headers = []
    header_row = table.find("thead")
    if header_row:
        for th in header_row.find_all("th"):
            headers.append(th.get_text(strip=True))

    rows = []
    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)

    if not rows:
        return None

    # Build DataFrame
    if headers:
        max_cols = max(len(headers), max(len(r) for r in rows))
        # Pad headers/rows to equal length
        headers += [""] * (max_cols - len(headers))
        rows = [r + [""] * (max_cols - len(r)) for r in rows]
        df = pd.DataFrame(rows, columns=headers)
    else:
        df = pd.DataFrame(rows)

    return df


def scrape_company_data(symbol: str) -> dict[str, pd.DataFrame]:
    """Scrape all financial tables from a screener.in company page.

    Args:
        symbol: The stock symbol (e.g. 'RELIANCE', 'TCS', 'INFY')

    Returns:
        A dict mapping sheet/section names to DataFrames.
    """
    # Try consolidated first, fall back to standalone
    for url_template in [CONSOLIDATED_URL, COMPANY_URL]:
        url = url_template.format(symbol.upper())
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            break
    else:
        raise ValueError(
            f"Could not find company page for '{symbol}'. "
            "Check the symbol and try again."
        )

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract the company name from the page
    name_tag = soup.find("h1")
    company_name = name_tag.get_text(strip=True) if name_tag else symbol.upper()

    # Sections we want to extract (id -> friendly sheet name)
    section_map = {
        "quarters": "Quarterly Results",
        "profit-loss": "Profit & Loss",
        "balance-sheet": "Balance Sheet",
        "cash-flow": "Cash Flow",
        "ratios": "Ratios",
        "shareholding": "Shareholding",
    }

    results: dict[str, pd.DataFrame] = {}

    for section_id, sheet_name in section_map.items():
        section = soup.find("section", id=section_id)
        if section is None:
            continue
        df = _parse_section(section)
        if df is not None and not df.empty:
            results[sheet_name] = df

    # Also try to grab any remaining data-tables not covered above
    all_sections = soup.find_all("section")
    for section in all_sections:
        sec_id = section.get("id", "")
        if sec_id in section_map or sec_id == "":
            continue
        # Use the section heading as the sheet name
        heading = section.find(["h2", "h3"])
        if heading:
            name = heading.get_text(strip=True)[:31]  # Excel sheet name limit
        else:
            name = sec_id[:31] if sec_id else "Other"
        if name in results:
            continue
        df = _parse_section(section)
        if df is not None and not df.empty:
            results[name] = df

    if not results:
        raise ValueError(
            f"No financial data found for '{symbol}'. "
            "The page may require login or the symbol may be invalid."
        )

    # Add a summary/info sheet
    info_rows = [
        ["Company", company_name],
        ["Symbol", symbol.upper()],
        ["Source", f"https://www.screener.in/company/{symbol.upper()}/"],
        ["Data Sections", ", ".join(results.keys())],
    ]
    results["Info"] = pd.DataFrame(info_rows, columns=["Field", "Value"])

    return results


def export_to_excel(data: dict[str, pd.DataFrame]) -> BytesIO:
    """Write all DataFrames to an in-memory Excel workbook.

    Returns a BytesIO buffer containing the .xlsx file.
    """
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        # Write Info sheet first
        if "Info" in data:
            data["Info"].to_excel(writer, sheet_name="Info", index=False)

        for name, df in data.items():
            if name == "Info":
                continue
            # Sanitise sheet name (Excel max 31 chars, no special chars)
            safe_name = name[:31].replace("/", "-").replace("\\", "-")
            df.to_excel(writer, sheet_name=safe_name, index=False)

    buffer.seek(0)
    return buffer


def export_to_pdf(data: dict[str, pd.DataFrame]) -> BytesIO:
    """Render all DataFrames into a formatted PDF document.

    Returns a BytesIO buffer containing the .pdf file.
    """
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- Info page ---
    if "Info" in data:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 22)
        info_df = data["Info"]
        company_name = ""
        for _, row in info_df.iterrows():
            if row.iloc[0] == "Company":
                company_name = str(row.iloc[1])
                break
        pdf.cell(0, 14, company_name or "Stock Data Report", new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 8, "Data sourced from screener.in", new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(6)

        pdf.set_font("Helvetica", "", 10)
        for _, row in info_df.iterrows():
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(50, 7, str(row.iloc[0]), border=1)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 7, str(row.iloc[1]), border=1, new_x="LMARGIN", new_y="NEXT")

    # --- Data sheets ---
    for name, df in data.items():
        if name == "Info":
            continue

        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, name, new_x="LMARGIN", new_y="NEXT", align="L")
        pdf.ln(2)

        n_cols = len(df.columns)
        if n_cols == 0:
            continue

        # Calculate column widths to fit the page
        page_width = pdf.w - pdf.l_margin - pdf.r_margin
        # Give the first column (label) more space
        first_col_w = min(page_width * 0.22, 60)
        remaining_w = page_width - first_col_w
        other_col_w = remaining_w / max(n_cols - 1, 1) if n_cols > 1 else remaining_w

        row_h = 7
        font_size = 7
        # If too many columns, shrink further
        if n_cols > 14:
            font_size = 5.5
            row_h = 5.5
        elif n_cols > 10:
            font_size = 6
            row_h = 6

        # Header row
        pdf.set_font("Helvetica", "B", font_size)
        for i, col in enumerate(df.columns):
            w = first_col_w if i == 0 else other_col_w
            pdf.cell(w, row_h, str(col)[:18], border=1, align="C")
        pdf.ln()

        # Data rows
        pdf.set_font("Helvetica", "", font_size)
        for _, row in df.iterrows():
            # Check if we need a new page
            if pdf.get_y() + row_h > pdf.h - 15:
                pdf.add_page()
                # Reprint header on new page
                pdf.set_font("Helvetica", "B", font_size)
                for i, col in enumerate(df.columns):
                    w = first_col_w if i == 0 else other_col_w
                    pdf.cell(w, row_h, str(col)[:18], border=1, align="C")
                pdf.ln()
                pdf.set_font("Helvetica", "", font_size)

            for i, val in enumerate(row):
                w = first_col_w if i == 0 else other_col_w
                align = "L" if i == 0 else "R"
                pdf.cell(w, row_h, str(val)[:20], border=1, align=align)
            pdf.ln()

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer
