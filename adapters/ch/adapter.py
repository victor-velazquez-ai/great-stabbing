"""Switzerland adapter — Eurostat CRIM_OFF_CAT all 5 categories at NUTS-0.

BFS (Federal Statistical Office) publishes more granular data by canton
but the Eurostat-harmonised series is the practical near-term source.
"""

from adapters._eurostat_homicide import EurostatHomicideAdapter


class CHAdapter(EurostatHomicideAdapter):
    country = "CH"
