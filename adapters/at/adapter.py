"""Austria adapter — Eurostat CRIM_OFF_CAT (intentional homicide, NUTS-0)."""

from adapters._eurostat_homicide import EurostatHomicideAdapter


class ATAdapter(EurostatHomicideAdapter):
    country = "AT"
