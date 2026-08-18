from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any
from urllib.request import Request, urlopen

PROVIDER = {
    "name": "NOAA/National Weather Service",
    "url": "https://www.weather.gov/documentation/services-web-api",
    "terms_url": "https://www.weather.gov/disclaimer",
}
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def nws_layer(kind: str, latitude: float, longitude: float) -> dict[str, Any]:
    """Return one bounded, official NWS context layer with explicit provenance."""
    key = f"{kind}:{latitude:.4f}:{longitude:.4f}"
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < 300:
        return {**cached[1], "cache": "hit"}
    if kind == "weather-stations":
        point = _fetch_json(f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}")
        url = point.get("properties", {}).get("observationStations")
        if not url:
            raise RuntimeError("NWS did not provide an observation-station endpoint for this location")
        collection = _fetch_json(url)
        features = [_station_feature(feature) for feature in collection.get("features", [])]
    elif kind == "weather-alerts":
        url = f"https://api.weather.gov/alerts/active?point={latitude:.4f},{longitude:.4f}"
        collection = _fetch_json(url)
        features = [_alert_feature(feature) for feature in collection.get("features", []) if feature.get("geometry")]
    else:
        raise ValueError("Unknown context layer")
    retrieved_at = datetime.now(timezone.utc).isoformat()
    result = {
        "type": "FeatureCollection", "features": features,
        "layer": kind, "provider": PROVIDER, "retrieved_at": retrieved_at,
        "source_url": url, "freshness": "current", "cache": "miss",
    }
    _cache[key] = (time.time(), result)
    return result


def _fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={
        "Accept": "application/geo+json, application/ld+json, application/json",
        "User-Agent": "MORNS/0.1 contact=https://github.com/morns-org/morns",
    })
    with urlopen(request, timeout=12) as response:
        return json.load(response)


def _station_feature(feature: dict[str, Any]) -> dict[str, Any]:
    properties = feature.get("properties") or {}
    return {
        "type": "Feature", "geometry": feature.get("geometry"),
        "properties": {
            "id": properties.get("stationIdentifier") or feature.get("id"),
            "name": properties.get("name") or "Weather observation station",
            "type": "weather_station", "provider": PROVIDER["name"],
            "source_url": feature.get("id"),
        },
    }


def _alert_feature(feature: dict[str, Any]) -> dict[str, Any]:
    properties = feature.get("properties") or {}
    return {
        "type": "Feature", "geometry": feature.get("geometry"),
        "properties": {
            "id": properties.get("id") or feature.get("id"),
            "name": properties.get("event") or "Active weather alert",
            "headline": properties.get("headline"), "severity": properties.get("severity"),
            "effective": properties.get("effective"), "expires": properties.get("expires"),
            "type": "weather_alert", "provider": PROVIDER["name"],
            "source_url": properties.get("@id") or feature.get("id"),
        },
    }
