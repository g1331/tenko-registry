from registry.discover import discover_entry

# 对应 https://pypi.org/pypi/tenko-plugin-demo/json 及各版本的 JSON（精简后的录制数据）。
def _file(sha, uploaded, **extra):
    return {"digests": {"sha256": sha}, "upload_time_iso_8601": uploaded, **extra}


WHEEL_10 = _file("1" * 64, "2026-09-01T10:00:00.250000Z")
SDIST_10 = _file("2" * 64, "2026-09-01T09:00:00.000000Z")
WHEEL_11 = _file("3" * 64, "2026-10-01T10:00:00.000000Z", yanked=True, yanked_reason="数据库迁移有误")
WHEEL_20 = _file("4" * 64, "2026-10-10T10:00:00.000000Z")

FIXTURES = {
    "https://pypi.org/pypi/tenko-plugin-demo/json": {
        "releases": {"1.0.0": [SDIST_10, WHEEL_10], "1.1.0": [WHEEL_11], "2.0.0rc1": [WHEEL_20], "0.9.0": []},
    },
    "https://pypi.org/pypi/tenko-plugin-demo/1.0.0/json": {
        "info": {"requires_dist": ["sqlalchemy>=2", "tenko-api<0.3,>=0.2"], "requires_python": ">=3.11,<3.14"},
        "urls": [SDIST_10, WHEEL_10],
    },
    "https://pypi.org/pypi/tenko-plugin-demo/1.1.0/json": {
        "info": {"requires_dist": ["tenko-api>=0.2,<0.3"], "requires_python": ">=3.11"},
        "urls": [WHEEL_11],
    },
    "https://pypi.org/pypi/tenko-plugin-demo/2.0.0rc1/json": {
        "info": {"requires_dist": None, "requires_python": None},
        "urls": [WHEEL_20],
    },
}


def test_new_pypi_versions_are_appended_newest_first():
    existing = {"version": "0.8.0", "pin": {"sha256": ["9" * 64]}, "yanked": None, "valid": True}
    entry = {"source": {"type": "pypi", "package": "tenko-plugin-demo"}, "versions": [existing]}

    changes = discover_entry(entry, get_json=FIXTURES.__getitem__, now="2026-10-21T00:00:00Z")

    assert [v["version"] for v in entry["versions"]] == ["2.0.0rc1", "1.1.0", "1.0.0", "0.8.0"]
    assert len(changes) == 3 and entry["versions"][-1] is existing
    v10 = entry["versions"][2]
    assert v10["pin"]["sha256"] == ["1" * 64, "2" * 64]
    assert v10["published_at"] == "2026-09-01T09:00:00Z"  # 取最早上传的文件
    assert v10["requires_api"] == "<0.3,>=0.2" and v10["requires_python"] == ">=3.11,<3.14"
    assert (v10["tested"], v10["valid"], v10["yanked"]) == (None, False, None)
    assert entry["versions"][1]["yanked"] == {"reason": "数据库迁移有误", "since": "2026-10-21T00:00:00Z"}
    assert entry["versions"][0]["requires_api"] is None
