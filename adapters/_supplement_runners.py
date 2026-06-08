"""Concrete subclasses so the runner can import them by ISO code.

Every country that has only sub-national data needs a supplement so the
homepage map's NUTS-0 fallback works. Plus a few that supplement-cover
specific gaps even though they have native NUTS-0 (cheap and consistent).
"""

from adapters._eurostat_supplement import EurostatSupplementAdapter


# Countries whose native adapter publishes only sub-national rows
class UKSupplement(EurostatSupplementAdapter):
    country = "UK"


class FRSupplement(EurostatSupplementAdapter):
    country = "FR"


class ESSupplement(EurostatSupplementAdapter):
    country = "ES"


class DKSupplement(EurostatSupplementAdapter):
    country = "DK"


class NLSupplement(EurostatSupplementAdapter):
    country = "NL"


class ITSupplement(EurostatSupplementAdapter):
    country = "IT"
