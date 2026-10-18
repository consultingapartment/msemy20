#!/usr/bin/env python3
"""Шинжилгээний тайланг Telegram руу ЭГ НЭГ мессежээр илгээнэ (хэсэглэхгүй).

    python send_telegram.py reports/latest_daily.txt
    python send_telegram.py reports/latest_weekly.txt --photo reports/latest_weekly.png --caption reports/latest_weekly_caption.txt

--photo өгвөл зургийг (товч тайлбартай) илгээнэ. Зураг илгээж чадахгүй бол текст тайланг нөөцөөр илгээнэ.

Орчны хувьсагч (GitHub Secrets):
    TELEGRAM_BOT_TOKEN   BotFather-ээс авсан токен
    TELEGRAM_CHAT_ID     хувийн чат, групп эсвэл сувгийн ID (жишээ: 123456789, -100123..., @channel)
Заавал биш:
    TELEGRAM_API_URL     анхдагч https://api.telegram.org (туршилтад)
    DRY_RUN=1            илгээхгүй, зөвхөн харуулна
    FORCE_SEND=true      өмнө илгээсэн ч дахин илгээнэ (туршилтад)

Тохируулаагүй бол чимээгүй алгасна. Ижил тайланг давхар илгээхээс сэргийлж
reports/sent.json-д хэш хадгална.
"""
import argparse
import hashlib
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

LIMIT = 4096      # Telegram-ийн нэг мессежийн дээд урт
CAPTION = 1024    # зургийн тайлбарын дээд урт


def fit(text, limit=LIMIT):
    """Тайланг хэсэглэхгүй, нэг мессеж болгоно. Хэтэрвэл сүүлчийн бүтэн догол мөрөөр таслана."""
    if len(text) <= limit:
        return text
    cut = text.rfind("\n\n", 0, limit - 3)
    return text[: cut if cut > 0 else limit - 3].rstrip() + "\n…"


def call(url, data, files=None):
    """JSON эсвэл multipart хүсэлт."""
    if files:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in data.items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, path in files.items():
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{path.name}"\r\n'
                     f"Content-Type: {mime}\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--photo")
    ap.add_argument("--caption")
    a = ap.parse_args()

    body_path = Path(a.text)
    if not body_path.is_file():
        print("Текст файл олдсонгүй:", body_path)
        return 0
    text = body_path.read_text(encoding="utf-8").strip()
    photo = Path(a.photo) if a.photo and Path(a.photo).is_file() else None
    caption = None
    if photo:
        cap_path = Path(a.caption) if a.caption else None
        caption = cap_path.read_text(encoding="utf-8").strip() if cap_path and cap_path.is_file() else text
        caption = fit(caption, CAPTION)

    if os.environ.get("DRY_RUN") == "1":
        print(text, "\n\nЗураг:", photo, "\nТайлбар:", caption)
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID тохируулаагүй тул Telegram-д илгээхгүй.")
        return 0

    reg = Path(os.environ.get("REPORT_DIR", "reports")) / "sent.json"
    sent = json.loads(reg.read_text()) if reg.exists() else []
    h = hashlib.sha1(text.encode("utf-8"))
    if photo:
        h.update(photo.read_bytes())
    digest = h.hexdigest()
    if digest in sent and os.environ.get("FORCE_SEND", "").lower() != "true":
        print("Энэ тайланг өмнө нь илгээсэн тул алгасав. (Дахин илгээх бол Run workflow дээр \"force\"-г сонгоно)")
        return 0

    api = os.environ.get("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/") + f"/bot{token}"
    done = False
    if photo:
        try:
            call(api + "/sendPhoto", {"chat_id": chat, "caption": caption}, {"photo": photo})
            print("Telegram руу зураг илгээлээ")
            done = True
        except urllib.error.HTTPError as e:
            print("Зураг илгээж чадсангүй:", e.code, e.read().decode("utf-8", "replace"), "→ текстээр илгээнэ")
        except (urllib.error.URLError, OSError) as e:
            print("Зураг илгээх холболтын алдаа:", type(e).__name__, "→ текстээр илгээнэ")
    if not done:
        try:
            call(api + "/sendMessage", {"chat_id": chat, "text": fit(text), "disable_web_page_preview": "true"})
            print("Telegram руу текст илгээлээ")
            done = True
        except urllib.error.HTTPError as e:
            print("Telegram алдаа:", e.code, e.read().decode("utf-8", "replace"))  # токеныг хэвлэхгүй
        except (urllib.error.URLError, OSError) as e:
            print("Telegram холболтын алдаа:", type(e).__name__)
    if not done:
        return 1

    sent.append(digest)
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps(sent[-200:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
