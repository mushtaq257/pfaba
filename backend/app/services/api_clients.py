from typing import Any, Dict, Optional

import requests

from backend.app.config import get_settings

OPEN_METEO_GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"


def fetch_exchange_rates(base_currency: str = "USD") -> Optional[Dict[str, Any]]:
    try:
        api_key = get_settings().exchange_rate_api_key
        if api_key:
            url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/{base_currency}"
        else:
            url = f"https://open.er-api.com/v6/latest/{base_currency}"

        response = requests.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()
        rates = payload.get("conversion_rates") or payload.get("rates")
        if payload.get("result") == "success" and isinstance(rates, dict):
            return rates
    except Exception:
        return None
    return None


def convert_currency(amount: float, from_currency: str, to_currency: str) -> float:
    if from_currency == to_currency:
        return amount

    rates = fetch_exchange_rates(from_currency)
    if not rates:
        return amount

    target_rate = rates.get(to_currency)
    if target_rate is None:
        return amount
    return round(amount * target_rate, 2)


def fetch_geolocation_context(location: Optional[str] = None) -> Dict[str, Any]:
    if not location:
        try:
            response = requests.get("https://ipapi.co/json/", timeout=8)
            response.raise_for_status()
            data = response.json()
            return {
                "city": data.get("city"),
                "country": data.get("country_name"),
                "region": data.get("region"),
                "currency": data.get("currency"),
            }
        except Exception:
            return {"city": None, "country": None, "region": None, "currency": None}

    try:
        params = {"name": location, "count": 1, "language": "en"}
        response = requests.get(OPEN_METEO_GEOCODING_API_URL, params=params, timeout=8)
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results:
            return {"city": location, "country": None, "region": None, "currency": None}
        place = results[0]
        return {
            "city": place.get("name"),
            "country": place.get("country"),
            "region": place.get("admin1"),
            "administrative_area": place.get("admin2"),
            "country_code": place.get("country_code"),
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
            "timezone": place.get("timezone"),
            "population": place.get("population"),
            "currency": None,
            "source": "Open-Meteo Geocoding API",
        }
    except Exception:
        return {"city": location, "country": None, "region": None, "currency": None}


def reverse_geocode_coordinates(latitude: float, longitude: float) -> Dict[str, Any]:
    response = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={
            "format": "jsonv2",
            "lat": latitude,
            "lon": longitude,
            "zoom": 10,
            "addressdetails": 1,
        },
        headers={"User-Agent": "PersonalFinanceBudgetAdvisor/1.0"},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    address = payload.get("address") or {}
    city = (
        address.get("city")
        or address.get("town")
        or address.get("municipality")
        or address.get("state_district")
        or address.get("city_district")
        or address.get("borough")
        or address.get("village")
    )
    locality = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("county")
    )
    country = address.get("country")
    region = address.get("state")
    if not city and not region and not country:
        raise ValueError("Reverse geocoding returned no address details.")

    return {
        "city": city,
        "locality": locality,
        "region": region,
        "country": country,
        "display_name": payload.get("display_name"),
        "latitude": latitude,
        "longitude": longitude,
        "source": "OpenStreetMap Nominatim",
    }
