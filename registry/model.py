"""仓库数据的读写、通用常量和严格校验。

``plugins/<id>.json`` 与 ``index.json`` 里的 ``plugins[id]`` 形状相同，所以校验
函数同时服务 build 与各个会写数据的命令。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1

PLUGIN_ID = re.compile(r"[a-z][a-z0-9_]*")
BLOCKED_KEY = re.compile(r"[a-z][a-z0-9_-]*")
DIST_PREFIX = "tenko-plugin-"
ICON_PATH = re.compile(r"icons/([a-z][a-z0-9_]*)-([0-9a-f]{8})\.png")
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
TIERS = ("official", "listed")
MAX_DESCRIPTION = 80
MAX_TAGS = 5
MAX_TAG_LENGTH = 16
GITHUB_REPO = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?")


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def builtin_ids(root: Path = ROOT) -> set[str]:
    return set((root / "builtin_ids.txt").read_text(encoding="utf-8").split())


def categories(root: Path = ROOT) -> dict[str, str]:
    """``categories.txt``：每行 ``<ID> <显示名>``，按文件顺序。"""

    lines = (root / "categories.txt").read_text(encoding="utf-8").splitlines()
    return dict(line.split(maxsplit=1) for line in lines if line.strip())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def plugin_files(root: Path = ROOT) -> list[Path]:
    return sorted((root / "plugins").glob("*.json"))


def load_plugin(plugin_id: str, root: Path = ROOT) -> dict[str, Any]:
    path = root / "plugins" / f"{plugin_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"找不到 plugins/{plugin_id}.json")
    return read_json(path)


def save_plugin(plugin_id: str, entry: dict[str, Any], root: Path = ROOT) -> None:
    write_json(root / "plugins" / f"{plugin_id}.json", entry)


def sorted_versions(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按版本号从新到旧排序；同一版本号不应重复出现。"""

    return sorted(versions, key=lambda v: Version(v["version"]), reverse=True)


def is_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def _opt_str(value: Any) -> bool:
    return value is None or is_str(value)


def _check_source(source: Any, err: Any) -> None:
    if not isinstance(source, dict):
        return err("source 必须是对象")
    kind = source.get("type")
    if kind == "pypi":
        package = source.get("package")
        if not is_str(package) or not normalize_dist(package).startswith(DIST_PREFIX):
            err(f"source.package 必须以 {DIST_PREFIX} 开头")
    elif kind == "git":
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            err("source.url 必须是 https 地址")
        if not _opt_str(source.get("subdirectory")):
            err("source.subdirectory 必须是字符串或 null")
    else:
        err("source.type 只能是 pypi 或 git")


def _check_version(item: Any, kind: str, err: Any) -> None:
    if not isinstance(item, dict):
        return err("版本项必须是对象")
    version = item.get("version")
    if not is_str(version):
        return err("version 必须是非空字符串")
    pin = item.get("pin")
    if kind == "pypi":
        hashes = pin.get("sha256") if isinstance(pin, dict) else None
        if not (
            isinstance(hashes, list)
            and hashes
            and all(isinstance(h, str) and SHA256.fullmatch(h) for h in hashes)
        ):
            err("pypi 版本的 pin 必须是 {sha256: [64 位十六进制, ...]}")
    else:
        valid_pin = (
            isinstance(pin, dict)
            and isinstance(pin.get("commit"), str)
            and COMMIT.fullmatch(pin["commit"])
            and is_str(pin.get("tag"))
        )
        if not valid_pin:
            err("git 版本的 pin 必须是 {commit: 40 位十六进制, tag: 字符串}")
    # requires_* 对 git 版本在首次测试前允许为 null；valid 为 true 时必须已知。
    for key in ("requires_api", "requires_python", "published_at"):
        if not _opt_str(item.get(key)):
            err(f"{key} 必须是字符串或 null")
    tested = item.get("tested")
    if tested is not None and not (
        isinstance(tested, dict)
        and all(is_str(tested.get(k)) for k in ("tenko", "api", "python", "at"))
    ):
        err("tested 必须是 null 或含 tenko/api/python/at 的对象")
    if not isinstance(item.get("valid"), bool):
        err("valid 必须是布尔值")
    elif item["valid"] and (
        tested is None or not item.get("requires_api") or not item.get("requires_python")
    ):
        err("valid 为 true 的版本必须已测试，且 requires_api/requires_python 已知")
    yanked = item.get("yanked")
    if yanked is not None and not (
        isinstance(yanked, dict) and is_str(yanked.get("reason")) and is_str(yanked.get("since"))
    ):
        err("yanked 必须是 null 或含 reason/since 的对象")


def validate_plugin(
    plugin_id: str, entry: Any, root: Path = ROOT, *, check_icon_file: bool = True
) -> list[str]:
    """返回错误列表；空列表表示通过。"""

    errors: list[str] = []

    def err(message: str, where: str = "") -> None:
        errors.append(f"plugins/{plugin_id}.json{where}: {message}")

    if not PLUGIN_ID.fullmatch(plugin_id):
        err("插件 ID 必须匹配 ^[a-z][a-z0-9_]*$")
    if plugin_id in builtin_ids(root):
        err("插件 ID 与内置插件冲突")
    if not isinstance(entry, dict):
        return [*errors, f"plugins/{plugin_id}.json: 顶层必须是对象"]

    if not is_str(entry.get("name")):
        err("name 必须是非空字符串")
    description = entry.get("description")
    if not is_str(description) or len(description) > MAX_DESCRIPTION:
        err(f"description 必须是 1 到 {MAX_DESCRIPTION} 个字符的字符串")
    authors = entry.get("authors")
    if not (
        isinstance(authors, list)
        and authors
        and all(
            isinstance(a, dict) and is_str(a.get("name")) and _opt_str(a.get("github"))
            for a in authors
        )
    ):
        err("authors 必须是非空列表，每项含 name，github 可为 null")
    homepage = entry.get("homepage")
    if not isinstance(homepage, str) or not homepage.startswith("https://"):
        err("homepage 必须是 https 地址")
    if not is_str(entry.get("license")):
        err("license 必须是 SPDX 标识符字符串")
    if entry.get("category") not in categories(root):
        err(f"category 只能是 {', '.join(categories(root))} 之一")
    tags = entry.get("tags")
    if not (
        isinstance(tags, list)
        and len(tags) <= MAX_TAGS
        and all(isinstance(t, str) and 0 < len(t) <= MAX_TAG_LENGTH for t in tags)
    ):
        err(f"tags 最多 {MAX_TAGS} 个，每个 1 到 {MAX_TAG_LENGTH} 个字符")
    if entry.get("tier") not in TIERS:
        err(f"tier 只能是 {' 或 '.join(TIERS)}")

    icon = entry.get("icon")
    if icon is not None:
        match = ICON_PATH.fullmatch(icon) if isinstance(icon, str) else None
        if not match or match[1] != plugin_id:
            err(f"icon 必须匹配 icons/{plugin_id}-<8 位十六进制>.png", ".icon")
        elif check_icon_file:
            file = root / icon
            if not file.is_file():
                err(f"图标文件不存在: {icon}")
            elif hashlib.sha256(file.read_bytes()).hexdigest()[:8] != match[2]:
                err(f"图标文件名中的哈希与内容不符: {icon}")

    source = entry.get("source")
    _check_source(source, err)
    kind = source.get("type") if isinstance(source, dict) else None

    versions = entry.get("versions")
    if not isinstance(versions, list):
        err("versions 必须是列表")
        return errors
    parsed: list[Version] = []
    for item in versions:
        _check_version(item, kind, lambda m: err(m, ".versions"))
        try:
            parsed.append(Version(item["version"]))
        except (InvalidVersion, KeyError, TypeError):
            err(f"版本号无法解析: {item.get('version') if isinstance(item, dict) else item!r}")
    if len(parsed) == len(versions) and any(a <= b for a, b in zip(parsed, parsed[1:])):
        err("versions 必须按版本号从新到旧排列且不能重复")
    return errors


def validate_blocked(blocked: Any, root: Path = ROOT) -> list[str]:
    if not isinstance(blocked, dict):
        return ["blocked.json: 顶层必须是对象"]
    errors: list[str] = []
    for key, item in blocked.items():
        where = f"blocked.json[{key}]"
        if not BLOCKED_KEY.fullmatch(key):
            errors.append(f"{where}: 键必须匹配 ^[a-z][a-z0-9_-]*$")
        ok = (
            isinstance(item, dict)
            and is_str(item.get("reason"))
            and is_str(item.get("since"))
            and isinstance(item.get("dists"), list)
            and item["dists"]
            and all(isinstance(d, str) and d.startswith(DIST_PREFIX) for d in item["dists"])
        )
        if not ok:
            errors.append(f"{where}: 需要 reason、since 和非空的 dists（均以 {DIST_PREFIX} 开头）")
    return errors


def validate_removed(removed: Any) -> list[str]:
    ok = isinstance(removed, list) and all(
        isinstance(i, dict) and all(is_str(i.get(k)) for k in ("id", "reason", "at"))
        for i in removed
    )
    return [] if ok else ["removed.json: 必须是 [{id, reason, at}, ...] 列表"]
