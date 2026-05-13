from reliability_lab.metrics import RunMetrics, percentile


def test_percentile() -> None:
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 50) == 30
    assert percentile(values, 95) >= 40


def test_report_dict_contains_required_metrics() -> None:
    m = RunMetrics(total_requests=2, successful_requests=1, failed_requests=1, latencies_ms=[100, 200])
    report = m.to_report_dict()
    for key in ["availability", "error_rate", "latency_p50_ms", "latency_p95_ms", "cache_hit_rate"]:
        assert key in report
