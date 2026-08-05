"""Fail-fast production readiness check for the pricing pipeline.

No secret values are printed. Run from ``backend/`` before a deployment:

    ENVIRONMENT=production uv run python -m scripts.pricing_preflight --json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

from app.core.config import settings


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    message: str


def estimated_worst_case_cost_usd() -> float:
    competitors = max(1, settings.pricing_max_competitors_per_run)
    place_rate = 0.035 if settings.pricing_place_provider == "google_places" else 0.015
    place_calls = 1
    if (
        settings.pricing_place_provider == "google_places"
        and settings.pricing_google_place_details_enabled
    ):
        place_calls += competitors
    search_rate = {"perplexity": 0.005, "tavily": 0.008, "exa": 0.007}[
        settings.pricing_search_provider
    ]
    content_rate = {"none": 0.0, "tavily": 0.0032, "exa": 0.001, "firecrawl": 0.001}[
        settings.pricing_content_fallback
    ]
    ai_rate = 0.0 if settings.pricing_extraction_provider == "deterministic" else 0.012
    return round(
        max(0, settings.pricing_max_geocoding_requests_per_run) * 0.005
        + place_calls * place_rate
        + competitors * search_rate
        + max(0, settings.pricing_max_content_fallbacks_per_run) * content_rate
        + max(0, settings.pricing_max_ai_fallbacks_per_run) * ai_rate,
        4,
    )


def build_checks() -> list[Check]:
    checks: list[Check] = []

    def required(name: str, configured: bool) -> None:
        checks.append(
            Check(
                name=name,
                passed=configured,
                message="configured" if configured else "missing",
            )
        )

    required("GOOGLE_MAPS_SERVER_API_KEY", bool(settings.google_maps_server_api_key))
    if settings.pricing_place_provider == "foursquare":
        required("FOURSQUARE_API_KEY", bool(settings.foursquare_api_key))
    if settings.pricing_search_provider == "perplexity":
        required("PERPLEXITY_API_KEY/search", bool(settings.perplexity_api_key))
    elif settings.pricing_search_provider == "tavily":
        required("TAVILY_API_KEY/search", bool(settings.tavily_api_key))
    else:
        required("EXA_API_KEY/search", bool(settings.exa_api_key))
    if settings.pricing_content_fallback == "tavily":
        required("TAVILY_API_KEY/content", bool(settings.tavily_api_key))
    elif settings.pricing_content_fallback == "exa":
        required("EXA_API_KEY/content", bool(settings.exa_api_key))
    elif settings.pricing_content_fallback == "firecrawl":
        required("FIRECRAWL_API_KEY/content", bool(settings.firecrawl_api_key))
    if settings.pricing_extraction_provider == "sonar":
        required("PERPLEXITY_API_KEY/extraction", bool(settings.perplexity_api_key))
    elif settings.pricing_extraction_provider == "deepseek":
        required(
            "TOKENMART_API_KEY or DEEPSEEK_API_KEY",
            bool(settings.tokenmart_api_key or settings.deepseek_api_key),
        )

    separate_google_key = bool(settings.google_maps_server_api_key) and (
        not settings.google_maps_api_key
        or settings.google_maps_server_api_key != settings.google_maps_api_key
    )
    checks.append(
        Check(
            name="server-key-separation",
            passed=separate_google_key,
            message=(
                "dedicated server credential"
                if separate_google_key
                else (
                    "cannot verify until the server credential is configured"
                    if not settings.google_maps_server_api_key
                    else "server and browser Google keys are identical"
                )
            ),
        )
    )
    worst_case = estimated_worst_case_cost_usd()
    checks.append(
        Check(
            name="per-item-provider-budget",
            passed=worst_case <= settings.pricing_max_provider_cost_usd,
            message=(
                f"estimated ceiling ${worst_case:.4f} / "
                f"configured ${settings.pricing_max_provider_cost_usd:.2f}"
            ),
        )
    )
    checks.append(
        Check(
            name="daily-tenant-quota",
            passed=0 < settings.pricing_daily_fresh_run_limit <= 10,
            message=f"{settings.pricing_daily_fresh_run_limit} fresh runs/day",
        )
    )
    checks.append(
        Check(
            name="scheduled-product-monitoring",
            passed=not settings.pricing_monitoring_enabled,
            message=(
                "disabled until a scheduler is deployed"
                if not settings.pricing_monitoring_enabled
                else "enabled; confirm a worker and scheduler are actually deployed"
            ),
        )
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    checks = build_checks()
    passed = all(check.passed for check in checks)
    payload = {
        "passed": passed,
        "pipeline": {
            "place": settings.pricing_place_provider,
            "search": settings.pricing_search_provider,
            "content": settings.pricing_content_fallback,
            "extraction": settings.pricing_extraction_provider,
        },
        "checks": [asdict(check) for check in checks],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for check in checks:
            print(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.message}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
