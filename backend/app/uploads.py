"""Yuklangan fayllarni magic-bytes bo'yicha tekshirish (kengaytma/Content-Type'ga ishonilmaydi). SVG qabul qilinmaydi (XSS)."""
import gzip
import json

from .errors import DomainError

_IMG = [(b"\x89PNG\r\n\x1a\n", "image", "image/png"), (b"\xff\xd8\xff", "image", "image/jpeg"), (b"GIF87a", "gif", "image/gif"), (b"GIF89a", "gif", "image/gif")]


def sniff_image(data: bytes, max_bytes: int, allow: tuple = ("image", "gif", "webm", "lottie", "tgs")) -> tuple[str, str]:
    if not data or len(data) > max_bytes:
        raise DomainError("bad_file", f"Fayl bo'sh yoki {max_bytes // 1000} KB dan katta", 413)
    for magic, kind, mime in _IMG:
        if data.startswith(magic):
            if kind in allow:
                return kind, mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and "image" in allow:
        return "image", "image/webp"
    if data[:4] == b"\x1a\x45\xdf\xa3" and "webm" in allow:
        return "webm", "video/webm"
    if data[:2] == b"\x1f\x8b" and "tgs" in allow:  # TGS = gzip(Lottie JSON)
        try:
            raw = gzip.decompress(data) if len(data) < 200_000 else b""
            j = json.loads(raw)
            if "layers" in j and "v" in j:
                return "tgs", "application/x-tgsticker"
        except Exception:
            pass
        raise DomainError("bad_file", "TGS fayl noto'g'ri (gzip Lottie JSON emas)")
    if data[:1] in (b"{", b" ") and "lottie" in allow:
        try:
            j = json.loads(data)
            if "layers" in j and "v" in j:
                return "lottie", "application/json"
        except Exception:
            pass
    raise DomainError("bad_file", "Fayl turi qo'llab-quvvatlanmaydi", 415)
