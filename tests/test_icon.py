import hashlib
import io

import pytest
from PIL import Image

from registry.icon import IconError, install_icon, process_icon
from tests.conftest import png_bytes


def test_wide_png_becomes_128_square_png_without_metadata(root):
    png = process_icon(png_bytes((200, 100)))
    image = Image.open(io.BytesIO(png))
    assert (image.format, image.size, image.mode) == ("PNG", (128, 128), "RGBA")
    assert image.info == {}  # 没有文本块、ICC 等元数据

    path = install_icon("demo", png, root)
    digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
    assert path == f"icons/demo-{digest[:8]}.png"


def test_new_icon_replaces_previous_file(root):
    first = install_icon("demo", process_icon(png_bytes((100, 100), (1, 2, 3))), root)
    second = install_icon("demo", process_icon(png_bytes((100, 100), (9, 9, 9))), root)
    assert first != second
    assert [p.name for p in (root / "icons").iterdir()] == [second.removeprefix("icons/")]


def test_svg_is_rejected():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"></svg>'
    with pytest.raises(IconError):
        process_icon(svg)


def test_oversize_input_is_rejected():
    with pytest.raises(IconError, match="1 MB"):
        process_icon(b"\x89PNG" + b"0" * (1024 * 1024))


def test_too_small_is_rejected():
    with pytest.raises(IconError, match="64"):
        process_icon(png_bytes((63, 200)))
