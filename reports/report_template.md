# Day 10 Reliability Report

## 1. Architecture summary

Describe your gateway, circuit breaker, fallback chain, and cache layers.
Include a simple diagram (text/ASCII is fine):

```
User Request
    |
    v
[Gateway] ---> [Cache check] ---> HIT? return cached
    |                                 |
    v                                 v MISS
[Circuit Breaker: Primary] -------> Provider A
    |  (OPEN? skip)
    v
[Circuit Breaker: Backup] --------> Provider B
    |  (OPEN? skip)
    v
[Static fallback message]
```

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | TODO | TODO |
| reset_timeout_seconds | TODO | TODO |
| success_threshold | TODO | TODO |
| cache TTL | TODO | TODO |
| similarity_threshold | TODO | TODO |
| load_test requests | TODO | TODO |

## 3. SLO definitions

Define your target SLOs and whether your system meets them:

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | TODO | TODO |
| Latency P95 | < 2500 ms | TODO | TODO |
| Fallback success rate | >= 95% | TODO | TODO |
| Cache hit rate | >= 10% | TODO | TODO |
| Recovery time | < 5000 ms | TODO | TODO |

## 4. Metrics

Paste or summarize `reports/metrics.json`.

| Metric | Value |
|---|---:|
| availability | TODO |
| error_rate | TODO |
| latency_p50_ms | TODO |
| latency_p95_ms | TODO |
| latency_p99_ms | TODO |
| fallback_success_rate | TODO |
| cache_hit_rate | TODO |
| estimated_cost_saved | TODO |
| circuit_open_count | TODO |
| recovery_time_ms | TODO |

## 5. Cache comparison

Run simulation with cache enabled vs disabled. Fill in both columns:

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---|
| latency_p50_ms | TODO | TODO | TODO |
| latency_p95_ms | TODO | TODO | TODO |
| estimated_cost | TODO | TODO | TODO |
| cache_hit_rate | 0 | TODO | TODO |

## 6. Redis shared cache

Explain why shared cache matters for production:

- Why in-memory cache is insufficient for multi-instance deployments: TODO
- How `SharedRedisCache` solves this: TODO

### Evidence of shared state

Show that two separate cache instances can see the same data:

```
# Paste test output or script output showing shared state
TODO
```

### Redis CLI output

```bash
# docker compose exec redis redis-cli KEYS "rl:cache:*"
TODO
```

### In-memory vs Redis latency comparison (optional)

| Metric | In-memory cache | Redis cache | Notes |
|---|---:|---:|---|
| latency_p50_ms | TODO | TODO | |
| latency_p95_ms | TODO | TODO | |

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | All traffic fallback to backup, circuit opens | TODO | TODO |
| primary_flaky_50 | Circuit oscillates, mix of primary and fallback | TODO | TODO |
| all_healthy | All requests via primary, no circuit opens | TODO | TODO |
| (your own scenario) | TODO | TODO | TODO |

## 8. Failure analysis

Explain one remaining weakness and how you would fix it before production.

- What could still go wrong?
- What would you change? (e.g., Redis circuit state, per-user rate limiting, quality SLO)

## 9. Next steps

List 2-3 concrete improvements you would make:

1. TODO
2. TODO
3. TODO
