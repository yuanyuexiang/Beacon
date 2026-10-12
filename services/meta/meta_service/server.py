import base64
import os
import secrets
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from meta_service.core import Core, MetaError

app = FastAPI(title="Beacon Meta Service", docs_url=None, redoc_url=None)


def core() -> Core:
    return Core(Path(os.environ.get("META_DATA_DIR", "/data")))


def authorized(request: Request):
    path = os.environ.get("META_SERVICE_TOKEN_FILE")
    expected = Path(path).read_text().strip() if path and Path(path).is_file() else ""
    if not expected or not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + expected):
        raise HTTPException(401, "服务认证失败")


@app.exception_handler(MetaError)
async def error_handler(_: Request, exc: MetaError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    # Pydantic normally echoes inputs, including access tokens and app secrets.
    return JSONResponse(status_code=422, content={"detail": "配置格式无效，请核对字段与账号类型"})


class AppConfig(BaseModel):
    app_id: str = Field(min_length=1, max_length=128)
    app_secret: str = Field(min_length=1, max_length=512, repr=False)
    verify_token: str = Field(min_length=16, max_length=256, repr=False)
    version: str = "v25.0"
    redirect_uri: str = Field(max_length=512)


class AccountConfig(BaseModel):
    platform: Literal["facebook", "instagram"]
    auth_mode: Literal["facebook_login", "instagram_login"]
    sender_id: str = Field(min_length=1, max_length=128)
    page_id: str | None = Field(default=None, max_length=128)
    token: str | None = Field(default=None, max_length=8192, repr=False)

    @model_validator(mode="after")
    def compatible(self):
        if self.platform == "facebook" and self.auth_mode != "facebook_login":
            raise ValueError("Facebook 需 Facebook Login")
        return self


class Policy(BaseModel):
    daily_limit: int = Field(default=20, ge=1, le=100000)
    sending_enabled: bool


class Preview(BaseModel):
    account_id: uuid.UUID
    recipient_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1000)
    window_expires_at: int
    request_key: str = Field(min_length=1, max_length=128)


class Send(BaseModel):
    approval_token: str = Field(max_length=16384, repr=False)


class Webhook(BaseModel):
    raw: str = Field(max_length=1400000)
    signature: str = Field(max_length=128)


class Callback(BaseModel):
    state: str = Field(max_length=256)
    code: str = Field(max_length=4096, repr=False)


class Challenge(BaseModel):
    token: str = Field(max_length=256, repr=False)
    challenge: str = Field(max_length=256)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/app", dependencies=[Depends(authorized)])
def app_status():
    return core().app_status()


@app.put("/app", dependencies=[Depends(authorized)])
def app_config(body: AppConfig):
    return core().configure_app(body.model_dump())


@app.get("/accounts/{key}", dependencies=[Depends(authorized)])
def account_status(key: uuid.UUID):
    return core().account_status(str(key))


@app.put("/accounts/{key}", dependencies=[Depends(authorized)])
def account_config(key: uuid.UUID, body: AccountConfig):
    return core().configure_account(str(key), body.model_dump())


@app.post("/accounts/{key}/check", dependencies=[Depends(authorized)])
def check(key: uuid.UUID):
    return core().check(str(key))


@app.put("/accounts/{key}/policy", dependencies=[Depends(authorized)])
def policy(key: uuid.UUID, body: Policy):
    return core().policy(str(key), body.sending_enabled, body.daily_limit)


@app.post("/accounts/{key}/disconnect", dependencies=[Depends(authorized)])
def disconnect(key: uuid.UUID):
    return core().disconnect(str(key))


@app.post("/accounts/{key}/connect", dependencies=[Depends(authorized)])
def connect(key: uuid.UUID, body: AccountConfig):
    return core().oauth_start(str(key), body.model_dump(exclude={"token"}))


@app.post("/oauth/callback", dependencies=[Depends(authorized)])
def callback(body: Callback):
    return core().oauth_finish(body.state, body.code)


@app.post("/preview", dependencies=[Depends(authorized)])
def preview(body: Preview):
    return core().preview(body.model_dump(mode="json"))


@app.post("/send", dependencies=[Depends(authorized)])
def send(body: Send):
    return core().send(body.approval_token)


@app.get("/requests/{key}", dependencies=[Depends(authorized)])
def result(key: str):
    return core().request_status(key)


@app.post("/webhook/challenge", dependencies=[Depends(authorized)])
def challenge(body: Challenge):
    return {"challenge": core().webhook_challenge(body.token, body.challenge)}


@app.post("/webhook/verify", dependencies=[Depends(authorized)])
def webhook(body: Webhook):
    try:
        raw = base64.b64decode(body.raw, validate=True)
    except ValueError:
        raise MetaError("Webhook 格式无效") from None
    return {"events": core().webhook(raw, body.signature)}


class Reconcile(BaseModel):
    sent_at: float | None = None
    status: Literal["sent", "failed"]
    message_id: str | None = Field(default=None, max_length=256)
    reason: str = Field(min_length=10, max_length=1000)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def evidence(self):
        if self.status == "sent" and (not self.message_id or not self.sent_at):
            raise ValueError("平台已发送需提供消息 ID 与时间")
        return self


@app.post("/requests/{key}/reconcile", dependencies=[Depends(authorized)])
def manual_reconcile(key: str, body: Reconcile):
    return core().manual_reconcile(key, body.model_dump())
