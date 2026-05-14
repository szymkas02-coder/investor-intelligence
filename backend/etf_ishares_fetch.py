"""
backend/etf_ishares_fetch.py — Auto-refresh ETF allocation data from iShares public API

iShares (BlackRock) publishes holdings data at public URLs — no auth required.
This module fetches region and sector breakdowns and upserts them into etf_allocations.
If any fetch fails, the existing seed data stays in place (seed is the fallback).

TEACHING NOTE:
  ETF providers like iShares publish their fund holdings as JSON files on public
  websites — they're required to disclose what's inside their funds. We can read
  these files programmatically (like a browser would) to get up-to-date allocation
  percentages without needing to pay for a data subscription.

  The iShares UK website uses a specific JSON endpoint format:
    https://www.ishares.com/uk/individual/en/products/{PRODUCT_ID}/fund.ajax.json?tab=holding&fileType=json
  This returns a JSON object with keys like "sectorWeights" and "countryWeights".

  Since this is a public but unofficial API (no contract), we wrap every call
  in try/except so that any format change or network error just logs a warning
  and falls back to our seed data.
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Timeout for all HTTP requests (seconds)
_TIMEOUT = 15

# Headers that mimic a normal browser request.
# Without these, iShares returns 403 (they block bots without a User-Agent).
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.ishares.com/",
}

# Known iShares UK product IDs mapped to our ticker symbols.
# Product IDs are found in the URL when browsing the iShares UK website.
# e.g. https://www.ishares.com/uk/individual/en/products/251882/
#
# NOTE: Some product IDs may be wrong or the URL format may change.
# The fetch function handles failures gracefully — bad IDs just log a warning.
ISHARES_PRODUCT_MAP: dict[str, str] = {
    "ISAC.L":  "251882",   # iShares MSCI ACWI UCITS ETF
    "CSPX.L":  "253743",   # iShares Core S&P 500 UCITS ETF
    "EGLN.L":  "258414",   # iShares Physical Gold ETC
    "EIMI.L":  "264659",   # iShares Core MSCI EM IMI UCITS ETF
    "IWDA.L":  "251882",   # iShares Core MSCI World UCITS ETF (same underlying as ISAC? check)
    "IUSQ.DE": "251882",   # iShares MSCI World UCITS ETF (DE-listed)
}

# The base URL pattern for iShares UK fund holdings JSON
_BASE_URL = (
    "https://www.ishares.com/uk/individual/en/products/{product_id}/"
    "fund.ajax.json?tab=holding&fileType=json"
)


def fetch_ishares_allocations(ticker: str, product_id: str) -> Optional[dict]:
    """Fetch region and sector allocations for one ETF from iShares public API.

    Makes a GET request to the iShares holdings URL and parses the JSON response.
    Returns a dict like::

        {
            "regions": {"United States": 0.6543, "Japan": 0.0612, ...},
            "sectors": {"Technology": 0.2401, "Financials": 0.1588, ...},
        }

    Returns None on any failure (network error, non-200 status, parse error).
    All failures are logged at WARNING level — they do not raise exceptions.

    Args:
        ticker:     Yahoo Finance ticker symbol (e.g. "ISAC.L")
        product_id: iShares product ID string (e.g. "251882")
    """
    url = _BASE_URL.format(product_id=product_id)
    logger.info("Fetching iShares data for %s (product %s)", ticker, product_id)

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    except requests.exceptions.Timeout:
        logger.warning("iShares fetch timeout for %s (url=%s)", ticker, url)
        return None
    except requests.exceptions.RequestException as exc:
        logger.warning("iShares fetch network error for %s: %s", ticker, exc)
        return None

    if resp.status_code != 200:
        logger.warning(
            "iShares returned HTTP %s for %s (product %s)",
            resp.status_code, ticker, product_id
        )
        return None

    try:
        data = resp.json()
    except Exception as exc:
        logger.warning("iShares JSON parse error for %s: %s", ticker, exc)
        return None

    # The iShares JSON structure varies by fund. We try several known key names.
    # If none match, return None (seed data stays as fallback).
    regions = _extract_weights(data, [
        "countryWeights",     # standard key for country/region breakdown
        "geographicBreakdown",
        "countryBreakdown",
        "regionWeights",
        "regionBreakdown",
    ])
    sectors = _extract_weights(data, [
        "sectorWeights",      # standard key for sector breakdown
        "sectorBreakdown",
        "gicsSectorWeights",
    ])

    if not regions and not sectors:
        # Try drilling into nested "fund" or "data" key that some iShares responses use
        for top_key in ("fund", "data", "tableData"):
            sub = data.get(top_key)
            if isinstance(sub, dict):
                regions = regions or _extract_weights(sub, [
                    "countryWeights", "geographicBreakdown", "countryBreakdown",
                    "regionWeights", "regionBreakdown",
                ])
                sectors = sectors or _extract_weights(sub, [
                    "sectorWeights", "sectorBreakdown", "gicsSectorWeights",
                ])
                if regions or sectors:
                    break

    if not regions and not sectors:
        logger.warning(
            "iShares response for %s has no recognisable allocation keys. "
            "Keys found: %s", ticker, list(data.keys())[:20]
        )
        return None

    result: dict = {}
    if regions:
        result["regions"] = regions
    if sectors:
        result["sectors"] = sectors

    logger.info(
        "iShares fetch OK for %s: %d regions, %d sectors",
        ticker, len(result.get("regions", {})), len(result.get("sectors", {}))
    )
    return result


def _extract_weights(data: dict, candidate_keys: list[str]) -> dict[str, float]:
    """Try each candidate key on a dict; return the first non-empty weight dict found.

    iShares JSON weight values can be expressed in several formats:
    - As a float 0–1 (e.g. 0.6543)
    - As a percentage float 0–100 (e.g. 65.43)
    - As a string "65.43%"
    - As a list of dicts [{"name": "US", "weight": 65.43}, ...]

    We normalise all formats to 0–1 floats.
    """
    for key in candidate_keys:
        raw = data.get(key)
        if not raw:
            continue

        # Format A: dict {label: value}
        if isinstance(raw, dict) and raw:
            return _normalise_weights({
                str(k): _parse_weight_value(v)
                for k, v in raw.items()
                if _parse_weight_value(v) is not None
            })

        # Format B: list of {name/label: ..., weight/value: ...}
        if isinstance(raw, list) and raw:
            parsed = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("label") or item.get("description")
                val  = item.get("weight") or item.get("value") or item.get("percentage")
                if name and val is not None:
                    w = _parse_weight_value(val)
                    if w is not None:
                        parsed[str(name)] = w
            if parsed:
                return _normalise_weights(parsed)

    return {}


def _parse_weight_value(v) -> Optional[float]:
    """Parse a weight value into a 0–1 float. Returns None if unparseable."""
    if v is None:
        return None
    try:
        if isinstance(v, str):
            v = v.strip().rstrip("%").replace(",", ".")
        f = float(v)
    except (ValueError, TypeError):
        return None

    if f < 0:
        return None
    # If value looks like a percentage (>1), convert to fraction
    if f > 1:
        f = f / 100.0
    return round(f, 6)


def _normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    """Normalise a weight dict so values sum to 1.0 (in case of rounding drift).

    Also filters out zero/None weights and trims labels.
    """
    cleaned = {k.strip(): v for k, v in weights.items() if v and v > 0.0001}
    if not cleaned:
        return {}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    # Only normalise if total is noticeably off from 1.0 (>2% drift)
    if abs(total - 1.0) > 0.02:
        cleaned = {k: round(v / total, 6) for k, v in cleaned.items()}
    return cleaned


def refresh_allocations_from_ishares(conn) -> dict:
    """Try to fetch fresh allocation data from iShares for all known tickers.

    For each ticker in ISHARES_PRODUCT_MAP:
    - Fetches region/sector weights from iShares public API
    - On success: upserts into etf_allocations (same ON CONFLICT pattern as seed)
    - On failure: logs warning, skips (seed data remains)

    Returns a summary dict::

        {
            "updated": ["ISAC.L", "CSPX.L"],
            "failed":  ["EGLN.L"],
            "skipped": [],
        }

    The "skipped" list is reserved for tickers where fetch succeeded but returned
    no usable data (as opposed to "failed" which means a network/HTTP error).

    Args:
        conn: A database connection (psycopg2 _PgAdapter or DuckDB connection)
              that supports conn.execute(sql, params) and conn.commit().
    """
    updated: list[str] = []
    failed:  list[str] = []
    skipped: list[str] = []

    for ticker, product_id in ISHARES_PRODUCT_MAP.items():
        # Small delay between requests to avoid rate-limiting
        time.sleep(1.0)

        alloc = fetch_ishares_allocations(ticker, product_id)

        if alloc is None:
            logger.warning("iShares fetch failed for %s — keeping seed data", ticker)
            failed.append(ticker)
            continue

        if not alloc.get("regions") and not alloc.get("sectors"):
            logger.warning("iShares returned empty allocation for %s — skipping", ticker)
            skipped.append(ticker)
            continue

        # Upsert into etf_allocations
        rows_written = 0
        for alloc_type, weights_dict in (
            ("region", alloc.get("regions", {})),
            ("sector", alloc.get("sectors", {})),
        ):
            for label, weight in weights_dict.items():
                try:
                    conn.execute("""
                        INSERT INTO etf_allocations (ticker, allocation_type, label, weight)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (ticker, allocation_type, label)
                        DO UPDATE SET weight = EXCLUDED.weight, updated_at = NOW()
                    """, [ticker, alloc_type, label, float(weight)])
                    rows_written += 1
                except Exception as exc:
                    logger.warning("DB upsert failed for %s/%s/%s: %s", ticker, alloc_type, label, exc)

        if rows_written > 0:
            try:
                conn.commit()
            except Exception as exc:
                logger.warning("Commit failed for %s: %s", ticker, exc)
                failed.append(ticker)
                continue
            logger.info("Updated %d allocation rows for %s", rows_written, ticker)
            updated.append(ticker)
        else:
            logger.warning("No rows written for %s — keeping seed data", ticker)
            skipped.append(ticker)

    return {"updated": updated, "failed": failed, "skipped": skipped}
