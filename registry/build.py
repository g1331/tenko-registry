"""校验全部数据并生成 dist/index.json。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .model import (
    ROOT,
    SCHEMA_VERSION,
    categories,
    normalize_dist,
    now_iso,
    plugin_files,
    read_json,
    validate_blocked,
    validate_plugin,
    validate_removed,
    write_json,
)


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("数据校验失败:\n" + "\n".join(f"  - {e}" for e in errors))
        self.errors = errors


def source_key(entry: dict[str, Any]) -> tuple[str, ...]:
    source = entry["source"]
    if source["type"] == "pypi":
        return ("pypi", normalize_dist(source["package"]))
    return ("git", source["url"].removesuffix(".git").lower(), source.get("subdirectory") or "")


def load_all(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    """读取并校验 plugins/ 与 blocked.json，返回 (plugins, blocked)。"""

    errors: list[str] = []
    plugins: dict[str, Any] = {}
    for path in plugin_files(root):
        try:
            plugins[path.stem] = read_json(path)
        except ValueError as error:
            errors.append(f"{path.name}: 不是合法 JSON ({error})")
    blocked = read_json(root / "blocked.json")
    errors += validate_blocked(blocked, root)
    errors += validate_removed(read_json(root / "removed.json"))

    seen: dict[tuple[str, ...], str] = {}
    blocked_dists = {
        normalize_dist(d) for item in blocked.values() if isinstance(item, dict)
        for d in item.get("dists", []) if isinstance(d, str)
    }
    for plugin_id, entry in plugins.items():
        problems = validate_plugin(plugin_id, entry, root)
        errors += problems
        if problems:
            continue
        if plugin_id in blocked:
            errors.append(f"plugins/{plugin_id}.json: 该 ID 已在 blocked.json 中")
        source = entry["source"]
        if source["type"] == "pypi" and normalize_dist(source["package"]) in blocked_dists:
            errors.append(f"plugins/{plugin_id}.json: 分发包 {source['package']} 已被屏蔽")
        key = source_key(entry)
        if key in seen:
            errors.append(f"plugins/{plugin_id}.json: 来源与 {seen[key]} 重复")
        seen[key] = plugin_id
    if errors:
        raise ValidationError(errors)
    return plugins, blocked


def build(out: Path, root: Path = ROOT, generated_at: str | None = None) -> dict[str, Any]:
    plugins, blocked = load_all(root)
    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or now_iso(),
        "categories": categories(root),
        "plugins": {
            plugin_id: {k: v for k, v in entry.items() if not (k == "icon" and v is None)}
            for plugin_id, entry in sorted(plugins.items())
        },
        "blocked": blocked,
    }
    shutil.rmtree(out / "icons", ignore_errors=True)  # 只清理自己生成的内容，不动 out 里的其他文件
    for entry in index["plugins"].values():
        if icon := entry.get("icon"):
            (out / icon).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / icon, out / icon)
    write_json(out / "index.json", index)
    return index
