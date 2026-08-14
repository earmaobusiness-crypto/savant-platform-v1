// TradingView → Room 3 live filter inbox.
// TV cannot send auth headers. Secret lives in the JSON body.
// Deploy: supabase functions deploy tv-screener
// Secret: supabase secrets set TV_WEBHOOK_SECRET=...

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "content-type",
};

function json(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

function normalizeTicker(raw: string): string {
  let t = String(raw || "").trim().toUpperCase().replace(/^\$/, "");
  t = t.replace(/^[A-Z]+:/, "");
  if (!/^[A-Z]{1,5}([.-][A-Z])?$/.test(t)) return "";
  return t;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json(405, { ok: false, error: "POST only" });

  const expected = String(Deno.env.get("TV_WEBHOOK_SECRET") || "").trim();
  if (!expected) return json(500, { ok: false, error: "TV_WEBHOOK_SECRET not set" });

  let payload: Record<string, unknown> = {};
  const text = await req.text();
  try {
    payload = JSON.parse(text);
  } catch {
    payload = { ticker: text };
  }

  const secret = String(payload.secret || payload.passphrase || "").trim();
  if (secret !== expected) return json(401, { ok: false, error: "bad secret" });

  const ticker = normalizeTicker(
    String(payload.ticker || payload.symbol || payload.Ticker || ""),
  );
  if (!ticker) return json(400, { ok: false, error: "ticker required" });

  const sessionRaw = String(payload.session || "rth").toLowerCase();
  const session = ["premarket", "rth", "postmarket"].includes(sessionRaw)
    ? sessionRaw
    : "rth";

  const url = Deno.env.get("SUPABASE_URL") || "";
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return json(500, { ok: false, error: "supabase env missing" });

  const sb = createClient(url, key);
  const { error } = await sb.from("room3_screener_hits").insert({
    ticker,
    session,
    source: "tradingview",
  });
  if (error) return json(500, { ok: false, error: error.message });
  return json(200, { ok: true, ticker, session });
});
