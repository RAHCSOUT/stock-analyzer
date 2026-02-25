"""
Stock Analysis using Anthropic Claude API.
Takes scraped financial data and runs it through a comprehensive
investment analysis prompt framework.
"""

import os
from pathlib import Path
import pandas as pd
import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

ANALYSIS_PROMPT = """
Use this question framework to analyse the data of the given stock.
Use these methods of investing to analyse the stock ie The Ben Graham Method, The Peter Lynch Strategy, The Warren Buffett Approach. Provide buy, sell hold positions for them with reasons. Tell me all the issues with the stocks honestly. If they don't deserve appreciation don't give it to them. Be brutal and give honest review only. Give short term and long term positions with reasons.

Which phase is this stock in it's cycle of profit with reasons. Can this is a buy and forget stock? How Indian Govt policies affect it short term and long term.

The explanations must be simple so that a beginner can understand.

TIER 0 (Meta-Analysis)
Am I investing or gambling? (Time horizon determines answer) (Confidence: 97%)

TIER 1 (Foundational Truth-Seeking)
What evidence would prove I'm wrong about this investment? (Falsifiability) (Confidence: 95%)
Who is on the other side of this trade, and why are they selling? (Adversarial thinking) (Confidence: 93%)
What does management own vs what they say? (Skin in the game) (Confidence: 91%)
What would have to be true for this to 10x? (Reverse engineer thesis) (Confidence: 89%)
What insider information would change my thesis? (What am I missing?) (Confidence: 87%)

TIER 2 (Market Incentives)
Who profits if I believe this narrative? (Media, broker, company?) (Confidence: 94%)
What does analyst rating actually mean? (Often means "don't sue us") (Confidence: 90%)
Why is this available to me vs institutions only? (Access = quality signal) (Confidence: 88%)
What fee am I paying, and to whom? (Hidden costs) (Confidence: 92%)
Who needs me to buy for their position to work? (Pump and dump risk) (Confidence: 86%)

TIER 3 (Causal Analysis)
What happens to earnings if revenue drops 20%? (Stress test) (Confidence: 91%)
If interest rates rise 2%, what happens to valuation? (Macro sensitivity) (Confidence: 89%)
What second-order effect of success kills the company? (Growth -> regulation, competition) (Confidence: 84%)
How many quarters until thesis proves/disproves? (Time-bound hypothesis) (Confidence: 87%)
What external factor does this depend on? (Macro, sector, commodity price?) (Confidence: 85%)

TIER 4 (Capital Allocation)
What's my cost basis vs current conviction? (Sunk cost vs future decision) (Confidence: 93%)
Am I averaging down or throwing good money after bad? (Bayesian update) (Confidence: 90%)
What opportunity am I missing by holding this? (Opportunity cost) (Confidence: 88%)
Can I sell half and sleep better? (Position sizing) (Confidence: 86%)
What return do I need to justify this risk? (Risk-adjusted thinking) (Confidence: 91%)

TIER 5 (Valuation Boundaries)
At what P/E ratio does this become absurd? (Valuation ceiling) (Confidence: 89%)
What growth rate is priced in? (Expectations embedded in price) (Confidence: 87%)
What margin of safety do I have? (Downside protection) (Confidence: 90%)
At what price would I buy more vs sell? (Conviction test) (Confidence: 85%)

TIER 6 (Risk & Failure)
What kills this company in 5 years? (Existential threats) (Confidence: 92%)
What accounting trick hides problems? (Revenue recognition, off-balance sheet) (Confidence: 88%)
What would management do if desperate? (Dilution, debt, desperation moves) (Confidence: 86%)
What's bankruptcy probability in severe recession? (Stress scenario) (Confidence: 83%)

TIER 7 (Reference Class)
What's base rate of success for companies like this? (Outside view) (Confidence: 96%)
What similar companies failed, and why? (Learn from deaths) (Confidence: 91%)
What different thesis leads to same buy conclusion? (Multiple paths) (Confidence: 85%)
Who shorted this and why are they wrong/right? (Bear case) (Confidence: 89%)

TIER 8 (Information Quality)
What can't be faked in financial statements? (Cash flow > earnings) (Confidence: 94%)
What narrative is easier to sell than verify? (Story vs numbers) (Confidence: 90%)
What metric management focuses on vs what matters? (Goodhart's Law) (Confidence: 87%)
What's invisible in SEC filings but crucial? (Culture, moat durability) (Confidence: 84%)

TIER 9 (Optionality)
Does this give me more investment options or trap capital? (Liquidity) (Confidence: 91%)
What upside optionality exists? (Acquisition, new product, expansion) (Confidence: 86%)
What protects me if I'm completely wrong? (Downside protection) (Confidence: 89%)
Can I learn from this position regardless of outcome? (Educational value) (Confidence: 82%)

TIER 10 (Leverage Points)
What one change would 10x this company? (Key driver) (Confidence: 88%)
What moat is widening vs eroding? (Competitive dynamics) (Confidence: 90%)
What distribution channel unlocks growth? (Bottleneck identification) (Confidence: 85%)
What fixed cost gets leveraged by growth? (Operating leverage) (Confidence: 87%)
""".strip()


def _dataframes_to_text(data: dict[str, pd.DataFrame]) -> str:
    """Convert all DataFrames in the dict to a readable text block."""
    parts = []
    for name, df in data.items():
        parts.append(f"=== {name} ===")
        parts.append(df.to_string(index=False))
        parts.append("")
    return "\n".join(parts)


def analyze_stock(
    data: dict[str, pd.DataFrame],
    source: str,
    api_key: str = "",
) -> str:
    """Run Claude analysis on the scraped stock data.

    Args:
        data: Dict of section name -> DataFrame (from scraper).
        source: Data source label ("Screener.in" or "Trendlyne").
        api_key: Anthropic API key (falls back to env var if empty).

    Returns:
        The analysis as a markdown string.
    """
    if not api_key:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "Anthropic API key not provided. Please enter it in the app."
        )

    stock_data_text = _dataframes_to_text(data)

    user_message = (
        f"Here is the financial data for a stock, scraped from {source}:\n\n"
        f"{stock_data_text}\n\n"
        f"Now analyse this stock using the following framework:\n\n"
        f"{ANALYSIS_PROMPT}"
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[{"role": "user", "content": user_message}],
    )

    return response.content[0].text
