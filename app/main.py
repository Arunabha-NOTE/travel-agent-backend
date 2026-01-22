from fastapi import FastAPI
import sentry_sdk

from app.config import SENTRY_DSN

sentry_sdk.init(
    dsn=SENTRY_DSN,
    send_default_pii=True,
)

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}
