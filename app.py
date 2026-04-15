# -*- coding: utf-8 -*-
"""
app.py — entry point only.

Registers all routes and starts the aiohttp server.
Business logic lives in:
  config/     — settings, env vars
  core/       — recorder, Hindi utilities
  pipelines/  — sarvam handler, gemini handler
  routes/     — webhook, dashboard, metrics
Prompts and tool schemas are in app_config.json.
"""
import asyncio, sys
from aiohttp import web

from config.settings import APP_CONFIG, PORT
from pipelines.sarvam import sarvam_handler
from pipelines.gemini import gemini_handler
from routes.webhook   import handle_answer
from routes.dashboard import home_page, set_provider
from routes.metrics   import metrics_page, metrics_data

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


async def main():
    app = web.Application()

    app.router.add_get( "/",                  home_page)
    app.router.add_post("/answer",            handle_answer)
    app.router.add_post("/api/set-provider",  set_provider)
    app.router.add_get( "/sarvam-stream",     sarvam_handler)
    app.router.add_get( "/gemini-stream",     gemini_handler)
    app.router.add_get( "/metrics",           metrics_page)
    app.router.add_get( "/metrics/data",      metrics_data)
    app.router.add_static("/recordings",      "recordings", show_index=True)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    provider = APP_CONFIG.get("active_provider", "sarvam")
    print(f"🚀 PRIYA ONLINE — PORT {PORT}")
    print(f"   Active pipeline : {provider.upper()}")
    print(f"   Dashboard       : http://localhost:{PORT}/")
    print(f"   Metrics         : http://localhost:{PORT}/metrics")
    await asyncio.Future()   # run forever


if __name__ == "__main__":
    asyncio.run(main())
