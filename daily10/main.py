"""FastAPI app: the Daily 10 API under /study (used by the web app in web/)."""

import logging

from fastapi import FastAPI

from daily10 import config
from daily10.api import router
from daily10.assistant_api import router as assistant_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# With STUDY_ENV=production, refuse to start with settings that would let strangers in.
if config.is_production() and config.production_problems():
    raise SystemExit("Not starting in production:\n  - " + "\n  - ".join(config.production_problems()))

app = FastAPI(title="Daily 10 API")
app.include_router(router)
app.include_router(assistant_router)


@app.get("/health")
def health():
    return {"status": "ok"}
