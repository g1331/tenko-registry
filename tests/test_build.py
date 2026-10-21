import json

import pytest

from registry.build import ValidationError, build
from registry.model import write_json
from tests.conftest import png_bytes, sha8

ENTRY = {
    "name": "示例插件",
    "description": "一个示例",
    "authors": [{"name": "you", "github": "you"}],
    "homepage": "https://github.com/you/tenko-plugin-example",
    "license": "MIT",
    "tags": ["工具"],
    "tier": "listed",
    "icon": None,
    "source": {"type": "pypi", "package": "tenko-plugin-example"},
    "versions": [
        {
            "version": "0.2.0",
            "pin": {"sha256": ["a" * 64]},
            "requires_api": ">=0.2,<1",
            "requires_python": ">=3.11",
            "published_at": "2026-10-02T00:00:00Z",
            "tested": {"tenko": "4.0.0", "api": "0.2.0", "python": "3.12", "at": "2026-10-03T00:00:00Z"},
            "valid": True,
            "yanked": None,
        },
        {
            "version": "0.1.0",
            "pin": {"sha256": ["b" * 64]},
            "requires_api": ">=0.2,<1",
            "requires_python": ">=3.11",
            "published_at": "2026-10-01T00:00:00Z",
            "tested": None,
            "valid": False,
            "yanked": None,
        },
    ],
}


def put(root, plugin_id, entry, icon_bytes=None, icon_hash=None):
    entry = dict(entry)
    if icon_bytes:
        entry["icon"] = f"icons/{plugin_id}-{icon_hash or sha8(icon_bytes)}.png"
        (root / entry["icon"]).write_bytes(icon_bytes)
    write_json(root / "plugins" / f"{plugin_id}.json", entry)


def test_build_writes_index_and_copies_icons(root, tmp_path):
    png = png_bytes((128, 128))
    put(root, "example", ENTRY, png)
    out = tmp_path / "dist"

    build(out, root, generated_at="2026-10-21T00:00:00Z")

    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["schema_version"] == 1 and index["generated_at"] == "2026-10-21T00:00:00Z"
    assert index["blocked"] == {}
    plugin = index["plugins"]["example"]
    assert [v["version"] for v in plugin["versions"]] == ["0.2.0", "0.1.0"]
    assert (out / plugin["icon"]).read_bytes() == png


def test_build_omits_null_icon(root, tmp_path):
    put(root, "example", ENTRY)
    index = build(tmp_path / "dist", root)
    assert "icon" not in index["plugins"]["example"]


@pytest.mark.parametrize("case", ["icon_hash", "builtin_id", "version_order"])
def test_build_rejects_invalid_data(root, tmp_path, case):
    png = png_bytes((128, 128))
    if case == "icon_hash":
        put(root, "example", ENTRY, png, icon_hash="00000000")
    elif case == "builtin_id":
        put(root, "status", ENTRY)
    else:
        put(root, "example", {**ENTRY, "versions": ENTRY["versions"][::-1]})
    with pytest.raises(ValidationError):
        build(tmp_path / "dist", root)
