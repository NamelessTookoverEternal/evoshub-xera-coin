"""
Country -> provider routing (decided by the SERVER from the country code; the browser only says which
country the user is in).

Smile ID is tried FIRST for every country. Didit is the fallback: used when Smile ID cannot start a session
for that country, when Smile ID is off, or as a second opinion after Smile ID declined the user
(see kyc_provider.start). AFRICAN_COUNTRIES is kept for reference / an optional restriction.
"""
import os

# ISO 3166-1 alpha-2 codes of the 54 African Union member / UN-recognised African states.
AFRICAN_COUNTRIES = frozenset("""
DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU MA MZ
NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW
""".split())

SMILEID = "smileid"
DIDIT = "didit"
ALL_PROVIDERS = (SMILEID, DIDIT)


def normalise_country(value) -> str:
    code = (value or "").strip().upper()
    return code if len(code) == 2 and code.isalpha() else ""


def _smileid_first_countries():
    """None = Smile ID is tried first for EVERY country (default). If XERA_KYC_SMILEID_COUNTRIES is set
    (comma-separated ISO-2 codes) only those countries go to Smile ID first."""
    raw = os.getenv("XERA_KYC_SMILEID_COUNTRIES", "").strip()
    if not raw:
        return None
    return frozenset(c for c in (normalise_country(x) for x in raw.split(",")) if c)


def preferred_provider(country: str) -> str:
    only = _smileid_first_countries()
    return SMILEID if only is None or country in only else DIDIT


def provider_order(country: str, enabled: list) -> list:
    """Preferred provider first, then any other enabled one as a fallback."""
    first = preferred_provider(country)
    order = [first] + [p for p in ALL_PROVIDERS if p != first]
    return [p for p in order if p in enabled]
