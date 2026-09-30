# Bot de trading — Cripto · EE.UU. · BYMA

Bot modular con tres modos (alertas → paper → live), estrategia de confluencia
(**tendencia EMA + MACD + RSI + velas japonesas + noticias**) filtrada por una
temporalidad mayor, gestión de riesgo y un **asesor** que opina sobre tus decisiones manuales.

> ⚠️ Herramienta educativa y de apoyo. No es asesoramiento financiero. Probá
> semanas en paper antes de arriesgar dinero. **DYOR.**

## 1. Instalación
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # completar claves (Telegram, Binance, Alpaca)
python tests/test_smoke.py  # verificación offline
```

## 2. Comandos
| Comando | Qué hace |
|---|---|
| `python -m bot.main scan` | Analiza la watchlist y manda alertas (no opera) |
| `python -m bot.main run --mode paper` | Opera en la cartera simulada |
| `python -m bot.main run --mode paper --loop 3600` | Igual, cada 1 hora |
| `python -m bot.main status` | Estado de la cartera simulada |
| `python -m bot.main decide --symbol GGAL --market byma --side buy --qty 10 --stop 5800` | Registra tu decisión y te da consejos |
| `... decide ... --execute-paper` | Además la ejecuta en paper |
| `python -m bot.main backtest --symbol BTC/USDT --market crypto` | Backtest con datos reales |
| `python -m bot.main backtest --csv historico.csv` | Backtest con CSV de Investing/TradingView |

Agregá `--offline` (antes del comando) para probar todo con datos sintéticos.

## 3. Cómo decide
Score ponderado en [-1, 1] (pesos en `config.yaml`):
- **Tendencia** (peso 2): precio y EMA20 vs EMA50.
- **MACD** (1.5): cruce en las últimas 3 velas, o signo del histograma.
- **RSI** (1): <30 suma, >70 resta.
- **Velas** (1): martillo, estrella fugaz, envolventes, estrella de la mañana/atardecer (con contexto de tendencia).
- **Noticias** (0.75): titulares de Google News de los últimos 3 días, puntuados por léxico ES/EN.
- **Filtro multi-timeframe**: si la temporalidad mayor va en contra, el score se reduce a la mitad.

BUY si score ≥ 0.35 · SELL (salida) si ≤ -0.35. Stop = 2×ATR, objetivo = 2:1.
Solo posiciones largas (sin cortos).

## 4. Riesgo
1% del capital en riesgo por operación · máx. 20% por activo · máx. 5 posiciones ·
corte al perder 3% en el día · **kill-switch**: crear el archivo `state/STOP` frena todas las compras.

## 5. Pasar a live (cuando decidas)
1. Probar en `paper` varias semanas y revisar `state/journal.csv`.
2. Binance **testnet** y Alpaca **paper** (vienen activados por defecto en `live`).
3. `live.enabled: true` en config **y** correr con `--confirm-live`. Cada orden pide confirmación
   por consola salvo `auto_confirm: true`.
4. Recién entonces: `crypto_testnet: false` / `alpaca_paper: false`.

API keys de Binance: **solo permiso de trading, sin retiros**, y con restricción de IP.

## 6. Notificaciones por WhatsApp (CallMeBot)
1. Agendá el número del bot que figura en callmebot.com (cambia cada tanto, verificalo ahí).
2. Mandale por WhatsApp: `I allow callmebot to send me messages`
3. Te responde con tu APIKEY (puede tardar unos minutos).
4. Completá `WHATSAPP_PHONE` (ej. `+5491112345678`) y `WHATSAPP_APIKEY` en `.env`.

Es gratuito y para uso personal; los mensajes pueden llegar con ~1 min de demora. Si necesitás
algo más robusto, la alternativa es la API oficial de WhatsApp Business (Meta) o Twilio.

## 7. En la nube (GitHub Actions)
El archivo `.github/workflows/bot.yml` corre el bot cada hora en los servidores de GitHub,
sin depender de tu PC. La cartera y la bitácora se guardan en la carpeta `state/` del repositorio.
Tu número y tu clave de WhatsApp van como *secrets* del repositorio, nunca en archivos.
Desde la pestaña Actions podés correrlo a mano y elegir `ciclo`, `reporte` o `ccl`.

## 8. Límites conocidos
- **BYMA**: datos vía Yahoo (`GGAL.BA`), con demora; ejecución real pendiente (fase 2: API de IOL/PPI). Hoy opera en alertas y paper.
- Los stops en live se verifican por software en cada ciclo, no quedan como orden en el exchange: si el bot está apagado, no protegen.
- El sentimiento de noticias es un filtro grueso por palabras clave.
- `yfinance` no es un feed oficial; puede fallar o cambiar.

## 9. Roadmap sugerido
Fase 2: broker BYMA (IOL), variables AR (MEP/CCL, riesgo país, Lecaps) como filtro macro,
stops nativos (OCO), resumen de noticias con IA, dashboard web.
