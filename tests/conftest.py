import hashlib
import io
import shutil
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parent.parent


def png_bytes(size=(200, 100), color=(200, 30, 30)) -> bytes:
    out = io.BytesIO()
    # 透明底上画一块实心色，模拟符合要求的图形图标。
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    w, h = size
    image.paste((*color, 255), (w // 4, h // 4, w * 3 // 4, h * 3 // 4))
    image.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def root(tmp_path):
    """一个最小的仓库根目录：带内置 ID 清单、空的屏蔽与下架记录。"""

    for name in ("builtin_ids.txt", "licenses.txt", "blocked.json", "removed.json"):
        shutil.copy(REPO / name, tmp_path / name)
    (tmp_path / "plugins").mkdir()
    (tmp_path / "icons").mkdir()
    return tmp_path


def sha8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]
