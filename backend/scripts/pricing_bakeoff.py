"""Compare pricing provider combinations against verified public cases.

The harness never opens a database session, reserves the per-item budget before
each run, and records only aggregate results and public source domains.

Example:

    uv run python -m scripts.pricing_bakeoff \
      --places google_places,foursquare \
      --search perplexity,tavily,exa \
      --content none,tavily,exa,firecrawl \
      --extraction deterministic,sonar \
      --confirm-matrix --output /tmp/pricing-bakeoff.json
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from app.core.config import settings
from app.core.deps import CurrentUser
from app.services.competitor_prices.competitor_research_service import (
    CompetitorResearchService,
)
from app.services.competitor_prices.schemas import CompetitorPriceResearchRequest
from app.services.competitor_prices.url_utils import canonical_domain

DEFAULT_CASES = Path(__file__).resolve().parents[1] / "evals" / "pricing_bakeoff_cases.json"


@dataclass(frozen=True)
class Pipeline:
    places: str
    search: str
    content: str
    extraction: str

    @property
    def name(self) -> str:
        return f"{self.places}+{self.search}+{self.content}+{self.extraction}"


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    pipeline: str
    passed: bool
    research_status: str
    observed_prices: list[float]
    source_domains: list[str]
    exact_businesses: int
    duration_ms: int
    provider_cost_usd: float
    issue_codes: list[str]
    failure: str | None = None


def _choices(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise SystemExit(f"No eval cases found in {path}")
    return [case for case in cases if isinstance(case, dict)]


def _pipelines(args: argparse.Namespace) -> list[Pipeline]:
    pipelines = [
        Pipeline(*values)
        for values in itertools.product(
            _choices(args.places),
            _choices(args.search),
            _choices(args.content),
            _choices(args.extraction),
        )
    ]
    if len(pipelines) > 1 and not args.confirm_matrix:
        raise SystemExit(
            f"Refusing to run {len(pipelines)} paid combinations without --confirm-matrix."
        )
    return pipelines


def _configure(pipeline: Pipeline) -> None:
    settings.pricing_place_provider = pipeline.places  # type: ignore[assignment]
    settings.pricing_search_provider = pipeline.search  # type: ignore[assignment]
    settings.pricing_content_fallback = pipeline.content  # type: ignore[assignment]
    settings.pricing_extraction_provider = pipeline.extraction  # type: ignore[assignment]
    settings.enable_perplexity_sonar = pipeline.extraction == "sonar"
    settings.enable_deepseek_extraction = pipeline.extraction == "deepseek"


def _evaluate(
    *,
    case: dict[str, Any],
    pipeline: Pipeline,
    response: Any,
    elapsed_ms: int,
    max_item_cost: float,
) -> EvalResult:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    expected_price = float(expected.get("price"))
    tolerance = float(expected.get("tolerance", 0.01))
    expected_domain = str(expected.get("sourceDomain") or "").casefold()
    observations = [
        price
        for competitor in response.competitors
        for price in competitor.prices
        if price.price_min is not None or price.price_max is not None
    ]
    values = sorted(
        {
            round(float(price.price_min if price.price_min is not None else price.price_max), 2)
            for price in observations
        }
    )
    domains = sorted({canonical_domain(price.source_url) for price in observations})
    price_match = any(abs(value - expected_price) <= tolerance for value in values)
    domain_match = not expected_domain or any(
        domain == expected_domain or domain.endswith(f".{expected_domain}")
        for domain in domains
    )
    within_budget = response.metadata.provider_cost_usd <= max_item_cost
    return EvalResult(
        case_id=str(case.get("id") or "unnamed"),
        pipeline=pipeline.name,
        passed=price_match and domain_match and within_budget,
        research_status=response.status,
        observed_prices=values,
        source_domains=domains,
        exact_businesses=response.market_summary.sample_size,
        duration_ms=elapsed_ms,
        provider_cost_usd=response.metadata.provider_cost_usd,
        issue_codes=[issue.code for issue in response.issues],
        failure=None if within_budget else f"Exceeded ${max_item_cost:.2f} item budget.",
    )


async def _run_one(
    case: dict[str, Any], pipeline: Pipeline, max_item_cost: float
) -> EvalResult:
    _configure(pipeline)
    started = perf_counter()
    try:
        request = CompetitorPriceResearchRequest.model_validate(case["request"])
        response = await CompetitorResearchService(db=None).research(
            request,
            CurrentUser(
                user_id="pricing-bakeoff",
                email=None,
                business_id="00000000-0000-0000-0000-00000000ba4e",
                business_name="PulseQ Pricing Eval",
            ),
        )
        return _evaluate(
            case=case,
            pipeline=pipeline,
            response=response,
            elapsed_ms=round((perf_counter() - started) * 1000),
            max_item_cost=max_item_cost,
        )
    except Exception as exc:  # noqa: BLE001 - every provider failure is an eval result
        return EvalResult(
            case_id=str(case.get("id") or "unnamed"),
            pipeline=pipeline.name,
            passed=False,
            research_status="unavailable",
            observed_prices=[],
            source_domains=[],
            exact_businesses=0,
            duration_ms=round((perf_counter() - started) * 1000),
            provider_cost_usd=0.0,
            issue_codes=[],
            failure=f"{exc.__class__.__name__}: {exc}",
        )


async def _main(args: argparse.Namespace) -> int:
    cases = _load_cases(Path(args.cases))
    pipelines = _pipelines(args)
    planned = len(cases) * len(pipelines)
    if planned * args.item_budget_usd > args.eval_budget_usd:
        raise SystemExit(
            f"The {planned}-run matrix reserves ${planned * args.item_budget_usd:.2f}, "
            f"above the ${args.eval_budget_usd:.2f} eval budget."
        )

    results: list[EvalResult] = []
    spent = 0.0
    for pipeline in pipelines:
        for case in cases:
            if spent + args.item_budget_usd > args.eval_budget_usd:
                raise SystemExit("Eval budget exhausted before the next provider call.")
            result = await _run_one(case, pipeline, args.item_budget_usd)
            results.append(result)
            spent += result.provider_cost_usd
            print(
                f"{'PASS' if result.passed else 'FAIL'} {result.pipeline} "
                f"{result.case_id} status={result.research_status} "
                f"cost=${result.provider_cost_usd:.4f} duration={result.duration_ms}ms"
            )

    summary = {
        "budgetUsd": args.eval_budget_usd,
        "itemBudgetUsd": args.item_budget_usd,
        "reportedSpendUsd": round(spent, 4),
        "runs": len(results),
        "passed": sum(result.passed for result in results),
        "failed": sum(not result.passed for result in results),
        "results": [asdict(result) for result in results],
    }
    if args.output:
        Path(args.output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}))
    return 0 if summary["failed"] == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--places", default=settings.pricing_place_provider)
    parser.add_argument("--search", default=settings.pricing_search_provider)
    parser.add_argument("--content", default=settings.pricing_content_fallback)
    parser.add_argument("--extraction", default=settings.pricing_extraction_provider)
    parser.add_argument("--eval-budget-usd", type=float, default=100.0)
    parser.add_argument("--item-budget-usd", type=float, default=0.10)
    parser.add_argument("--confirm-matrix", action="store_true")
    parser.add_argument("--output")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(parse_args())))
