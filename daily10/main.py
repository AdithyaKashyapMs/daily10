"""FastAPI app: the Daily 10 API under /study (used by the web app in web/)."""

import logging

from fastapi import FastAPI

from daily10.api import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Daily 10 API")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
