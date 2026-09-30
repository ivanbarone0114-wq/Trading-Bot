"""Sentimiento de noticias vía Google News RSS + léxico simple ES/EN.
Es un filtro grueso, no un modelo: sirve para no operar contra titulares muy negativos/positivos."""
from urllib.parse import quote_plus

POS = ["sube", "suben", "alza", "récord", "record", "rally", "máximo", "maximo", "ganancia", "crece",
       "supera", "aprobación", "aprobacion", "acuerdo", "compra", "optimismo", "rebote", "mejora",
       "surge", "soars", "jumps", "gains", "beats", "upgrade", "bullish", "approval", "rally"]
NEG = ["cae", "caen", "baja", "desplome", "derrumbe", "pérdida", "perdida", "crisis", "default",
       "hackeo", "hack", "fraude", "demanda", "sanción", "sancion", "recesión", "recesion", "venta masiva",
       "pánico", "panico", "plunges", "falls", "drops", "downgrade", "bearish", "lawsuit", "selloff", "crash"]


def headline_score(title: str) -> int:
    t = title.lower()
    s = sum(w in t for w in POS) - sum(w in t for w in NEG)
    return (s > 0) - (s < 0)


def news_sentiment(keywords, max_items=20):
    """Devuelve (score en [-1,1] o None, lista de titulares)."""
    if not keywords:
        return None, []
    try:
        import feedparser
    except ImportError:
        return None, []
    q = quote_plus(" OR ".join(f'"{k}"' if " " in k else k for k in keywords) + " when:3d")
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=AR&ceid=AR:es-419"
    try:
        feed = feedparser.parse(url)
    except Exception:
        return None, []
    titles = [e.title for e in feed.entries[:max_items]]
    if not titles:
        return None, []
    scores = [headline_score(t) for t in titles]
    return sum(scores) / len(scores), titles
