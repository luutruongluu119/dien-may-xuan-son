# -*- coding: utf-8 -*-
"""Gửi sự kiện chuyển đổi lên Facebook Conversions API (server-side) — đáng
tin hơn Pixel phía trình duyệt vì không bị trình duyệt/AdBlock chặn mất, và
không phụ thuộc JS có chạy được hay không (VD khi swap nội dung qua htmx).

Best-effort: không bao giờ raise lỗi ra ngoài — một khách hàng để lại số điện
thoại phải luôn được lưu thành công dù Facebook có lỗi/chậm hay chưa.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

GRAPH = "https://graph.facebook.com/v23.0"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def normalize_vn_phone(phone: str) -> str:
    """Chuẩn hoá số điện thoại VN về dạng không dấu '+' kèm mã quốc gia
    (VD 0966.09.22.61 -> 84966092261) — đúng định dạng Facebook yêu cầu cho
    user_data.ph trước khi hash."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0"):
        digits = "84" + digits[1:]
    elif not digits.startswith("84"):
        digits = "84" + digits
    return digits


def send_lead_event(pixel_id: str, access_token: str, *, phone: str = "", name: str = "",
                    event_source_url: str = "", client_ip: str = "", user_agent: str = "",
                    fbp: str = "", fbc: str = "", event_id: str = "") -> None:
    """Gửi 1 sự kiện 'Lead' (khách để lại thông tin đặt hàng/nhận ưu đãi)."""
    if not pixel_id or not access_token:
        return
    user_data = {}
    if phone:
        user_data["ph"] = [_sha256(normalize_vn_phone(phone))]
    if name:
        parts = name.strip().split()
        if parts:
            user_data["fn"] = [_sha256(parts[0])]
            if len(parts) > 1:
                user_data["ln"] = [_sha256(parts[-1])]
    if client_ip:
        user_data["client_ip_address"] = client_ip
    if user_agent:
        user_data["client_user_agent"] = user_agent
    if fbp:
        user_data["fbp"] = fbp
    if fbc:
        user_data["fbc"] = fbc

    event = {
        "event_name": "Lead", "event_time": int(time.time()),
        "action_source": "website", "user_data": user_data,
    }
    if event_source_url:
        event["event_source_url"] = event_source_url
    if event_id:
        event["event_id"] = event_id

    body = json.dumps({"data": [event], "access_token": access_token}).encode("utf-8")
    req = urllib.request.Request(
        f"{GRAPH}/{pixel_id}/events", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=8)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        detail = e.read().decode("utf-8", "replace") if isinstance(e, urllib.error.HTTPError) else str(e)
        print(f"[fb_capi] gửi sự kiện Lead thất bại (không ảnh hưởng đơn của khách): {detail[:300]}",
              file=sys.stderr)
