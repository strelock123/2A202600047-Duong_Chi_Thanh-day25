# Day 10 Lab — Reliability Engineering for Production Agents

Build a production-style reliability layer for an LLM agent gateway. The starter repo is intentionally a skeleton: core architecture, interfaces, tests, metric/report format, and TODO zones are provided; students implement the reliability logic.

## Learning goals

By the end, you should be able to:

1. Implement a circuit breaker state machine for unreliable providers.
2. Route requests through a fallback chain with explicit route reasons.
3. Add exact/semantic-style cache behavior with TTL and safety checks.
4. Implement a shared Redis cache for multi-instance deployments using Docker.
5. Capture metrics: availability, error rate, P50/P95/P99 latency, fallback success rate, cache hit rate, recovery time, and estimated cost saved.
6. Produce a reproducible report that can be graded from evidence rather than opinion.

## Time design

Class time is 2 hours, but the lab is designed for 4 hours total.

| Time | Milestone | Deliverable |
|---:|---|---|
| 0–30 min | Setup, run baseline tests, inspect TODOs | test log screenshot |
| 30–75 min | Circuit breaker + fallback routing | state transition log |
| 75–120 min | Metrics + one chaos scenario | `reports/metrics.json` v1 |
| 120–165 min | In-memory cache + TTL/threshold tuning | cache comparison table |
| 165–210 min | Redis shared cache via Docker | Redis tests passing, shared-state evidence |
| 210–240 min | Load test + final report | final report + metrics JSON/CSV |

Strong students should complete the core path in about 2 hours and use the extra time for stretch tasks.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start Redis for shared cache (requires Docker)
make docker-up

# Run tests — some will xfail/skip until you implement TODOs
make test

# Run chaos simulation and generate metrics JSON
make run-chaos

# Generate report from metrics
make report
```

## Repository structure

```
src/reliability_lab/
  circuit_breaker.py   # TODO: complete state machine logic
  gateway.py           # TODO: improve route reasons, cache checks, error handling
  cache.py             # TODO: improve similarity, add false-hit guardrails, implement SharedRedisCache
  providers.py         # FakeLLMProvider — simulates latency/failures/cost (no changes needed)
  metrics.py           # RunMetrics model — add fields if needed
  config.py            # Pydantic config loader (no changes needed)
  chaos.py             # TODO: add named scenarios, compare cache vs no-cache

scripts/
  run_chaos.py         # CLI entry point for chaos simulation
  generate_report.py   # Generates report from metrics JSON

configs/
  default.yaml         # Tweak provider fail rates, CB thresholds, cache settings

tests/
  test_gateway_contract.py    # Gateway response contract
  test_metrics.py             # Percentile and report dict
  test_config.py              # Config loading
  test_todo_requirements.py   # xfail test — passes when you fix false-hit problem
  test_redis_cache.py         # Redis cache tests — skipped if Redis not running

data/
  sample_queries.jsonl  # 5 sample queries with risk labels

docker-compose.yml     # Local Redis for shared cache

reports/
  report_template.md   # Copy this and fill in for your final report
```

---

## How to get the best score: step-by-step guide

### Rubric overview (100 points total)

| Category | Points | What graders look for |
|---|---:|---|
| Circuit breaker & fallback | 25 | Correct 3-state machine, no retry storm, route reasons include provider name + why |
| In-memory cache & cost | 15 | Hit rate measured, cost saved calculated, TTL/threshold justified, false-hit examples shown |
| Redis shared cache | 15 | SharedRedisCache get/set implemented, shared state verified, privacy guardrails, Redis tests pass |
| Observability & metrics | 15 | `metrics.json` has P50/P95/P99, availability, circuit open count, cache metrics, all reproducible |
| Chaos & load testing | 15 | At least 3 named scenarios with pass/fail, recovery evidence, concurrent load attempted |
| Report & code quality | 15 | Report has architecture diagram, config table with justifications, failure analysis, type hints, tests pass |

---

### Phase 1 (0–30 min): Setup and orientation

1. Create venv and install: `pip install -e ".[dev]"`
2. Run `make test` — note which tests pass and which xfail.
3. Run `make run-chaos` — observe baseline `reports/metrics.json`.
4. Read every `TODO(student)` in source files. There are TODOs in:
   - `circuit_breaker.py` (3 TODOs)
   - `gateway.py` (1 TODO)
   - `cache.py` (2 TODOs — ResponseCache improvement + SharedRedisCache implementation)
   - `chaos.py` (1 TODO)
5. Screenshot or save test output — this is your "before" baseline.

**Deliverable:** test log screenshot showing baseline state.

---

### Phase 2 (30–75 min): Circuit breaker + fallback — 25 points

**What to implement in `circuit_breaker.py`:**

- `allow_request()`: Already partially implemented. Verify OPEN → HALF_OPEN transition when timeout elapses.
- `record_success()`: Reset failure count, increment success count. When in HALF_OPEN and success_count >= success_threshold, transition to CLOSED.
- `record_failure()`: Increment failure count, reset success count. In HALF_OPEN: immediately re-open. In CLOSED: open when failure_count >= failure_threshold.

**What to implement in `gateway.py`:**

- Improve route reasons to be specific: e.g., `"primary:gpt4"`, `"fallback:backup_provider"`, `"cache_hit:0.95"` instead of bare `"primary"` or `"fallback"`.
- Add timing around the full `complete()` method so latency includes routing overhead.

**What graders check:**

- Circuit transitions appear in `transition_log` (CLOSED → OPEN → HALF_OPEN → CLOSED cycle).
- No retry storm: when circuit is OPEN, requests fail fast — they do NOT retry the same provider.
- Fallback chain: when primary circuit opens, backup provider serves requests.
- Static fallback message returned when ALL providers fail.

**How to verify:**

```bash
make test  # test_gateway_contract should pass
make run-chaos  # check metrics.json for circuit_open_count > 0
```

**Scoring tips:**
- Add a test that forces primary to fail N times, checks circuit opens, then verifies backup serves.
- Print or log transition_log to show state changes — include this in your report.

---

### Phase 3 (75–120 min): Metrics + first chaos scenario — 20 points

**What to implement in `chaos.py`:**

The current `run_simulation` runs one generic scenario. For full marks, add at least 3 distinct named scenarios:

1. **`primary_timeout_100`**: Set primary fail_rate=1.0. Expect: circuit opens immediately, all traffic goes to backup, fallback success rate near 100%.
2. **`primary_flaky_50`**: Set primary fail_rate=0.5. Expect: circuit oscillates between OPEN and CLOSED, mix of primary and fallback responses.
3. **`cache_stale_candidate`**: Enable cache with low similarity threshold. Run queries, check if semantically different queries get false cache hits.

For each scenario:
- Record metrics separately.
- Set `metrics.scenarios["scenario_name"] = "pass"` or `"fail"` based on expected behavior.
- Calculate `recovery_time_ms` from circuit breaker `transition_log` (time between OPEN → CLOSED transitions).

**What goes in `metrics.json`:**

```json
{
  "total_requests": 100,
  "availability": 0.95,
  "error_rate": 0.05,
  "latency_p50_ms": 195.2,
  "latency_p95_ms": 312.5,
  "latency_p99_ms": 445.1,
  "fallback_success_rate": 0.92,
  "cache_hit_rate": 0.15,
  "circuit_open_count": 3,
  "recovery_time_ms": 2100.0,
  "estimated_cost": 0.0042,
  "estimated_cost_saved": 0.0008,
  "scenarios": {
    "primary_timeout_100": "pass",
    "primary_flaky_50": "pass",
    "cache_stale_candidate": "pass"
  }
}
```

**Scoring tips:**
- Recovery time must be a real number derived from transition_log, not hardcoded.
- More scenarios = higher score. 3 is minimum, 4+ shows depth.
- Each scenario needs evidence: what you expected vs. what happened.

---

### Phase 4 (120–165 min): In-memory cache + tuning — 15 points

**What to implement in `cache.py`:**

- Improve `similarity()`: The baseline uses token overlap (Jaccard). For better scoring:
  - Option A: Use TF-IDF or character n-gram overlap (no external API needed).
  - Option B: Use `numpy` (already a dependency) for simple vector similarity.
  - Option C: Add exact-match fast path + token overlap fallback.

- Add false-hit guardrails:
  - Check if query contains privacy-sensitive keywords (e.g., "balance", "user 123") — skip cache.
  - Check `expected_risk` field from sample queries — high-risk queries should not be cached.

- Fix `test_todo_requirements.py`: The xfail test checks that "refund policy for 2024" and "refund policy for 2026" do NOT match. Your improved similarity must distinguish these.

**What to show in report:**

Create a comparison table:

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---:|
| latency_p50_ms | 195 | 12 | -93.8% |
| latency_p95_ms | 312 | 280 | -10.3% |
| estimated_cost | 0.0042 | 0.0034 | -19.0% |
| cache_hit_rate | 0 | 0.15 | +0.15 |

**How to generate comparison:** Run simulation twice — once with `cache.enabled: false` in config, once with `true`. Capture both metrics.

**Scoring tips:**
- Show at least one false-hit example you caught and how your guardrail prevented it.
- Explain why you chose your similarity_threshold value (e.g., "0.85 gave 3 false hits, 0.92 gave 0").
- TTL justification: explain what TTL you chose and why (freshness vs. hit rate tradeoff).

---

### Phase 5 (165–210 min): Redis shared cache — 15 points

**Prerequisites:** Docker installed and running.

```bash
make docker-up   # starts Redis on localhost:6379
```

**What to implement in `cache.py` → `SharedRedisCache`:**

The class skeleton and Redis connection are provided. You implement `get()` and `set()`:

- **`set()`**: Store the query/response pair as a Redis Hash, with TTL via `EXPIRE`.
  ```python
  key = f"{self.prefix}{self._query_hash(query)}"
  self._redis.hset(key, mapping={"query": query, "response": value})
  self._redis.expire(key, self.ttl_seconds)
  ```

- **`get()`**: Two-step lookup:
  1. **Exact match** — hash the query, try `HGET` on that key directly.
  2. **Similarity scan** — `scan_iter(prefix*)`, fetch each entry's `query` field, compute `ResponseCache.similarity()`, return best match above threshold.
  3. Apply privacy guardrails (`_is_uncacheable`) and false-hit detection (`_looks_like_false_hit`) just like the in-memory cache.

**What graders check:**

- `test_redis_cache.py` passes (all 6 tests):
  - Connection works
  - Set + exact get returns correct value with score 1.0
  - TTL expiry (entry gone after TTL)
  - **Shared state**: two `SharedRedisCache` instances see the same data
  - Privacy queries bypass cache
  - False-hit detection on different years
- Config switch: `backend: redis` in `default.yaml` makes `run-chaos` use Redis cache.
- Cache data visible in Redis: `docker exec -it <container> redis-cli KEYS "rl:cache:*"`

**How to verify:**

```bash
make docker-up                     # start Redis
make test                          # Redis tests should now pass (not skip)
# Switch config to backend: redis
make run-chaos                     # generates metrics using Redis cache
docker compose exec redis redis-cli KEYS "rl:cache:*"   # see cached entries
```

**Scoring tips:**
- The key insight: two separate gateway processes sharing one Redis = shared cache state. Show this in your report.
- Demonstrate shared state by running two `SharedRedisCache` instances in a test or script.
- Explain in your report why shared cache matters for production (horizontal scaling, consistent cache hits).
- Handle the case where Redis is down gracefully — don't crash the gateway.

---

### Phase 6 (210–240 min): Load test + final report — 15 points

**Load test:**

- Increase `load_test.requests` to 200+ in config.
- If you can add concurrency (threading/asyncio), do it — the config has `concurrency: 10` but the starter code runs sequentially. Adding concurrency is a stretch goal but earns extra credit.
- Run under different configs and record results.

**Final report (`reports/final_report.md`):**

Copy `reports/report_template.md` and fill in ALL sections:

1. **Architecture summary** — 2-3 sentences + a simple text diagram showing: User → Gateway → [Cache check] → [Circuit breaker] → Provider A / Provider B → [Static fallback].

2. **Configuration table** — List every config parameter with its value AND your rationale:

   | Setting | Value | Why this value |
   |---|---:|---|
   | failure_threshold | 3 | Low enough to detect failures fast, high enough to avoid false opens from jitter |
   | reset_timeout_seconds | 2 | Matches expected provider recovery time |
   | cache TTL | 300 | 5-min freshness for FAQ-type queries |
   | similarity_threshold | 0.92 | Tested: 0.85 caused false hits on date-sensitive queries |

3. **Metrics table** — Paste from `metrics.json`. Must include ALL required metrics.

4. **Chaos scenario table** — For each scenario: expected behavior, observed behavior, pass/fail.

5. **Cache comparison** — With vs. without cache metrics side by side.

6. **Redis shared cache** — Explain:
   - Why shared cache matters (horizontal scaling, cache consistency across instances).
   - Show evidence: two `SharedRedisCache` instances reading the same cached entry.
   - Include Redis CLI output showing cached keys: `KEYS "rl:cache:*"`.
   - Note any latency difference between in-memory and Redis cache.

7. **Failure analysis** — Pick one remaining weakness in your system and explain:
   - What could still go wrong in production?
   - What would you change? (e.g., "Add per-user rate limiting", "Move circuit state to Redis for multi-instance")

8. **Next steps** — 2-3 concrete improvements (not vague wishes).

**Scoring tips:**
- Reports without quantitative metrics = 0 points for this section.
- Type hints in all your code — run `make typecheck` to verify.
- All tests passing: `make test` should show 0 failures (xfail is OK if you haven't reached that stretch goal).
- Clean code: run `make lint` and fix any issues.

---

## Required final deliverables

Submit a zip or GitHub repo containing:

1. **Source code** — all TODOs completed in `src/reliability_lab/`.
2. **`reports/metrics.json`** — generated by `make run-chaos`, reproducible.
3. **`reports/final_report.md`** — filled-in report with all sections above (including Redis shared cache section).
4. **Test output** — screenshot or log of `make test` passing (with Redis running).
5. **Failure analysis** — in report: one remaining weakness + proposed fix.
6. **`docker-compose.yml`** — included so grader can `docker compose up -d` to start Redis.

The grader should be able to run these commands and reproduce your results:

```bash
pip install -e ".[dev]"
docker compose up -d       # start Redis
make test                  # all tests pass including Redis tests
make run-chaos
make report
```

---

## Stretch goals (extra credit)

These are not required but demonstrate deeper understanding:

- **Concurrency**: Make `run_simulation` use `concurrent.futures.ThreadPoolExecutor` with the `concurrency` config value. Show metrics differ under concurrent load.
- **Redis-backed circuit state**: Store circuit breaker counters in Redis (INCR, EXPIRE) so state is shared across instances — not just cache.
- **Redis graceful degradation**: If Redis is down, fall back to in-memory cache automatically instead of crashing.
- **False-hit analysis**: Log every cache hit with its similarity score. Show examples where high similarity != same intent.
- **Cost-aware routing**: After monthly budget hits 80%, route to cheaper model. At 100%, return cached-only or static fallback.
- **Property-based tests**: Use `hypothesis` to test circuit breaker state transitions are valid under random failure sequences.
- **Prometheus export**: Add `prometheus_client` counters/gauges matching the slide's metric names (`agent_requests_total`, `agent_latency_seconds`, `cache_hits_total`, `circuit_state`).
- **SLO definition**: Define your own SLOs (e.g., availability >= 99%, P95 < 2.5s) and check whether your system meets them. Add a pass/fail SLO table to report.

---

## Common mistakes that lose points

| Mistake | Points lost | How to avoid |
|---|---:|---|
| Report has no numbers, only descriptions | Up to 20 | Always paste actual `metrics.json` values |
| Circuit breaker allows retries when OPEN | Up to 10 | Verify `CircuitOpenError` is raised, not silent retry |
| Cache returns stale/wrong answers without guardrails | Up to 10 | Add privacy check, test with different-intent similar queries |
| Only 1 chaos scenario | Up to 10 | Implement 3+ scenarios with different failure modes |
| No config justification | Up to 5 | Every config value needs a "why" in report |
| Redis tests skipped because Docker not running | Up to 10 | Always `make docker-up` before `make test` |
| SharedRedisCache crashes when Redis is unreachable | Up to 5 | Catch `ConnectionError` in get/set, return graceful fallback |
| Code doesn't run on grader's machine | Up to 15 | Test with fresh venv: `pip install -e ".[dev]" && docker compose up -d && make test && make run-chaos` |
| No type hints | Up to 5 | Run `make typecheck` before submission |
| Report missing architecture diagram | Up to 3 | Even a text/ASCII diagram counts |

## FAQ

**Q: Do I need real API keys?**
A: No. `FakeLLMProvider` simulates everything locally. No API keys needed.

**Q: Can I add more providers in config?**
A: Yes. Add more entries in `configs/default.yaml` under `providers`. The gateway iterates them as fallback chain in order.

**Q: What if my xfail test still fails after I improve similarity?**
A: The `test_todo_requirements.py` test checks that queries with different dates/years are NOT false-hit matched. If it still fails, your similarity threshold or function needs more work. This is a stretch goal — partial credit if you explain the limitation.

**Q: Can I use external libraries?**
A: Yes, but add them to `pyproject.toml` dependencies. The grader will run `pip install -e ".[dev]"`. Common useful additions: `scikit-learn` (TF-IDF), `prometheus_client`, `hypothesis`.

**Q: Do I need Docker installed?**
A: Yes. Redis runs in a Docker container via `docker compose up -d`. If you can't install Docker, you can install Redis natively (`brew install redis` on Mac, `apt install redis-server` on Linux) and update `redis_url` in config if needed.

**Q: What if Redis tests are skipped?**
A: They skip when Redis isn't reachable on `localhost:6379`. Run `make docker-up` first. Check with `docker compose ps` that the Redis container is healthy.

**Q: Can I use a remote Redis instead of local Docker?**
A: Yes — change `redis_url` in `configs/default.yaml` to point to your Redis instance.

**Q: How is the report graded?**
A: Graders run your code, compare `metrics.json` output to your report, check that numbers match and scenarios are reproducible. Discrepancies between report and actual output will lose points.
