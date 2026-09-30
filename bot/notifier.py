"""Notificaciones: consola + Telegram + WhatsApp (CallMeBot). Se activan solo si están configuradas en .env."""
import os, re, time, requests


def _telegram(text):
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=10)


def _whatsapp(text):
    phone, key = os.getenv("WHATSAPP_PHONE"), os.getenv("WHATSAPP_APIKEY")
    if phone and key:
        msg = text.replace("<b>", "*").replace("</b>", "*")  # negrita de WhatsApp
        msg = re.sub(r"\b([A-Z0-9]+)\.BA\b", r"\1 (BA)", msg)  # evita que WhatsApp lo tome como link
        for part in _chunks(msg, 700):
            r = requests.get("https://api.callmebot.com/whatsapp.php",
                             params={"phone": phone, "text": part, "apikey": key}, timeout=20)
            if r.status_code != 200:
                raise RuntimeError(f"CallMeBot respondió {r.status_code}")
            time.sleep(3)  # CallMeBot limita mensajes seguidos


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
    for name, fn in (("telegram", _telegram), ("whatsapp", _whatsapp)):
        try:
            fn(text)
        except Exception as e:
            print(f"[{name}] error: {e}")
