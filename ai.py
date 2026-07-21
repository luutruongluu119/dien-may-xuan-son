# -*- coding: utf-8 -*-
"""Gọi Claude API bằng urllib — không cần cài thư viện ngoài, cùng tinh thần
với ai.py của các app khác trong "AGEN MỚI" (seo-studio, script-studio...)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

CLAUDE_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "{model}:generateContent?key={key}")
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-image"


class AIError(Exception):
    pass


def generate(settings: dict, system: str, user: str, messages: list | None = None,
             max_tokens: int = 8192) -> str:
    """Gọi Claude, trả về text thô. Truyền `messages` (list [{role, content}])
    để chat nhiều lượt — mặc định vẫn dùng 1 tin nhắn `user` như trước."""
    key = (settings.get("claude_key") or "").strip()
    if not key:
        raise AIError("Chưa có Claude API key — vào Cài đặt để dán key.")
    model = (settings.get("claude_model") or DEFAULT_CLAUDE_MODEL).strip()
    req = urllib.request.Request(
        CLAUDE_URL,
        data=json.dumps({
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages or [{"role": "user", "content": user}],
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        raise AIError(f"Claude trả lỗi HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise AIError(f"Không kết nối được tới Claude: {e.reason}")
    try:
        return "".join(b.get("text", "") for b in data["content"])
    except (KeyError, TypeError):
        raise AIError(f"Claude trả về dữ liệu lạ: {json.dumps(data)[:400]}")


def generate_image(settings: dict, prompt: str) -> dict:
    """Sinh ảnh minh hoạ bằng Gemini (Nano Banana). Trả về {"mime": "...", "data": "<base64>"}."""
    key = (settings.get("gemini_key") or "").strip()
    if not key:
        raise AIError("Chưa có Gemini API key — vào Cài đặt để dán key.")
    model = (settings.get("gemini_model") or DEFAULT_GEMINI_MODEL).strip()
    req = urllib.request.Request(
        GEMINI_URL.format(model=model, key=key),
        data=json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        raise AIError(f"Gemini trả lỗi HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise AIError(f"Không kết nối được tới Gemini: {e.reason}")
    try:
        cand_parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        raise AIError(f"Gemini trả về dữ liệu lạ: {json.dumps(data)[:400]}")
    for p in cand_parts:
        inline = p.get("inline_data") or p.get("inlineData")
        if inline and inline.get("data"):
            mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
            return {"mime": mime, "data": inline["data"]}
    raise AIError("Gemini không trả về ảnh — thử lại hoặc tự tải ảnh lên.")


def extract_json(text: str) -> dict:
    """Bóc JSON từ câu trả lời của model (bỏ ```json fence nếu có)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise AIError("Model không trả về JSON hợp lệ: " + text[:300])
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIError(f"JSON lỗi ({e}): {text[:300]}")
