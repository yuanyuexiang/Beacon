"""Record a manually verified unknown result. This command never sends an email."""

import argparse
import json
import time

from . import core, server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_key")
    parser.add_argument("--status", choices=["sent", "failed"], required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--message-id", default="")
    args = parser.parse_args()
    if not args.note.strip():
        parser.error("必须填写核对依据")
    if server.policy()["sending_enabled"]:
        parser.error("请先在设置页暂停 Gmail 发送，再核对结果")
    result = server.request_result(args.request_key)
    if result["status"] != "unknown":
        parser.error("只能核对结果未知的请求")
    if args.status == "sent":
        if not args.message_id:
            parser.error("确认已发送必须提供 Gmail message ID")
        message = core._gmail_get("messages/" + args.message_id, [("format", "metadata")])
        if "SENT" not in message.get("labelIds", []):
            parser.error("指定邮件不属于已发送邮件，请重新核对")
        result.update(
            id=message["id"], threadId=message.get("threadId"), sent_at=int(message.get("internalDate", 0)) // 1000
        )
    if result.get("attempt_id"):
        core.resolve_send(result["attempt_id"], args.status, args.note, args.message_id)
    result["status"] = args.status
    with server.db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS resolutions(key TEXT NOT NULL, status TEXT NOT NULL, "
            "note TEXT NOT NULL, at INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT INTO resolutions VALUES(?,?,?,?)", (args.request_key, args.status, args.note, int(time.time()))
        )
        conn.execute("UPDATE requests SET result=? WHERE key=?", (json.dumps(result), args.request_key))
    print("Recorded verified result; no email sent. Reconcile this delivery in Beacon.")


if __name__ == "__main__":
    main()
