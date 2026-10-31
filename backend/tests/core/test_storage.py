import io
import os
from pathlib import Path

import pytest

from app.core import storage
from app.core.config import settings
from app.core.errors import BusinessError

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff\xe0"


@pytest.fixture(autouse=True)
def upload_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "uploads"
    monkeypatch.setattr(settings, "UPLOAD_DIR", directory)
    return directory


def _files(directory: Path) -> list[str]:
    return sorted(os.listdir(directory)) if directory.exists() else []


def _image(magic: bytes, size: int) -> io.BytesIO:
    return io.BytesIO(magic + b"\0" * (size - len(magic)))


class _EndlessStream(io.RawIOBase):
    """永遠讀不完的 PNG：用來確認大小是邊讀邊算，不會整個讀進記憶體。"""

    def __init__(self) -> None:
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        assert size > 0, "save_image 必須分段讀取"
        chunk = (
            (PNG_MAGIC + b"\0" * size)[:size] if self.bytes_read == 0 else b"\0" * size
        )
        self.bytes_read += len(chunk)
        return chunk


@pytest.mark.parametrize(
    ("content_type", "magic", "extension"),
    [("image/png", PNG_MAGIC, ".png"), ("image/jpeg", JPEG_MAGIC, ".jpg")],
)
def test_save_image_stores_file_and_returns_key(
    upload_dir: Path, content_type: str, magic: bytes, extension: str
) -> None:
    data = magic + b"pixels"

    key = storage.save_image(io.BytesIO(data), content_type=content_type)

    assert key.endswith(extension)
    assert "/" not in key and "\\" not in key
    assert _files(upload_dir) == [key]
    with storage.open_file(key) as stored:
        assert stored.read() == data


def test_content_type_parameters_and_case_are_ignored() -> None:
    key = storage.save_image(
        io.BytesIO(PNG_MAGIC), content_type="Image/PNG; charset=binary"
    )

    assert key.endswith(".png")


@pytest.mark.parametrize(
    ("content_type", "data"),
    [
        ("image/gif", b"GIF89a" + b"\0" * 10),
        (None, PNG_MAGIC),
        ("", PNG_MAGIC),
        ("image/png", JPEG_MAGIC + b"\0" * 10),  # 檔頭與 MIME 不符
        ("image/jpeg", PNG_MAGIC),
        ("image/png", b""),  # 空檔案
        ("image/png", PNG_MAGIC[:4]),  # 檔頭不完整
    ],
)
def test_unsupported_type_is_rejected_without_writing(
    upload_dir: Path, content_type: str | None, data: bytes
) -> None:
    with pytest.raises(BusinessError) as exc_info:
        storage.save_image(io.BytesIO(data), content_type=content_type)

    assert exc_info.value.code == "UNSUPPORTED_FILE_TYPE"
    assert exc_info.value.status_code == 415
    assert exc_info.value.message == "只接受 JPG 或 PNG 圖片"
    assert _files(upload_dir) == []


def test_exactly_5_mb_is_accepted(upload_dir: Path) -> None:
    key = storage.save_image(
        _image(PNG_MAGIC, storage.MAX_IMAGE_BYTES), content_type="image/png"
    )

    assert (upload_dir / key).stat().st_size == 5 * 1024 * 1024


def test_one_byte_over_5_mb_is_rejected_without_leaving_file(
    upload_dir: Path,
) -> None:
    with pytest.raises(BusinessError) as exc_info:
        storage.save_image(
            _image(PNG_MAGIC, storage.MAX_IMAGE_BYTES + 1), content_type="image/png"
        )

    assert exc_info.value.code == "FILE_TOO_LARGE"
    assert exc_info.value.status_code == 413
    assert exc_info.value.message == "圖片不能超過 5 MB"
    assert _files(upload_dir) == []


def test_size_is_counted_while_reading(upload_dir: Path) -> None:
    stream = _EndlessStream()

    with pytest.raises(BusinessError, match="5 MB"):
        storage.save_image(stream, content_type="image/png")  # type: ignore[arg-type]

    # 超過上限後立刻停止，不會繼續讀
    assert stream.bytes_read <= storage.MAX_IMAGE_BYTES + 64 * 1024
    assert _files(upload_dir) == []


def test_wrong_magic_stops_reading_early(upload_dir: Path) -> None:
    stream = io.BytesIO(b"GIF89a" + b"\0" * (storage.MAX_IMAGE_BYTES * 2))

    with pytest.raises(BusinessError) as exc_info:
        storage.save_image(stream, content_type="image/png")

    # 格式錯誤優先於大小：檔頭不對就不必讀完
    assert exc_info.value.code == "UNSUPPORTED_FILE_TYPE"
    assert stream.tell() < storage.MAX_IMAGE_BYTES
    assert _files(upload_dir) == []


def test_read_error_leaves_no_file(upload_dir: Path) -> None:
    class _BrokenStream(io.RawIOBase):
        calls = 0

        def read(self, size: int = -1) -> bytes:
            self.calls += 1
            if self.calls > 1:
                raise OSError("連線中斷")
            return PNG_MAGIC

    with pytest.raises(OSError, match="連線中斷"):
        storage.save_image(_BrokenStream(), content_type="image/png")  # type: ignore[arg-type]

    assert _files(upload_dir) == []


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../x",
        "../secret.png",
        "/etc/passwd",
        "0" * 32 + ".gif",
        "0" * 32 + ".png/../x",
        "A" * 32 + ".png",
        "0" * 32 + ".png\n",
        ".upload-abc",
        "0" * 32 + ".png",  # 格式合法但不存在
    ],
)
def test_open_file_rejects_invalid_or_missing_key(key: str) -> None:
    with pytest.raises(BusinessError) as exc_info:
        storage.open_file(key)

    assert exc_info.value.code == "FILE_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_open_file_does_not_read_outside_upload_dir(
    upload_dir: Path, tmp_path: Path
) -> None:
    upload_dir.mkdir()
    (tmp_path / "secret.png").write_bytes(PNG_MAGIC)

    with pytest.raises(BusinessError, match="找不到"):
        storage.open_file("../secret.png")
