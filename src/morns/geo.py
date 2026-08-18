from __future__ import annotations

import csv
from functools import lru_cache
from importlib.resources import files
from io import TextIOWrapper
from zipfile import ZipFile

US_ZCTA_DATASET = {
    "country": "US",
    "vintage": "2025",
    "source": "U.S. Census Bureau ZIP Code Tabulation Area Gazetteer",
    "source_url": "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/",
    "lookup_scope": "five-digit ZCTA representative point",
}


@lru_cache(maxsize=1)
def _zcta_centers() -> dict[str, tuple[float, float]]:
    archive = files("morns").joinpath("data/2025_Gaz_zcta_national.zip")
    with archive.open("rb") as source, ZipFile(source) as zipped:
        filename = zipped.namelist()[0]
        with zipped.open(filename) as raw:
            rows = csv.DictReader(TextIOWrapper(raw, encoding="utf-8"), delimiter="|")
            return {
                row["GEOID"]: (float(row["INTPTLAT"]), float(row["INTPTLONG"]))
                for row in rows
            }


def zcta_center(postal_code: str) -> tuple[float, float] | None:
    """Return the Census representative point for a five-digit ZCTA."""
    return _zcta_centers().get(postal_code)


def location_dataset_info() -> dict[str, str]:
    return dict(US_ZCTA_DATASET)
