# Day 10 Reliability Report

## 1. Architecture summary

The gateway now applies three reliability layers in order: cache lookup, circuit-breaker protected provider routing, and a final static fallback message. The primary provider is attempted first, the backup provider is used when the primary fails or its circuit is open, and successful provider responses are cached when the prompt is safe to cache.

```
User Request
    |
    v
[Gateway]
    |
    v
[Cache check] ---- HIT ----> [Return cached response]
    |
   MISS
    |
    v
[Circuit Breaker: primary] ---> [Primary provider]
    |
   open/fail
    v
[Circuit Breaker: backup] ----> [Backup provider]
    |
   open/fail
    v
[Static fallback message]
```

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Opens quickly after repeated failures without tripping on a single transient error |
| reset_timeout_seconds | 2 | Short enough to probe recovery during the lab's sequential chaos runs |
| success_threshold | 1 | One successful HALF_OPEN probe is enough to close the circuit for this lightweight fake provider |
| cache TTL | 300 | Five minutes fits FAQ and policy-style prompts while keeping data reasonably fresh |
| similarity_threshold | 0.92 | High threshold reduces false semantic hits on date-sensitive prompts |
| load_test requests | 100 per scenario | Enough traffic to expose breaker transitions and fallback behavior in each named scenario |

## 3. SLO definitions

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | 100.00% | Yes |
| Latency P95 | < 2500 ms | 506.25 ms | Yes |
| Fallback success rate | >= 95% | 100.00% | Yes |
| Cache hit rate | >= 10% | 42.25% | Yes |
| Recovery time | < 6000 ms | 2896.82 ms | Yes |

## 4. Metrics

Source: `reports/metrics.json` generated from the Redis-backed run in `configs/redis.yaml`

| Metric | Value |
|---|---:|
| availability | 1.0 |
| error_rate | 0.0 |
| latency_p50_ms | 208.59 |
| latency_p95_ms | 506.25 |
| latency_p99_ms | 533.36 |
| fallback_success_rate | 1.0 |
| cache_hit_rate | 0.4225 |
| estimated_cost_saved | 0.048462 |
| circuit_open_count | 19 |
| recovery_time_ms | 2896.8158960342407 |

## 5. Cache comparison

Comparison runs were executed separately with the same scenarios, once with cache disabled and once with cache enabled.

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---|
| latency_p50_ms | 234.74 | 217.21 | -7.47% |
| latency_p95_ms | 509.42 | 513.57 | +0.81% |
| estimated_cost | 0.197108 | 0.10707 | -45.68% |
| cache_hit_rate | 0.0 | 0.3925 | +0.3925 |

The cache reduced median latency and cut estimated cost almost in half. P95 latency was slightly worse in this run because failure scenarios still force fallback provider calls, so the cache mostly helps repeated safe prompts rather than every tail-latency case.

False-hit guardrails added:

- Privacy-sensitive prompts such as `account balance for user 123` are never cached.
- Different 4-digit values are treated as potential false hits, so `refund policy for 2024` does not match `refund policy for 2026`.
- The false-hit requirement is now satisfied by test behavior: `tests/test_todo_requirements.py` currently `xpassed`.

## 6. Redis shared cache

Why shared cache matters for production:

- In-memory cache is per-process, so horizontally scaled gateway instances miss each other's cached responses.
- Redis allows multiple gateway instances to reuse the same safe cached answers and keeps TTL-based expiry centralized.

Implementation status:

- `SharedRedisCache.get()` and `set()` are implemented in [cache.py](/c:/Users/Admin/Desktop/Thanh%20AI/day_25/2A202600047-Duong_Chi_Thanh-day25/src/reliability_lab/cache.py).
- Exact-match lookup, similarity scan, TTL expiry, privacy bypass, and false-hit logging are all in place.
- Redis failures degrade safely by returning cache miss behavior instead of crashing the gateway.

Runtime evidence in this environment:

- `pytest -q tests/test_redis_cache.py` passed: `6 passed in 1.81s`
- Full suite status with Redis available: `11 passed, 1 xpassed`
- Docker Redis container status: healthy on `localhost:6379`

Shared-state evidence captured from two Redis cache instances:

```text
instance_a_set=shared query
instance_b_get=shared response
score=1.0
```

Redis CLI output:

```bash
$ docker compose exec redis redis-cli KEYS "rl:cache:*"
rl:cache:11956e8badb2
rl:cache:095946136fea
```

In-memory vs Redis comparison from separate chaos runs:

| Metric | In-memory cache | Redis cache | Notes |
|---|---:|---:|---|
| latency_p50_ms | 206.73 | 208.59 | Nearly identical median latency in this small local setup |
| latency_p95_ms | 499.33 | 506.25 | Redis adds a small lookup overhead at tail latency |
| cache_hit_rate | 0.405 | 0.4225 | Shared cache slightly improved hit rate |
| estimated_cost | 0.097732 | 0.097972 | Cost difference was negligible in this run |
| recovery_time_ms | 4713.17 | 2896.82 | Redis-backed run recovered faster in the sampled scenarios |

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | Primary always fails, circuit opens, backup serves traffic | Availability 100%, fallback success 100%, circuit opened 14 times | Pass |
| primary_flaky_50 | Circuit oscillates and backup serves failed primary traffic | Availability 100%, fallback success 100%, recovery time about 4576 ms, circuit opened 4 times | Pass |
| all_healthy | Requests should stay healthy with no circuit opens | Availability 100%, circuit_open_count 0, cache hit rate 79% | Pass |
| cache_stale_candidate | Safe prompts may hit cache but year-sensitive prompts should avoid false hits | Availability 100%, cache hit rate 72%, false-hit rule for year mismatch enforced in tests | Pass |

## 8. Failure analysis

One remaining weakness is that circuit state is still local to each process. In a multi-instance deployment, one instance can open the primary circuit while another instance continues sending traffic to the same failing provider. The next production improvement should move breaker counters and state transitions into Redis so cache state and circuit state are both shared across replicas.

## 9. Next steps

1. Move circuit breaker state into Redis so open and half-open transitions are shared across multiple gateway replicas.
2. Add concurrent load execution using the configured concurrency value to see how the breaker and cache behave under burst traffic rather than sequential requests.
3. Add budget-aware routing so the gateway prefers cheaper providers or cache-only responses when spend crosses a configurable threshold.
