"""在隔离虚拟环境里由 ``test`` 命令直接执行的探针脚本（不属于 registry 包的导入图）。

它只依赖已安装的 Tenko 宿主：按宿主启动的方式加载插件，把检查结果写成 JSON。
加载方式与 examples/tenko-plugin-example/tests/conftest.py 一致。
"""

import argparse
import asyncio
import json
import os
import platform
import re
import sys
import traceback
from importlib.metadata import entry_points, version
from pathlib import Path


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def select_entry(dist, plugin_id, errors):
    found = [
        ep
        for ep in entry_points(group="tenko.plugins")
        if (not dist or (ep.dist and norm(ep.dist.name) == norm(dist)))
        and (not plugin_id or ep.name == plugin_id)
    ]
    if len(found) != 1:
        names = [f"{ep.name}({ep.dist.name if ep.dist else '?'})" for ep in found]
        errors.append(f"应当恰有 1 个 tenko.plugins 入口，实际找到 {len(found)} 个: {names}")
        return None
    return found[0]


def dist_info(ep):
    dist = ep.dist
    meta = dist.metadata
    urls = {}
    for item in meta.get_all("Project-URL") or []:
        label, _, url = item.partition(",")
        urls[label.strip()] = url.strip()
    files = [dist.locate_file(f) for f in dist.files or []]
    return {
        "dist": meta["Name"],
        "version": dist.version,
        "requires_python": meta["Requires-Python"],
        "requires_dist": list(dist.requires or []),
        "license": meta.get("License-Expression") or meta.get("License"),
        "project_urls": urls,
        "size": sum(f.stat().st_size for f in files if f.is_file()),
    }


async def load(plugin_id, root, errors):
    from arclet.entari import Entari
    from arclet.entari.config import EntariConfig
    from tenko.config import DatabaseConfig
    from tenko.db.bootstrap import load_database_plugin
    from tenko.db.migration import run_database_migrations
    from tenko.host.plugins import PluginRuntime, api_incompatibility

    os.chdir(root)
    EntariConfig(root / "entari.yml")
    Entari(ignore_self_message=True)
    (root / "state.json").write_text(json.dumps({"enabled": [plugin_id]}))
    service = load_database_plugin(
        DatabaseConfig(url=f"sqlite+aiosqlite:///{root / 'main.db'}")
    )
    runtime = PluginRuntime(root / "no-builtin", state_file=root / "state.json")
    await runtime.load_all(external_configs={})
    plugin = runtime.loaded_plugins.get(plugin_id)
    if plugin is None:
        errors.append("插件未能加载（宿主日志里有具体原因）")
        return None
    if reason := api_incompatibility(plugin_id):
        errors.append(f"与宿主的 tenko-api 不兼容: {reason}")
    await service.initialize()
    await run_database_migrations(service)
    meta = plugin.metadata
    result = {
        "name": getattr(meta, "name", None),
        "description": getattr(meta, "description", None),
        "author": getattr(meta, "author", None),
        "icon": getattr(meta, "icon", None),
        "license": getattr(meta, "license", None),
        "urls": getattr(meta, "urls", None),
    }
    for engine in service.engines.values():
        await engine.dispose()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dist", default="")
    parser.add_argument("--id", default="")
    args = parser.parse_args()

    errors = []
    result = {
        "errors": errors,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "tenko": version("tenko"),
    }
    try:
        from tenko_api import __version__ as api_version

        result["api"] = api_version
        ep = select_entry(args.dist, args.id, errors)
        if ep is not None:
            result.update(dist_info(ep), id=ep.name)
            result["metadata"] = asyncio.run(load(ep.name, args.root, errors))
    except Exception:
        errors.append("探针异常:\n" + traceback.format_exc(limit=8))
    args.out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


main()
