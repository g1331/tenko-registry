import subprocess

import pytest

from registry.testrun import InfraError, Outcome, outside_api_range, run_test


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


def _fake_uv(install_error: str):
    """宿主那几步都成功，装插件时按 install_error 失败。"""

    calls = []

    def runner(cmd, timeout):
        calls.append(cmd)
        failed = "install" in cmd and "-c" in cmd  # 只有装插件这一步带约束文件
        return subprocess.CompletedProcess(cmd, int(failed), "", install_error if failed else "")

    return runner, calls


def test_version_missing_from_the_index_is_retried_then_left_untested():
    error = "Because there is no version of tenko-plugin-demo==1.1.0 and you require ..."
    runner, calls = _fake_uv(error)
    waits = []
    source = {"type": "pypi", "package": "tenko-plugin-demo"}

    with pytest.raises(InfraError, match="下一轮再测"):
        run_test(source, {"version": "1.1.0"}, plugin_id="demo", tenko_ref="v4", runner=runner, sleep=waits.append)

    installs = [c for c in calls if "install" in c and "-c" in c]
    assert len(installs) == 6 and len(waits) == 5
    assert installs[0][-2:] == ["--refresh-package", "tenko-plugin-demo"]


def test_a_real_install_failure_is_not_retried():
    runner, calls = _fake_uv("error: tenko-plugin-demo depends on httpx<0.1, which conflicts")
    waits = []

    outcome = run_test(
        {"type": "pypi", "package": "tenko-plugin-demo"}, {"version": "1.1.0"},
        plugin_id="demo", tenko_ref="v4", runner=runner, sleep=waits.append,
    )

    assert outcome.errors[0].startswith("插件安装失败") and not waits
