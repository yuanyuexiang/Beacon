"""Channel-specific, evidence-backed review. Never grants API capabilities or sends."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

VERSION = "channel-review:v1"

# A manual reviewer attests each applicable fact; models cannot invent consent or screening.
REQUIREMENTS: dict[str, list[dict[str, str]]] = {
    "email": [
        {
            "key": "email_basis",
            "label": "邮件联系依据",
            "hint": "说明公司订户及邮箱归属，或具体同意／适用的既有客户依据；涉及个人信息时一并说明处理依据。",
        }
    ],
    "phone": [
        {
            "key": "tps",
            "label": "TPS 筛查",
            "hint": "记录号码、查询来源、查询日期及未登记结果；登记号码须提供针对本方的有效来电同意。",
        },
        {
            "key": "ctps",
            "label": "CTPS 筛查",
            "hint": "记录号码、查询来源、查询日期及未登记结果；登记号码须提供针对本方的有效来电同意。",
        },
    ],
    "whatsapp": [
        {
            "key": "opt_in",
            "label": "接收消息的同意记录",
            "hint": "记录谁、何时、通过什么方式，同意接收本方哪些消息；公开手机号不代表同意。",
        }
    ],
    "contact_form": [
        {
            "key": "form_purpose",
            "label": "表单用途及本次提交依据",
            "hint": "引用商务／供应商合作用途和适用联系依据；不要使用预约、投诉或求职表单推销。",
        }
    ],
    "post": [
        {
            "key": "postal_basis",
            "label": "邮寄对象、地址及处理依据",
            "hint": "确认业务地址、适用的数据处理依据和拒收记录；不自动购买邮资或寄送。",
        }
    ],
}
SOCIAL = [
    {
        "key": "message_basis",
        "label": "本次消息联系依据",
        "hint": "记录适用的收件方类型或同意依据及用途；关注、好友关系、公开主页不等于营销授权。",
    },
]
for _channel in ("facebook", "instagram", "tiktok", "linkedin", "other_social"):
    REQUIREMENTS[_channel] = SOCIAL


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=40)
    source: str = Field(default="", max_length=500)
    detail: str = Field(default="", max_length=2500)
    checked_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    result: Literal["verified", "clear", "specific_consent"] = "verified"


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["allowed", "unknown", "blocked"]
    # Narrow scope: outbound business marketing, manual or supported API execution.
    purpose: Literal["business_marketing", "requested_reply"] = "business_marketing"
    content_id: uuid.UUID | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=8)
    note: str = Field(min_length=5, max_length=1500)
    confirmed: bool = False


def missing(channel: str, record: dict | None, at: datetime | None = None) -> list[str]:
    at = at or datetime.now(UTC)
    if not record:
        return ["尚未记录本渠道的联系依据"]
    if record.get("version") != VERSION or record.get("purpose") not in {"business_marketing", "requested_reply"}:
        return ["联系条件版本或用途不匹配，请重新审核"]
    items = {e.get("key"): e for e in record.get("evidence", [])}
    errors = []
    if record.get("decision") != "allowed" or not record.get("confirmed"):
        errors.append("本次联系依据尚未确认允许")
    for requirement in requirements(channel, record.get("purpose", "business_marketing")):
        entry = items.get(requirement["key"])
        label = requirement["label"]
        if not entry:
            errors.append(f"缺少{label}")
            continue
        try:
            evidence = Evidence.model_validate(entry)
            if not evidence.checked_at or not evidence.expires_at:
                raise ValueError("missing dates")
            if len(evidence.source.strip()) < 3 or len(evidence.detail.strip()) < 10:
                raise ValueError("empty evidence")
            if evidence.checked_at > at or evidence.expires_at <= at or evidence.expires_at <= evidence.checked_at:
                errors.append(f"{label}日期无效或已过期")
            if channel == "phone" and record.get("purpose") != "requested_reply":
                if evidence.result not in {"clear", "specific_consent"}:
                    errors.append(f"{label}须记录未登记或针对本方的有效同意")
                if evidence.result == "clear" and (
                    at - evidence.checked_at > timedelta(days=28)
                    or evidence.expires_at - evidence.checked_at > timedelta(days=28)
                ):
                    errors.append(f"{label}超出系统 28 天筛查有效期，请重新筛查")
        except (ValueError, TypeError):
            errors.append(f"{label}记录不完整")
    if channel not in REQUIREMENTS:
        errors.append("该渠道尚无适用联系规则")
    return errors


def requirements(channel: str, purpose: str) -> list[dict[str, str]]:
    if purpose == "requested_reply":
        return [
            {
                "key": "inbound_request",
                "label": "客户请求及本次回复范围",
                "hint": "引用客户实际咨询、时间和记录来源，核对本次回复范围；主动询问菜单不是客户请求。",
            }
        ]
    return REQUIREMENTS.get(channel, [])


def content_missing(record: dict | None, content_id: str, content_hash: str) -> list[str]:
    if (
        record
        and record.get("purpose") == "requested_reply"
        and (record.get("content_id") != content_id or record.get("content_hash") != content_hash)
    ):
        return ["客户请求依据仅适用于已核对的回复消息；内容变化后须重新核对回复范围"]
    return []


def public(row) -> dict:
    record = row.conditions
    gaps = missing(row.channel.value, record) if record else []
    return {
        "version": VERSION,
        "purpose": "business_marketing",
        "requirements": REQUIREMENTS.get(row.channel.value, []),
        "reply_requirements": requirements(row.channel.value, "requested_reply"),
        "record": record,
        "missing": gaps,
        "status": "unknown" if gaps else row.eligibility.value,
        "execution": "需另行检查账号、权限及会话窗口"
        if row.channel.value in {"facebook", "instagram", "whatsapp", "tiktok", "linkedin"}
        else "执行前重新检查联系条件与消息确认",
        "legacy": record is None,
    }
