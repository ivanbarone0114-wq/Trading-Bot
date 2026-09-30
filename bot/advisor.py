"""Consejos básicos después de que tomás una decisión manual."""


def advise(decision, sig, risk_cfg, capital, held_qty=0.0, news_titles=None, atr_mult=2.0):
    side, price, qty = decision["side"], decision["price"], decision["qty"]
    stop = decision.get("stop")
    tips = []
    if sig.price and abs(price / sig.price - 1) > 0.03:
        tips.append(f"⚠️ Tu precio ({price:,.4f}) difiere {price / sig.price - 1:+.1%} del último cierre ({sig.price:,.4f}). Revisá el dato o usá orden límite.")

    if side == "buy":
        if sig.action == "SELL":
            tips.append(f"⚠️ Comprás contra la señal del sistema (score {sig.score:+.2f}). Confirmá que tu tesis tenga otro fundamento.")
        elif sig.action == "BUY":
            tips.append(f"✅ Tu compra coincide con la señal (score {sig.score:+.2f}).")
        else:
            tips.append(f"➖ Señal neutral (score {sig.score:+.2f}): no hay confluencia técnica clara.")
        if sig.rsi > 70:
            tips.append(f"⚠️ RSI {sig.rsi:.0f}: comprás en sobrecompra; el riesgo de retroceso es mayor. Considerá entrar escalonado.")
        if not stop:
            s = price - atr_mult * sig.atr
            tips.append(f"🛑 No definiste stop. Uno técnico por ATR sería ≈ {s:,.4f} ({(price - s) / price:.1%} abajo).")
            stop = s
        if stop and stop < price:
            risk_amt = (price - stop) * qty
            pct = risk_amt / capital
            lim = risk_cfg["risk_per_trade"]
            if pct > lim:
                ok_qty = capital * lim / (price - stop)
                tips.append(f"⚠️ Arriesgás {pct:.1%} del capital (tu regla: {lim:.0%}). Cantidad sugerida: {ok_qty:,.4f}.")
            else:
                tips.append(f"✅ Riesgo de la operación: {pct:.2%} del capital, dentro de tu regla.")
            if sig.target is None:
                tips.append(f"🎯 Con R:R 2:1, un objetivo razonable sería {price + 2 * (price - stop):,.4f}.")
        if price * qty / capital > risk_cfg["max_position_pct"]:
            tips.append(f"⚠️ La posición es {price * qty / capital:.0%} del capital: concentración alta.")
    else:
        if held_qty <= 0:
            tips.append("ℹ️ No hay posición registrada en este activo: la venta sería en corto (no soportado en spot/BYMA).")
        if sig.action == "BUY":
            tips.append(f"⚠️ Vendés con señal de compra activa (score {sig.score:+.2f}). ¿Es toma de ganancia planificada o miedo?")
        elif sig.action == "SELL":
            tips.append(f"✅ Tu venta coincide con la señal (score {sig.score:+.2f}).")
        if sig.rsi < 30:
            tips.append(f"⚠️ RSI {sig.rsi:.0f}: vendés en sobreventa; suelen darse rebotes técnicos.")
        if 0 < qty < held_qty:
            tips.append("✅ Venta parcial: buena práctica para asegurar ganancia y dejar correr el resto.")

    if news_titles:
        tips.append("📰 Titulares recientes: " + " | ".join(news_titles[:3]))
    tips.append("📝 Decisión registrada en la bitácora. Revisala en 1-2 semanas: ¿se cumplió la tesis?")
    return tips
