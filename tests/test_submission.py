from registry import net, testrun
from registry.model import read_json
from registry.submission import Deps, check_submission, official_basis

PACKAGE = "tenko-plugin-demo"
WHEEL, SDIST = "a" * 64, "b" * 64
PROVENANCE = "https://pypi.org/integrity/tenko-plugin-demo/0.1.0/{}/provenance"


def provenance(repository="g1331/tenko-plugins", kind="GitHub"):
    publisher = {"kind": kind, "repository": repository, "workflow": "publish.yml", "environment": "pypi"}
    return {"version": 1, "attestation_bundles": [{"publisher": publisher, "attestations": []}]}


def pypi(wheel=None, sdist=None, *, wheel_provenance=True):
    """模拟 PyPI：项目和版本 JSON、Simple JSON 索引，以及每个文件的来源证明。"""

    wheel = provenance() if wheel is None else wheel
    sdist = provenance() if sdist is None else sdist
    files = [
        {"filename": "demo.whl", "digests": {"sha256": WHEEL}, "upload_time_iso_8601": "2026-11-01T00:00:00Z"},
        {"filename": "demo.tar.gz", "digests": {"sha256": SDIST}, "upload_time_iso_8601": "2026-11-01T00:00:00Z"},
    ]
    responses = {
        f"https://pypi.org/pypi/{PACKAGE}/json": {
            "info": {"project_urls": {"Repository": "https://github.com/g1331/tenko-plugins"}},
            "releases": {"0.1.0": files},
        },
        f"https://pypi.org/pypi/{PACKAGE}/0.1.0/json": {
            "info": {"requires_dist": ["tenko-api>=0.4,<0.5"], "requires_python": ">=3.11"},
            "urls": files,
        },
        f"https://pypi.org/simple/{PACKAGE}/": {
            "files": [
                {
                    "filename": "demo.whl",
                    "hashes": {"sha256": WHEEL},
                    "provenance": PROVENANCE.format("demo.whl") if wheel_provenance else None,
                },
                {"filename": "demo.tar.gz", "hashes": {"sha256": SDIST}, "provenance": PROVENANCE.format("demo.tar.gz")},
            ]
        },
        PROVENANCE.format("demo.whl"): wheel,
        PROVENANCE.format("demo.tar.gz"): sdist,
    }

    def get_json(url, headers=None):
        if url not in responses:
            raise net.NetError(f"404 {url}")
        return responses[url]

    return get_json


def version():
    return {"version": "0.1.0", "pin": {"sha256": [WHEEL, SDIST]}}


def basis(root, get_json, source=None):
    source = source or {"type": "pypi", "package": PACKAGE}
    return official_basis(source, version(), "g1331/tenko-plugins", root, Deps(get_json=get_json))


def test_pypi_package_published_by_an_official_repo_is_official(root):
    assert basis(root, pypi()) == "PyPI 来源证明显示由 g1331/tenko-plugins 发布"
    # 名单比较不分大小写
    assert basis(root, pypi(provenance("G1331/Tenko-Plugins"), provenance("g1331/tenko-plugins")))


def test_every_file_must_come_from_an_official_repo(root):
    # 项目链接谁都能写成官方仓库，只认来源证明
    assert basis(root, pypi(sdist=provenance("someone/fork"))) is None
    assert basis(root, pypi(wheel_provenance=False)) is None
    assert basis(root, pypi(wheel=provenance(kind="GitLab"))) is None
    assert basis(root, pypi(wheel={"attestation_bundles": []})) is None


def test_git_source_is_official_when_the_repo_is_listed(root):
    git = {"type": "git", "url": "https://github.com/g1331/tenko-plugins", "subdirectory": None}
    assert official_basis(git, version(), "g1331/tenko-plugins", root, Deps()) == (
        "来源仓库 g1331/tenko-plugins 在官方名单中"
    )
    assert official_basis(git, version(), "someone/tenko-plugins", root, Deps()) is None


def run_check(root, get_json):
    probe = {
        "id": "demo",
        "dist": PACKAGE,
        "license": "MIT",
        "requires_python": ">=3.11",
        "requires_dist": ["tenko-api>=0.4,<0.5"],
        "project_urls": {"Repository": "https://github.com/g1331/tenko-plugins"},
        "metadata": {"name": "示例", "description": "一个示例插件", "author": ["13"]},
    }
    outcome = testrun.Outcome(probe=probe, host={"tenko": "4.0.0", "api": "0.4.2", "python": "3.12"})
    deps = Deps(get_json=get_json, run_test=lambda *args, **kwargs: outcome)
    return check_submission(PACKAGE, "g1331", category="娱乐", root=root, deps=deps)


def test_submission_records_the_tier_and_says_why(root):
    report = run_check(root, pypi())
    assert report.failure is None, report.failure
    assert read_json(root / "plugins" / "demo.json")["tier"] == "official"
    assert "| 等级 | 官方（PyPI 来源证明显示由 g1331/tenko-plugins 发布） |" in report.markdown()


def test_community_package_stays_listed(root):
    report = run_check(root, pypi(provenance("someone/demo"), provenance("someone/demo")))
    assert report.failure is None, report.failure
    assert read_json(root / "plugins" / "demo.json")["tier"] == "listed"
    assert "| 等级 | 社区收录 |" in report.markdown()


def test_unreadable_provenance_does_not_block_the_submission(root):
    get_json = pypi()

    def flaky(url, headers=None):
        if "/integrity/" in url:
            raise net.NetError("503")
        return get_json(url, headers)

    report = run_check(root, flaky)
    assert report.failure is None, report.failure
    assert read_json(root / "plugins" / "demo.json")["tier"] == "listed"
    assert any("来源证明" in note for note in report.notes)
