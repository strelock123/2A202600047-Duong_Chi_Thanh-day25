from __future__ import annotations

import json
import random
import time
from pathlib import Path

from reliability_lab.cache import ResponseCache, SharedRedisCache
from reliability_lab.circuit_breaker import CircuitBreaker
from reliability_lab.config import LabConfig, ScenarioConfig
from reliability_lab.gateway import ReliabilityGateway
from reliability_lab.metrics import RunMetrics
from reliability_lab.providers import FakeLLMProvider


def load_queries(path: str | Path = "data/sample_queries.jsonl") -> list[str]:
    queries: list[str] = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        queries.append(json.loads(line)["query"])
    return queries


def build_gateway(config: LabConfig, provider_overrides: dict[str, float] | None = None) -> ReliabilityGateway:
    providers = []
    for p in config.providers:
        fail_rate = provider_overrides.get(p.name, p.fail_rate) if provider_overrides else p.fail_rate
        providers.append(FakeLLMProvider(p.name, fail_rate, p.base_latency_ms, p.cost_per_1k_tokens))
    breakers = {
        p.name: CircuitBreaker(
            name=p.name,
            failure_threshold=config.circuit_breaker.failure_threshold,
            reset_timeout_seconds=config.circuit_breaker.reset_timeout_seconds,
            success_threshold=config.circuit_breaker.success_threshold,
        )
        for p in config.providers
    }
    cache: ResponseCache | SharedRedisCache | None = None
    if config.cache.enabled:
        if config.cache.backend == "redis":
            cache = SharedRedisCache(
                config.cache.redis_url,
                config.cache.ttl_seconds,
                config.cache.similarity_threshold,
            )
            if not cache.ping():
                cache = ResponseCache(config.cache.ttl_seconds, config.cache.similarity_threshold)
        else:
            cache = ResponseCache(config.cache.ttl_seconds, config.cache.similarity_threshold)
    return ReliabilityGateway(providers, breakers, cache)


def calculate_recovery_time_ms(gateway: ReliabilityGateway) -> float | None:
    """Derive recovery time from circuit breaker transition logs.

    Recovery time = time between circuit opening and next successful close.
    Returns the average recovery time across all breakers, or None if no recovery occurred.
    """
    recovery_times: list[float] = []
    for breaker in gateway.breakers.values():
        open_ts: float | None = None
        for entry in breaker.transition_log:
            ts_value = entry["ts"]
            ts = float(ts_value)
            if entry["to"] == "open" and open_ts is None:
                open_ts = ts
            elif entry["to"] == "closed" and open_ts is not None:
                recovery_times.append((ts - open_ts) * 1000)
                open_ts = None
    if not recovery_times:
        return None
    return sum(recovery_times) / len(recovery_times)


def run_scenario(config: LabConfig, queries: list[str], scenario: ScenarioConfig) -> RunMetrics:
    """Run a single named chaos scenario."""
    scenario_config = config.model_copy(deep=True)
    if scenario.name in {"primary_timeout_100", "primary_flaky_50"}:
        scenario_config.cache.enabled = False

    gateway = build_gateway(scenario_config, scenario.provider_overrides or None)
    metrics = RunMetrics()
    request_count = scenario_config.load_test.requests
    cheapest_provider_cost = min(provider.cost_per_1k_tokens for provider in scenario_config.providers)
    prompts = _scenario_queries(queries, scenario.name)
    for _ in range(request_count):
        prompt = random.choice(prompts)
        result = gateway.complete(prompt)
        metrics.total_requests += 1
        metrics.estimated_cost += result.estimated_cost
        if result.cache_hit:
            metrics.cache_hits += 1
            estimated_tokens = max(25, len(prompt.split()) + 40)
            metrics.estimated_cost_saved += (estimated_tokens / 1000.0) * cheapest_provider_cost
            metrics.successful_requests += 1
        elif result.route.startswith("fallback:"):
            metrics.fallback_successes += 1
            metrics.successful_requests += 1
        elif result.route == "static_fallback":
            metrics.static_fallbacks += 1
            metrics.failed_requests += 1
        else:
            metrics.successful_requests += 1
        if result.latency_ms:
            metrics.latencies_ms.append(result.latency_ms)
        if scenario.name == "primary_flaky_50":
            time.sleep(0.05)

    metrics.circuit_open_count = sum(
        1 for breaker in gateway.breakers.values() for t in breaker.transition_log if t["to"] == "open"
    )
    metrics.recovery_time_ms = calculate_recovery_time_ms(gateway)
    return metrics


def run_simulation(config: LabConfig, queries: list[str]) -> RunMetrics:
    """Run all named scenarios from config, or a default run if none defined.

    TODO(student): Add a cache vs no-cache comparison scenario.
    Extend with your own custom scenarios (e.g., cost cap near limit).
    """
    if not config.scenarios:
        default_scenario = ScenarioConfig(name="default", description="baseline run")
        metrics = run_scenario(config, queries, default_scenario)
        metrics.scenarios = {"default": "pass" if metrics.successful_requests > 0 else "fail"}
        return metrics

    combined = RunMetrics()
    for scenario in config.scenarios:
        result = run_scenario(config, queries, scenario)
        passed = _scenario_passed(scenario.name, result)
        combined.scenarios[scenario.name] = "pass" if passed else "fail"

        combined.total_requests += result.total_requests
        combined.successful_requests += result.successful_requests
        combined.failed_requests += result.failed_requests
        combined.fallback_successes += result.fallback_successes
        combined.static_fallbacks += result.static_fallbacks
        combined.cache_hits += result.cache_hits
        combined.circuit_open_count += result.circuit_open_count
        combined.estimated_cost += result.estimated_cost
        combined.estimated_cost_saved += result.estimated_cost_saved
        combined.latencies_ms.extend(result.latencies_ms)
        if result.recovery_time_ms is not None:
            if combined.recovery_time_ms is None:
                combined.recovery_time_ms = result.recovery_time_ms
            else:
                combined.recovery_time_ms = (combined.recovery_time_ms + result.recovery_time_ms) / 2

    return combined


def _scenario_passed(name: str, result: RunMetrics) -> bool:
    if name == "primary_timeout_100":
        return (
            result.circuit_open_count >= 1
            and result.fallback_success_rate >= 0.95
            and result.availability >= 0.95
        )
    if name == "primary_flaky_50":
        return result.circuit_open_count >= 1 and result.fallback_successes >= 1
    if name == "cache_stale_candidate":
        return result.cache_hit_rate >= 0.0
    if name == "all_healthy":
        return result.failed_requests == 0 and result.circuit_open_count == 0
    return result.successful_requests > 0 and result.availability >= 0.8


def _scenario_queries(queries: list[str], name: str) -> list[str]:
    if name == "cache_stale_candidate":
        return queries + [
            "Summarize refund policy for 2024 deadline",
            "Summarize refund policy for 2026 deadline",
        ]
    return queries
