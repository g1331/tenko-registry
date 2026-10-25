from registry.testrun import Outcome, outside_api_range


def test_api_range_mismatch_is_not_a_failure():
    host = Outcome(host={"tenko": "4.0.0-rc24", "api": "0.3.0", "python": "3.12"})

    assert outside_api_range({"requires_api": "<0.3,>=0.2"}, host)
    assert not outside_api_range({"requires_api": ">=0.3,<0.4"}, host)
    # 范围未知时照常测试，由测试结果决定。
    assert not outside_api_range({"requires_api": None}, host)
    assert not outside_api_range({"requires_api": "<0.3"}, Outcome(host={"api": "unknown"}))


def test_untested_retest_only_runs_new_versions(root, monkeypatch):
    from registry import testrun
    from registry.model import load_plugin, save_plugin

    old = {"version": "1.0.0", "tested": {"at": "2026-10-01T00:00:00Z"}, "valid": True, "yanked": None}
    new = {"version": "1.1.0", "requires_api": ">=0.3", "requires_python": ">=3.11", "tested": None, "valid": False, "yanked": None}
    save_plugin("demo", {"source": {"type": "pypi", "package": "demo"}, "versions": [new, old]}, root)
    ran = []

    def run_test(source, item, **kwargs):
        ran.append(item["version"])
        return Outcome(host={"tenko": "4.0.0", "api": "0.3.0", "python": "3.12"})

    monkeypatch.setattr(testrun, "run_test", run_test)
    testrun.retest(root, tenko_ref="v4.0.0", untested=True)
    testrun.retest(root, tenko_ref="v4.0.0", untested=True)

    assert ran == ["1.1.0"]
    assert load_plugin("demo", root)["versions"][1]["tested"] == old["tested"]
