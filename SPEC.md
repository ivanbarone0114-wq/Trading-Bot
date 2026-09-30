# Especificación (formato EARS)

## Ubicuos
- R1. El sistema deberá calcular EMA, RSI, MACD, ATR y patrones de velas sobre OHLCV de cripto, EE.UU. y BYMA.
- R2. El sistema deberá registrar toda alerta, decisión y operación en `state/journal.csv`.
- R3. El sistema deberá incluir la advertencia "No es consejo financiero. DYOR." en cada alerta.

## Dirigidos por evento
- R4. Cuando el score sea ≥ umbral, el sistema deberá emitir una señal BUY con stop (2×ATR) y objetivo (R:R 2).
- R5. Cuando el score sea ≤ -umbral y exista posición, el sistema deberá cerrarla (paper/live).
- R6. Cuando el precio toque stop u objetivo de una posición, el sistema deberá cerrarla.
- R7. Cuando el usuario registre una decisión (`decide`), el sistema deberá devolver consejos de coherencia con la señal, riesgo, concentración, RSI y noticias.

## Dependientes de estado
- R8. Mientras el modo sea `alerts`, el sistema no deberá enviar órdenes.
- R9. Mientras exista `state/STOP` o se supere la pérdida diaria máxima, el sistema no deberá abrir posiciones.

## Comportamiento no deseado
- R10. Si `live.enabled` no es true o falta `--confirm-live`, el sistema deberá abortar el modo live.
- R11. Si falla la descarga de datos de un activo, el sistema deberá registrarlo y continuar con el resto.
- R12. Si la temporalidad mayor contradice la señal, el sistema deberá reducir el score a la mitad.

## Opcionales
- R13. Donde estén configurados TELEGRAM_TOKEN y TELEGRAM_CHAT_ID, el sistema deberá enviar alertas por Telegram.
