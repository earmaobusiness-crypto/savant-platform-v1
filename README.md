# Savant Apprentice

Premium monochrome Streamlit chat UI for stock setup analysis with TradingView chart embeds.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

## Run (local Mac)

```bash
./run_room3.sh
# or: source .venv/bin/activate && streamlit run app.py
```

Open **http://localhost:8501** (same link every time; only works while Streamlit is running).

## Foot-in-the-door online (Streamlit Community Cloud)

You already have GitHub (`savant-platform-v1`). Cloud UI is the online half; your Mac can stay optional.

1. Push latest `main` to GitHub (no `secrets.toml` — it’s gitignored).
2. Go to [share.streamlit.io](https://share.streamlit.io/) → sign in with GitHub → **New app**.
3. Repo: `earmaobusiness-crypto/savant-platform-v1` · Branch: `main` · Main file: `app.py`.
4. In the app **Settings → Secrets**, paste the same keys you use locally (Alpaca paper, Groq, Supabase, etc.) — cloud cannot read your Mac’s `.streamlit/secrets.toml`.
5. Deploy. You’ll get a fixed URL like `https://….streamlit.app` — bookmark that.

**Split that makes sense now**
- **Online (Streamlit Cloud):** open the app from anywhere — Rooms 1–3 UI, paper Alpaca API calls while the cloud app is awake.
- **Local Mac (optional):** same app via localhost when cloud is asleep or you’re developing.
- **Later (serious all-day scanning):** move the heavy watcher to a small always-on VPS/Render worker — not the MacBook.

Free Streamlit Cloud **sleeps when idle**; the first visit may take a minute to wake. That’s normal — not a new link.

## Cloud compute (Room 2 offload)

See `services/cloud_compute/README.md` (Render/Railway). Set `CLOUD_COMPUTE_URL` in secrets.

## Notes

- Live quotes come from Yahoo Finance (`yfinance`).
- News context is pulled via DuckDuckGo HTML search (`html.duckduckgo.com`) and cached for 5 minutes per query.
- Chart embed appears only when a ticker is detected; macro-only questions skip the chart.
- Context-aware correlation notes trigger on Nvidia, Nasdaq, or general order-flow keywords.
- TradingView charts use the official Advanced Chart embed; symbols default to `NASDAQ:{TICKER}`.
