"""Norway adapter — Eurostat CRIM_OFF_CAT (intentional homicide, NUTS-0).

SSB (Statistics Norway) publishes more granular data via PXweb but the
Eurostat-harmonised series is the practical near-term source.
"""

from adapters._eurostat_homicide import EurostatHomicideAdapter


class NOAdapter(EurostatHomicideAdapter):
    country = "NO"
