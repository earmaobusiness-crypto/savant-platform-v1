# Savant Apprentice

Premium monochrome Streamlit chat UI for stock setup analysis with TradingView chart embeds.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

## Run

```bash
streamlit run app.py
```

Open the URL shown in the terminal (default `http://localhost:8501`).

## Notes

- Live quotes come from Yahoo Finance (`yfinance`).
- News context is pulled via DuckDuckGo HTML search (`html.duckduckgo.com`) and cached for 5 minutes per query.
- Chart embed appears only when a ticker is detected; macro-only questions skip the chart.
- Context-aware correlation notes trigger on Nvidia, Nasdaq, or general order-flow keywords.
- TradingView charts use the official Advanced Chart embed; symbols default to `NASDAQ:{TICKER}`.
