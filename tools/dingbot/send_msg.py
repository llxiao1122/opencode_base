#!/usr/bin/env python3
"""
铁炉西工班钉钉机器人

用法:
  python3 tools/dingbot/send_msg.py <文本消息>
  python3 tools/dingbot/send_msg.py --md <标题> <消息>
  python3 tools/dingbot/send_msg.py --at-all <消息>
  python3 tools/dingbot/send_msg.py --task <YYYY-MM-DD> <任务描述>
"""

import requests
import json
import sys
import os
import argparse

TOKEN = "871e8ca746a4514807e8c958bf8fdebde00261ff0feba370f73173c967982639"
WEBHOOK_URL = f"https://oapi.dingtalk.com/robot/send?access_token={TOKEN}"
KEYWORD = "助手"


def send_text(content: str, at_mobiles: list = None, at_all: bool = False) -> dict:
    if KEYWORD not in content:
        content = f"【{KEYWORD}】{content}"
    payload = {
        "msgtype": "text",
        "text": {"content": content},
        "at": {"atMobiles": at_mobiles or [], "isAtAll": at_all},
    }
    return _post(payload)


def send_markdown(title: str, text: str, at_mobiles: list = None, at_all: bool = False) -> dict:
    if KEYWORD not in title and KEYWORD not in text:
        title = f"【{KEYWORD}】{title}"
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"atMobiles": at_mobiles or [], "isAtAll": at_all},
    }
    return _post(payload)


def _post(payload: dict) -> dict:
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="钉钉群消息推送")
    parser.add_argument("message", nargs="*", help="消息内容")
    parser.add_argument("--md", nargs=2, metavar=("TITLE", "TEXT"), help="发送 Markdown")
    parser.add_argument("--at-all", nargs="+", help="发送文本并@所有人")
    args = parser.parse_args()

    if args.md:
        result = send_markdown(args.md[0], args.md[1])
    elif args.at_all:
        result = send_text(" ".join(args.at_all), at_all=True)
    elif args.message:
        result = send_text(" ".join(args.message))
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))
