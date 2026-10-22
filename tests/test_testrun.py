from registry.testrun import Outcome, outside_api_range


def test_api_range_mismatch_is_not_a_failure():
    host = Outcome(host={"tenko": "4.0.0-rc24", "api": "0.3.0", "python": "3.12"})

    assert outside_api_range({"requires_api": "<0.3,>=0.2"}, host)
    assert not outside_api_range({"requires_api": ">=0.3,<0.4"}, host)
    # 范围未知时照常测试，由测试结果决定。
    assert not outside_api_range({"requires_api": None}, host)
    assert not outside_api_range({"requires_api": "<0.3"}, Outcome(host={"api": "unknown"}))
