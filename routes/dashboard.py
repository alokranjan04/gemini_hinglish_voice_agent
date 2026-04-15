# -*- coding: utf-8 -*-
"""
Home page dashboard and provider-switch API.

GET  /           → Pipeline selector + links to metrics
POST /api/set-provider  → Switch active_provider in APP_CONFIG and persist to disk
"""
from aiohttp import web
from config.settings import APP_CONFIG, PORT, save_config

# ── Dashboard HTML template ───────────────────────────────────────────────────
# Uses str.format() — curly braces in CSS/JS are doubled to escape them.

_HOME_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Priya — Voice Agent</title>
<style>
  *,*::before,*::after{{box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       background:#f0f2f5;margin:0;padding:32px;color:#1a1a1a}}
  h1{{margin:0 0 4px;font-size:1.8rem}}
  .sub{{color:#888;margin-bottom:28px;font-size:.9rem}}
  .card{{background:white;border-radius:14px;padding:24px;
         box-shadow:0 2px 10px rgba(0,0,0,.07);margin-bottom:20px}}
  .card h2{{margin:0 0 16px;font-size:1.1rem}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  .provider{{border:2px solid #ddd;border-radius:10px;padding:20px;
             cursor:pointer;transition:all .15s;background:#fafafa;text-align:left}}
  .provider:hover{{background:#f5f5f5}}
  .provider.active.sarvam{{border-color:#2e7d32;background:#f1f8f1}}
  .provider.active.google{{border-color:#1565c0;background:#f0f4ff}}
  .provider h3{{margin:0 0 4px;font-size:1rem}}
  .provider p{{margin:0;font-size:.78rem;color:#888;line-height:1.4}}
  .badge{{display:inline-block;margin-top:10px;padding:3px 10px;border-radius:20px;
          font-size:.7rem;font-weight:700;background:#2e7d32;color:white}}
  .provider.google .badge{{background:#1565c0}}
  .links{{display:flex;gap:12px;flex-wrap:wrap}}
  .btn{{padding:10px 22px;border-radius:8px;font-size:.9rem;text-decoration:none;
        display:inline-block;border:none;cursor:pointer}}
  .btn-primary{{background:#1a73e8;color:white}}
  .btn-outline{{background:white;color:#1a73e8;border:1px solid #1a73e8}}
  .status{{font-size:.82rem;color:#888;margin-top:12px;min-height:1.2em}}
</style>
</head>
<body>
<h1>Priya — Voice Agent</h1>
<p class="sub">Neha Child Care · AI Receptionist · Port {port}</p>

<div class="card">
  <h2>Active Pipeline</h2>
  <div class="grid">
    <div class="provider {sa_active} sarvam" onclick="switchProvider('sarvam')">
      <h3>Sarvam AI</h3>
      <p>Deepgram Nova-3 STT → Sarvam 30B LLM → Sarvam Bulbul v2 TTS</p>
      {sa_badge}
    </div>
    <div class="provider {goo_active} google" onclick="switchProvider('google')">
      <h3>Google Gemini</h3>
      <p>Gemini Multimodal Live — native end-to-end audio (lowest latency)</p>
      {goo_badge}
    </div>
  </div>
  <p class="status" id="status"></p>
</div>

<div class="card">
  <h2>Monitoring</h2>
  <div class="links">
    <a href="/metrics" class="btn btn-primary">Metrics Dashboard</a>
    <a href="/metrics/data" class="btn btn-outline">Raw JSON</a>
  </div>
</div>

<script>
async function switchProvider(p) {{
  document.getElementById('status').textContent = 'Switching to ' + p + '…';
  const r = await fetch('/api/set-provider', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{provider: p}})
  }});
  const d = await r.json();
  if (d.ok) {{ location.reload(); }}
  else {{ document.getElementById('status').textContent = 'Error: ' + (d.error || 'unknown'); }}
}}
</script>
</body>
</html>
"""


async def home_page(request: web.Request) -> web.Response:
    provider   = APP_CONFIG.get("active_provider", "sarvam")
    sa_active  = "active" if provider == "sarvam" else ""
    goo_active = "active" if provider == "google"  else ""
    sa_badge   = '<span class="badge">● ACTIVE</span>' if provider == "sarvam" else ""
    goo_badge  = '<span class="badge">● ACTIVE</span>' if provider == "google"  else ""
    html = _HOME_TEMPLATE.format(
        port=PORT,
        sa_active=sa_active, goo_active=goo_active,
        sa_badge=sa_badge,   goo_badge=goo_badge,
    )
    return web.Response(text=html, content_type="text/html")


async def set_provider(request: web.Request) -> web.Response:
    try:
        data     = await request.json()
        provider = data.get("provider", "").strip().lower()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    if provider not in ("sarvam", "google"):
        return web.json_response(
            {"ok": False, "error": "Must be 'sarvam' or 'google'"}, status=400
        )

    APP_CONFIG["active_provider"] = provider
    try:
        save_config()
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)

    print(f"🔄 Provider switched → {provider}")
    return web.json_response({"ok": True, "provider": provider})
