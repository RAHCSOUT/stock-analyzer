"""
Combined PDF exporter.
Merges Screener.in and Trendlyne data into a single PDF document.
"""

import pandas as pd
from io import BytesIO
from fpdf import FPDF


def _sanitize(text: str) -> str:
    """Replace non-latin1 characters so FPDF Helvetica can render them."""
    replacements = {
        "\u2026": "...",
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "--",
        "\u20b9": "Rs ",
        "\u2022": "*",
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _add_table_to_pdf(pdf: FPDF, name: str, df: pd.DataFrame):
    """Render a single DataFrame as a table on a new page."""
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, _sanitize(name), new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(2)

    n_cols = len(df.columns)
    if n_cols == 0:
        return

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


def export_combined_pdf(
    stock_name: str,
    screener_data: dict[str, pd.DataFrame] | None,
    trendlyne_data: dict[str, pd.DataFrame] | None,
) -> BytesIO:
    """Merge Screener + Trendlyne data into one PDF.

    Args:
        stock_name: Display name / symbol for the cover page.
        screener_data: Dict from screener scraper (or None).
        trendlyne_data: Dict from trendlyne scraper (or None).

    Returns:
        BytesIO buffer containing the combined PDF.
    """
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    # ── Cover page ────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 28)
    pdf.ln(30)
    pdf.cell(
        0, 16, _sanitize(stock_name),
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.set_font("Helvetica", "", 14)
    pdf.cell(
        0, 10, "Combined Financial Data Report",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.ln(6)

    sources = []
    if screener_data:
        sources.append("Screener.in")
    if trendlyne_data:
        sources.append("Trendlyne")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(
        0, 8, f"Sources: {', '.join(sources)}",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )

    # List all sections on cover page
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Contents:", new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.set_font("Helvetica", "", 10)
    idx = 1
    if screener_data:
        for name in screener_data:
            if name == "Info":
                continue
            pdf.cell(
                0, 6, f"  {idx}. [Screener] {_sanitize(name)}",
                new_x="LMARGIN", new_y="NEXT",
            )
            idx += 1
    if trendlyne_data:
        for name in trendlyne_data:
            if name == "Info":
                continue
            pdf.cell(
                0, 6, f"  {idx}. [Trendlyne] {_sanitize(name)}",
                new_x="LMARGIN", new_y="NEXT",
            )
            idx += 1

    # ── Screener.in section ───────────────────────────────────────
    if screener_data:
        # Section divider page
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 22)
        pdf.ln(40)
        pdf.cell(
            0, 14, "SCREENER.IN DATA",
            new_x="LMARGIN", new_y="NEXT", align="C",
        )
        pdf.set_font("Helvetica", "", 12)
        pdf.cell(
            0, 8, "screener.in",
            new_x="LMARGIN", new_y="NEXT", align="C",
        )

        for name, df in screener_data.items():
            if name == "Info":
                continue
            _add_table_to_pdf(pdf, f"[Screener] {name}", df)

    # ── Trendlyne section ─────────────────────────────────────────
    if trendlyne_data:
        # Section divider page
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 22)
        pdf.ln(40)
        pdf.cell(
            0, 14, "TRENDLYNE DATA",
            new_x="LMARGIN", new_y="NEXT", align="C",
        )
        pdf.set_font("Helvetica", "", 12)
        pdf.cell(
            0, 8, "trendlyne.com",
            new_x="LMARGIN", new_y="NEXT", align="C",
        )

        for name, df in trendlyne_data.items():
            if name == "Info":
                continue
            _add_table_to_pdf(pdf, f"[Trendlyne] {name}", df)

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer
