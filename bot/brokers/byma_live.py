"""BYMA: ejecución real pendiente (fase 2).
Opciones: API de InvertirOnline (api.invertironline.com) o PPI. Requiere cuenta habilitada para API.
Mientras tanto, BYMA opera en modo alertas y paper."""


class BymaBroker:
    name = "byma"

    def __init__(self, *a, **kw):
        raise NotImplementedError("Ejecución real en BYMA no implementada aún. Usá modo 'alerts' o 'paper'.")
