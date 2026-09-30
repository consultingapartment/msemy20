#!/usr/bin/env python3
"""Шинжилгээний тайланг Telegram руу илгээнэ (текст + Excel файл).

    python send_telegram.py reports/latest_daily.txt reports/daily_2026-09-29.xlsx

1-р аргумент : мессеж болгох текст файл
Үлдсэн       : хавсаргах файлууд (Excel)

Орчны хувьсагч (GitHub Secrets):
    TELEGRAM_BOT_TOKEN   BotFather-ээс авсан токен
    TELEGRAM_CHAT_ID     хувийн чат, групп эсвэл сувгийн ID (жишээ: 123456789, -100123..., @channel)
Заавал биш:
    TELEGRAM_API_URL     анхдагч https://api.telegram.org (туршилтад)
    DRY_RUN=1            илгээхгүй, зөвхөн харуулна

Тохируулаагүй бол чимээгүй алгасна. Ижил тайланг давхар илгээхээс сэргийлж
reports/sent.json-д хэш хадгална.
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

LIMIT = 4096  # Telegram-ийн нэг мессежийн дээд урт


def call(url, data, files=None):
    """JSON эсвэл multipart хүсэлт. Алдаа гарвал токенгүй мэдээлэл өгнө."""
    if files:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in data.items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, path in files.items():
            body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{path.name}"\r\n'
                     "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    body_path = Path(sys.argv[1])
    if not body_path.is_file():
        print("Текст файл олдсонгүй:", body_path)
        return 0
    text = body_path.read_text(encoding="utf-8").strip()
    files = [Path(a) for a in sys.argv[2:] if a and Path(a).is_file()]

    if os.environ.get("DRY_RUN") == "1":
        print(text, "\n\nХавсралт:", [f.name for f in files])
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID тохируулаагүй тул Telegram-д илгээхгүй.")
        return 0

    reg = Path(os.environ.get("REPORT_DIR", "reports")) / "sent.json"
    sent = json.loads(reg.read_text()) if reg.exists() else []
    digest = hashlib.sha1((text + "|" + ",".join(f.name for f in files)).encode("utf-8")).hexdigest()
    if digest in sent:
        print("Энэ тайланг өмнө нь илгээсэн тул алгасав.")
        return 0

    api = os.environ.get("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/") + f"/bot{token}"
    try:
        call(api + "/sendMessage", {"chat_id": chat, "text": text[:LIMIT], "disable_web_page_preview": "true"})
        for f in files:
            call(api + "/sendDocument", {"chat_id": chat, "caption": f.name}, {"document": f})
    except urllib.error.HTTPError as e:
        print("Telegram алдаа:", e.code, e.read().decode("utf-8", "replace"))  # токеныг хэвлэхгүй
        return 1
    except (urllib.error.URLError, OSError) as e:
        print("Telegram холболтын алдаа:", type(e).__name__)
        return 1

    sent.append(digest)
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps(sent[-200:]))
    print(f"Telegram руу илгээлээ (текст + {len(files)} файл)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
