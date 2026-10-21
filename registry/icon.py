"""图标处理：解码校验、居中裁成方形、缩放到 128x128，并重新编码为无元数据的 PNG。

Tenko 的图片菜单把图标统一染成白色显示，所以图标必须是透明底的图形。
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from . import net
from .model import ROOT, load_plugin, save_plugin

MAX_INPUT_BYTES = 1024 * 1024
MIN_SIDE = 64
SIZE = 128
ALLOWED_FORMATS = {"PNG", "WEBP"}
MAX_PIXELS = 4096 * 4096  # 1 MB 的压缩图可以解出远大于此的像素，先拒绝


class IconError(ValueError):
    """图标不符合要求；消息直接展示给提交者。"""


def process_icon(data: bytes) -> bytes:
    if len(data) > MAX_INPUT_BYTES:
        raise IconError("图标不能超过 1 MB")
    try:
        # 以内容为准识别格式：SVG、GIF 等都会在这里失败或被格式白名单拦下。
        image = Image.open(io.BytesIO(data))
        if image.format not in ALLOWED_FORMATS:
            raise IconError("图标只支持带透明通道的 PNG 或 WebP")
        if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1:
            raise IconError("不支持动图，请提供静态图片")
        if image.width * image.height > MAX_PIXELS:
            raise IconError("图片尺寸过大")
        image.load()
    except IconError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise IconError("无法解析为 PNG 或 WebP 图片（不支持 SVG）") from error

    image = ImageOps.exif_transpose(image)
    if min(image.size) < MIN_SIDE:
        raise IconError(f"图片的短边至少 {MIN_SIDE} px，当前为 {min(image.size)} px")
    image = ImageOps.fit(image.convert("RGBA"), (SIZE, SIZE), Image.Resampling.LANCZOS)
    if image.getchannel("A").getextrema()[0] == 255:
        raise IconError("图标需要透明背景：菜单会把图标染成白色，不透明的方图会显示成白块")
    # 用像素数据重建图像，确保不带任何 ICC、EXIF 或文本块。
    clean = Image.frombytes("RGBA", image.size, image.tobytes())
    out = io.BytesIO()
    clean.save(out, format="PNG", optimize=True)
    return out.getvalue()


def install_icon(plugin_id: str, png: bytes, root: Path = ROOT) -> str:
    """写入 icons/<id>-<sha8>.png，删除该插件的旧图标，返回相对路径。"""

    name = f"{plugin_id}-{hashlib.sha256(png).hexdigest()[:8]}.png"
    icons = root / "icons"
    icons.mkdir(exist_ok=True)
    (icons / name).write_bytes(png)
    for old in icons.glob(f"{plugin_id}-????????.png"):
        if old.name != name:
            old.unlink()
    return f"icons/{name}"


def load_source(source: str, fetch: Callable[[str, int], bytes] = net.fetch_bytes) -> bytes:
    if source.startswith("https://"):
        return fetch(source, MAX_INPUT_BYTES)
    if "://" in source:
        raise IconError("图标地址只允许 https")
    path = Path(source)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise IconError("图标不能超过 1 MB")
    return path.read_bytes()


def set_icon(plugin_id: str, source: str, root: Path = ROOT, fetch=net.fetch_bytes) -> str:
    entry = load_plugin(plugin_id, root)
    entry["icon"] = install_icon(plugin_id, process_icon(load_source(source, fetch)), root)
    save_plugin(plugin_id, entry, root)
    return entry["icon"]
