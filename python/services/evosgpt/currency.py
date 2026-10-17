"""
Visitor currency for EVOSGPT.

Default is GHS (Ghana cedi). If the visitor's country (from their IP, so a VPN exit
country counts too) uses a different currency, prices are DISPLAYED in that currency.

Important: this is display only. Paystack still charges in GHS (see /upgrade/init), so
the checkout note tells the visitor they are billed in GHS. No exchange rate is ever
invented: if live rates have never been fetched, everyone is shown GHS.
"""
import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_CURRENCY = "GHS"
RATES_URL = "https://open.er-api.com/v6/latest/GHS"   # free, no key
_FRESH_SECONDS = 6 * 3600          # refresh at most every 6 hours
_MAX_STALE_SECONDS = 7 * 24 * 3600  # keep using an old copy for a week if the API is down

_EUR = ("AT BE CY DE EE ES FI FR GR HR IE IT LT LU LV MT NL PT SI SK AD MC SM VA ME XK").split()
_XOF = "BJ BF CI GW ML NE SN TG".split()
_XAF = "CM CF TD CG GQ GA".split()
_XCD = "AG DM GD KN LC VC AI MS".split()

COUNTRY_CURRENCY = {
    # Africa
    "GH": "GHS", "NG": "NGN", "KE": "KES", "ZA": "ZAR", "UG": "UGX", "TZ": "TZS", "RW": "RWF",
    "ET": "ETB", "EG": "EGP", "MA": "MAD", "DZ": "DZD", "TN": "TND", "ZM": "ZMW", "ZW": "USD",
    "BW": "BWP", "NA": "NAD", "MZ": "MZN", "AO": "AOA", "SL": "SLE", "LR": "LRD", "GM": "GMD",
    "GN": "GNF", "MW": "MWK", "MG": "MGA", "MU": "MUR", "SD": "SDG", "SS": "SSP", "SO": "SOS",
    "CD": "CDF", "BI": "BIF", "LY": "LYD", "CV": "CVE", "LS": "LSL", "SZ": "SZL", "SC": "SCR",
    "ER": "ERN", "DJ": "DJF", "KM": "KMF", "MR": "MRU", "ST": "STN",
    # Americas
    "US": "USD", "CA": "CAD", "MX": "MXN", "BR": "BRL", "AR": "ARS", "CL": "CLP", "CO": "COP",
    "PE": "PEN", "VE": "VES", "UY": "UYU", "PY": "PYG", "BO": "BOB", "EC": "USD", "PA": "USD",
    "SV": "USD", "CR": "CRC", "GT": "GTQ", "HN": "HNL", "NI": "NIO", "DO": "DOP", "CU": "CUP",
    "JM": "JMD", "TT": "TTD", "BS": "BSD", "BB": "BBD", "HT": "HTG", "PR": "USD", "GY": "GYD",
    "SR": "SRD", "BZ": "BZD",
    # Europe (non-euro)
    "GB": "GBP", "CH": "CHF", "LI": "CHF", "NO": "NOK", "SE": "SEK", "DK": "DKK", "IS": "ISK",
    "PL": "PLN", "CZ": "CZK", "HU": "HUF", "RO": "RON", "BG": "BGN", "RS": "RSD", "UA": "UAH",
    "RU": "RUB", "BY": "BYN", "MD": "MDL", "AL": "ALL", "MK": "MKD", "BA": "BAM", "GE": "GEL",
    "AM": "AMD", "AZ": "AZN", "TR": "TRY",
    # Middle East & Asia
    "AE": "AED", "SA": "SAR", "QA": "QAR", "KW": "KWD", "BH": "BHD", "OM": "OMR", "JO": "JOD",
    "IL": "ILS", "LB": "LBP", "IQ": "IQD", "IR": "IRR", "SY": "SYP", "YE": "YER",
    "IN": "INR", "PK": "PKR", "BD": "BDT", "LK": "LKR", "NP": "NPR", "BT": "BTN", "MV": "MVR",
    "AF": "AFN", "CN": "CNY", "HK": "HKD", "MO": "MOP", "TW": "TWD", "JP": "JPY", "KR": "KRW",
    "MN": "MNT", "SG": "SGD", "MY": "MYR", "TH": "THB", "VN": "VND", "ID": "IDR", "PH": "PHP",
    "KH": "KHR", "LA": "LAK", "MM": "MMK", "BN": "BND", "KZ": "KZT", "UZ": "UZS", "KG": "KGS",
    "TJ": "TJS", "TM": "TMT",
    # Oceania
    "AU": "AUD", "NZ": "NZD", "FJ": "FJD", "PG": "PGK", "WS": "WST", "TO": "TOP", "VU": "VUV",
    "SB": "SBD",
}
for _c in _EUR: COUNTRY_CURRENCY[_c] = "EUR"
for _c in _XOF: COUNTRY_CURRENCY[_c] = "XOF"
for _c in _XAF: COUNTRY_CURRENCY[_c] = "XAF"
for _c in _XCD: COUNTRY_CURRENCY[_c] = "XCD"

_lock = threading.Lock()
_cache = {"rates": None, "at": 0.0}


def _load_rates() -> Optional[dict]:
    """Rates relative to 1 GHS. Cached; returns None if we have never had any."""
    now = time.time()
    with _lock:
        rates, at = _cache["rates"], _cache["at"]
    if rates and now - at < _FRESH_SECONDS:
        return rates
    try:
        res = requests.get(RATES_URL, timeout=4)
        data = res.json()
        fresh = data.get("rates") if data.get("result") == "success" else None
        if isinstance(fresh, dict) and fresh:
            with _lock:
                _cache["rates"], _cache["at"] = fresh, now
            return fresh
    except Exception as exc:
        logger.warning("EVOSGPT currency: rate fetch failed (%s)", exc)
    if rates and now - at < _MAX_STALE_SECONDS:
        return rates          # API down: an old rate is better than none
    return None


def currency_for_country(country_code: Optional[str]) -> dict:
    """
    {"country": "US", "currency": "USD", "rate": 0.09, "base": "GHS", "converted": True}
    Falls back to GHS / rate 1 when the country is unknown, is Ghana, or no rate is available.
    """
    code = (country_code or "").strip().upper()
    ghs = {"country": code, "currency": BASE_CURRENCY, "rate": 1.0, "base": BASE_CURRENCY, "converted": False}
    target = COUNTRY_CURRENCY.get(code)
    if not target or target == BASE_CURRENCY:
        return ghs
    rates = _load_rates()
    rate = rates.get(target) if rates else None
    if not isinstance(rate, (int, float)) or rate <= 0:
        return ghs            # never show a made-up price
    return {"country": code, "currency": target, "rate": float(rate), "base": BASE_CURRENCY, "converted": True}
