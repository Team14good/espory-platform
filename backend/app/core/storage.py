"""上傳檔案的存放與讀取（AD-15）。

檔案只存在 `settings.UPLOAD_DIR`（容器內為 volume `/app/uploads`），資料庫只存
`save_image()` 回傳的鍵值（例如 `<uuid hex>.png`），鍵值不含路徑。

圖片同時檢查宣告的 MIME 與檔頭 magic bytes，兩者一致才收；大小邊讀邊算，超過
`MAX_IMAGE_BYTES` 立刻停止。內容先寫到同資料夾的暫存檔，驗證通過才改名成正式
鍵值；任何失敗都會刪掉暫存檔，不留下半個檔案。
"""

import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings
from app.core.errors import BusinessError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
"""圖片大小上限：5 MB（剛好 5 MB 可收，多 1 byte 拒絕）。"""

# 宣告的 MIME → (檔頭 magic bytes, 副檔名)
_IMAGE_TYPES: dict[str, tuple[bytes, str]] = {
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
}
_HEADER_BYTES = max(len(magic) for magic, _ in _IMAGE_TYPES.values())
_CHUNK_BYTES = 64 * 1024
_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png)$")
_TEMP_PREFIX = ".upload-"


def _unsupported_type() -> BusinessError:
    return BusinessError("UNSUPPORTED_FILE_TYPE", "只接受 JPG 或 PNG 圖片", 415)


def _too_large() -> BusinessError:
    return BusinessError("FILE_TOO_LARGE", "圖片不能超過 5 MB", 413)


def _not_found() -> BusinessError:
    return BusinessError("FILE_NOT_FOUND", "找不到這個檔案", 404)


def _normalize_content_type(content_type: str | None) -> str:
    # 去掉 `; charset=...` 之類的參數，不分大小寫
    return (content_type or "").split(";", 1)[0].strip().lower()


def save_image(stream: BinaryIO, *, content_type: str | None) -> str:
    """存一張 JPG／PNG 圖片，回傳檔案鍵值。

    格式不符拋 415 `UNSUPPORTED_FILE_TYPE`；超過 5 MB 拋 413 `FILE_TOO_LARGE`。
    失敗時不留下任何檔案。
    """
    image_type = _IMAGE_TYPES.get(_normalize_content_type(content_type))
    if image_type is None:
        raise _unsupported_type()
    magic, extension = image_type

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=_TEMP_PREFIX, dir=upload_dir)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as temp_file:
            header = b""
            total = 0
            while chunk := stream.read(_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise _too_large()
                if len(header) < _HEADER_BYTES:
                    header += chunk[: _HEADER_BYTES - len(header)]
                    # 檔頭一湊齊就比對，不必等整個檔案讀完
                    if len(header) >= len(magic) and not header.startswith(magic):
                        raise _unsupported_type()
                temp_file.write(chunk)
        if not header.startswith(magic):
            raise _unsupported_type()
        key = f"{uuid.uuid4().hex}{extension}"
        os.replace(temp_path, upload_dir / key)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return key


def open_file(key: str) -> BinaryIO:
    """以二進位模式開啟已存的檔案；呼叫端負責關閉。

    鍵值不合格式（例如含 `../`）或檔案不存在時拋 404 `FILE_NOT_FOUND`。
    """
    if not _KEY_PATTERN.fullmatch(key):
        raise _not_found()
    try:
        return (Path(settings.UPLOAD_DIR) / key).open("rb")
    except FileNotFoundError, IsADirectoryError:
        raise _not_found() from None
