"""Concrete subclasses so the runner can import them by ISO code."""

from adapters._eurostat_supplement import EurostatSupplementAdapter


class ITSupplement(EurostatSupplementAdapter):
    country = "IT"


class NLSupplement(EurostatSupplementAdapter):
    country = "NL"
