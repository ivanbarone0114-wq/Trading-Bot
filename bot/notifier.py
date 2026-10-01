"""Notificaciones: consola + Telegram + WhatsApp (CallMeBot).
Canales activos: variable NOTIFY_CHANNELS (por defecto "telegram,whatsapp"); cada uno se usa solo si está configurado."""
import html, os, re, time, requests


def _channels():
    return {c.strip().lower() for c in os.getenv("NOTIFY_CHANNELS", "telegram,whatsapp").split(",") if c.strip()}


def _telegram(text):
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    safe = html.escape(text, quote=False).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    for part in _chunks(safe, 3500):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": part, "parse_mode": "HTML"}, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"Telegram respondió {r.status_code}: {r.text[:150]}")


def _whatsapp(text):
    phone, key = os.getenv("WHATSAPP_PHONE"), os.getenv("WHATSAPP_APIKEY")
    if not (phone and key):
        print("[whatsapp] sin configurar: faltan WHATSAPP_PHONE / WHATSAPP_APIKEY")
        return
    msg = text.replace("<b>", "*").replace("</b>", "*")  # negrita de WhatsApp
    msg = re.sub(r"\b([A-Z0-9]+)\.BA\b", r"\1 (BA)", msg)  # evita que WhatsApp lo tome como link
    for part in _chunks(msg, 700):
        r = requests.get("https://api.callmebot.com/whatsapp.php",
                         params={"phone": phone.strip(), "text": part, "apikey": key.strip()}, timeout=30)
        body = re.sub(r"<[^>]+>", " ", r.text)
        body = re.sub(r"\s+", " ", body).strip()[:200]
        print(f"[whatsapp] código {r.status_code}: {body}")
        if not 200 <= r.status_code < 300:
            raise RuntimeError(f"CallMeBot respondió {r.status_code}")
        time.sleep(5)  # CallMeBot limita mensajes seguidos


def _chunks(text, limit):
    """Corta por líneas completas para no partir una señal a la mitad."""
    parts, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > limit:
            parts.append(cur); cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    if len(parts) > 1:
        parts = [f"{p}\n({i}/{len(parts)})" for i, p in enumerate(parts, 1)]
    return parts


def notify(text):
    print(text.replace("<b>", "").replace("</b>", ""), "\n")
    active = _channels()
    for name, fn in (("telegram", _telegram), ("whatsapp", _whatsapp)):
        if name not in active:
            continue
        try:
            fn(text)
        except Exception as e:
            print(f"[{name}] error: {e}")
