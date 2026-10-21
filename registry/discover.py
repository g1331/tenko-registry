"""从 PyPI 或 git 标签发现新版本，追加到插件条目的 versions。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from . import net
from .model import ROOT, load_plugin, now_iso, plugin_files, save_plugin, sorted_versions

PYPI = "https://pypi.org/pypi"


def tenko_api_specifier(requires_dist: list[str] | None) -> str | None:
    for line in requires_dist or []:
        try:
            req = Requirement(line)
        except InvalidRequirement:
            continue
        if req.name.replace("_", "-").lower() != "tenko-api":
            continue
        if req.marker and not req.marker.evaluate({"extra": ""}):
            continue
        return str(req.specifier)
    return None


def _utc(timestamp: str) -> str:
    return datetime.fromisoformat(timestamp).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yank(files: list[dict[str, Any]], now: str) -> dict[str, str] | None:
    for f in files:
        if f.get("yanked"):
            return {"reason": f.get("yanked_reason") or "PyPI 上已撤回", "since": now}
    return None


def _pypi_version(package: str, version: str, files: list[dict[str, Any]], now: str, get_json):
    # 单个版本的 JSON 才带该版本自己的 requires_dist，项目总览只带最新版本的。
    detail = get_json(f"{PYPI}/{package}/{version}/json")
    info = detail["info"]
    return {
        "version": version,
        "pin": {"sha256": sorted({f["digests"]["sha256"] for f in detail["urls"]})},
        "requires_api": tenko_api_specifier(info.get("requires_dist")),
        "requires_python": info.get("requires_python") or None,
        "published_at": min(_utc(f["upload_time_iso_8601"]) for f in detail["urls"]),
        "tested": None,
        "valid": False,
        "yanked": _yank(files, now),
    }


def discover_pypi(entry: dict[str, Any], get_json=net.get_json, now: str | None = None) -> list[str]:
    now = now or now_iso()
    package = entry["source"]["package"]
    releases = get_json(f"{PYPI}/{package}/json")["releases"]
    known = {Version(v["version"]): v for v in entry["versions"]}
    changes: list[str] = []
    for version, files in releases.items():
        try:
            parsed = Version(version)
        except InvalidVersion:
            continue
        if not files:
            continue
        if parsed in known:
            # 只同步 PyPI 侧的撤回；本仓库手动设置的 yanked 不会被清除。
            item = known[parsed]
            if item["yanked"] is None and (yanked := _yank(files, now)):
                item["yanked"] = yanked
                changes.append(f"{version} 已在 PyPI 撤回")
            continue
        entry["versions"].append(_pypi_version(package, version, files, now, get_json))
        changes.append(f"发现新版本 {version}")
    return changes


def discover_git(entry: dict[str, Any], ls_tags=net.git_ls_remote_tags) -> list[str]:
    known = {Version(v["version"]) for v in entry["versions"]}
    changes: list[str] = []
    for tag, commit in ls_tags(entry["source"]["url"]).items():
        match = net.SEMVER_TAG.fullmatch(tag)
        if not match:
            continue
        try:
            parsed = Version(match[1])
        except InvalidVersion:
            continue
        if parsed in known:
            continue
        known.add(parsed)
        entry["versions"].append({
            "version": match[1],
            "pin": {"commit": commit, "tag": tag},
            # git 版本的这三项要等 test 装好后才知道，在此之前为 null。
            "requires_api": None,
            "requires_python": None,
            "published_at": None,
            "tested": None,
            "valid": False,
            "yanked": None,
        })
        changes.append(f"发现新标签 {tag}")
    return changes


def discover_entry(
    entry: dict[str, Any], *, get_json=net.get_json, ls_tags=net.git_ls_remote_tags, now=None
) -> list[str]:
    if entry["source"]["type"] == "pypi":
        changes = discover_pypi(entry, get_json, now)
    else:
        changes = discover_git(entry, ls_tags)
    entry["versions"] = sorted_versions(entry["versions"])
    return changes


def discover(
    plugin_id: str | None = None, root: Path = ROOT, **deps: Any
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """返回 ({id: 变更说明}, {id: 错误})；单个插件失败不影响其他插件。"""

    ids = [plugin_id] if plugin_id else [p.stem for p in plugin_files(root)]
    changed: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for current in ids:
        entry = load_plugin(current, root)
        try:
            changed[current] = changes = discover_entry(entry, **deps)
        except net.NetError as error:
            errors[current] = str(error)
            continue
        if changes:
            save_plugin(current, entry, root)
    return changed, errors
