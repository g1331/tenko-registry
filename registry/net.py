"""所有会碰网络或外部进程的薄封装。业务代码通过参数注入它们，测试用夹具替换。"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any
from urllib.parse import urlsplit

import httpx
from packaging.version import InvalidVersion, Version

TIMEOUT = httpx.Timeout(20.0)
HEADERS = {"User-Agent": "tenko-registry (+https://github.com/g1331/tenko-registry)"}
SEMVER_TAG = re.compile(r"v?(\d+\.\d+\.\d+.*)")
TENKO_REPO = "https://github.com/g1331/tenko"


class NetError(RuntimeError):
    """网络或外部命令失败。"""


def get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    try:
        response = httpx.get(
            url, headers={**HEADERS, **(headers or {})}, timeout=TIMEOUT, follow_redirects=True
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise NetError(f"请求 {url} 失败: {error}") from error


def fetch_bytes(url: str, limit: int, max_redirects: int = 3) -> bytes:
    """只允许 https 的下载；跳转逐跳检查，流式读取时即限制大小。"""

    try:
        with httpx.Client(headers=HEADERS, timeout=TIMEOUT) as client:
            for _ in range(max_redirects + 1):
                if urlsplit(url).scheme != "https":
                    raise NetError(f"只允许 https 地址: {url}")
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = str(response.next_request.url) if response.next_request else ""
                        continue
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise NetError(f"文件超过大小上限 {limit} 字节")
                        chunks.append(chunk)
                    return b"".join(chunks)
    except httpx.HTTPError as error:
        raise NetError(f"下载失败: {error}") from error
    raise NetError("跳转次数过多")


def git_ls_remote_tags(url: str) -> dict[str, str]:
    """返回 {标签名: 提交 SHA}；附注标签取其指向的提交。"""

    try:
        out = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            check=True, capture_output=True, text=True, timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        ).stdout
    except (subprocess.SubprocessError, OSError) as error:
        raise NetError(f"git ls-remote {url} 失败: {error}") from error
    tags: dict[str, str] = {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            tags[name[:-3]] = sha  # 附注标签的 ^{} 行才是提交
        else:
            tags.setdefault(name, sha)
    return tags


def latest_tenko_tag(ls_tags=git_ls_remote_tags) -> str:
    """g1331/tenko 中版本号最大的 ``v*`` 标签（含预发布）。"""

    best: tuple[Version, str] | None = None
    for tag in ls_tags(TENKO_REPO):
        match = re.fullmatch(r"v(\d.*)", tag)
        if not match:
            continue
        try:
            candidate = (Version(match[1]), tag)
        except InvalidVersion:
            continue
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        raise NetError("g1331/tenko 没有 v* 标签")
    return best[1]
