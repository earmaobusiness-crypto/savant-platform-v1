# Deploy Savant Cloud Compute to Render / Railway

## Render (recommended)

1. Create a new **Web Service** from this repo.
2. Set **Root Directory** to `services/cloud_compute`.
3. **Build command:** `pip install -r requirements.txt`
4. **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Copy the public URL into Streamlit secrets as `CLOUD_COMPUTE_URL`.

## Railway

```bash
cd services/cloud_compute
railway up
```

## Health check

`GET /health` → `{"status":"ok","engine":"savant-cloud-compute"}`

## Endpoints

| Route | Purpose |
|-------|---------|
| `POST /v1/resample` | Multi-timeframe OHLCV resample |
| `POST /v1/metric-envelopes` | Volume/velocity/spread σ-envelopes |
| `POST /v1/volume-envelope` | 3-hour volume baseline band |

## Supabase RPC

Run `supabase/migrations/007_cloud_offload_rpc.sql` in the Supabase SQL editor so spatial cosine matching and genetic merge execute on the database server.
