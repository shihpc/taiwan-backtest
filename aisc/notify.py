# -*- coding: utf-8 -*-
"""LINE 推播（Messaging API push，與 taiwan-flow-live-v2 Worker 同一條通道、同一組 secret 名）。

環境變數：LINE_TOKEN（channel access token）、LINE_USER_ID。缺任一→不推、回 False、不報錯。
文字訊息上限 5000 字，超過切段。token 絕不印出。
"""
from __future__ import annotations

import json
import os
import urllib.request

LINE_PUSH = "https://api.line.me/v2/bot/message/push"
MAX_LEN = 4900


def line_ready() -> bool:
    return bool(os.environ.get("LINE_TOKEN")) and bool(os.environ.get("LINE_USER_ID"))


def _chunks(text: str):
    while text:
        yield text[:MAX_LEN]
        text = text[MAX_LEN:]


def push_text(text: str, opener=urllib.request.urlopen) -> bool:
    if not line_ready():
        print("[info] LINE_TOKEN／LINE_USER_ID 未設，略過推播")
        return False
    tok, uid = os.environ["LINE_TOKEN"], os.environ["LINE_USER_ID"]
    msgs = [{"type": "text", "text": t} for t in _chunks(text)][:5]
    body = json.dumps({"to": uid, "messages": msgs}).encode("utf-8")
    req = urllib.request.Request(LINE_PUSH, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    try:
        with opener(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001
        print(f"[warn] LINE push 失敗：{type(e).__name__}")
        return False
