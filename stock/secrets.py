# -*- coding: utf-8 -*-
"""API key 的本机加密（Windows DPAPI）。

为什么用 DPAPI：
  * Python 标准库没有 AES，硬写一个"自制加密"是不负责任的；
  * DPAPI 由系统保管密钥，密文绑定「当前用户 + 当前机器」，
    拷到别的机器/别的用户下解不开——正好符合「key 只在本机用」的场景。

非 Windows 或 DPAPI 不可用时，`encrypt` 返回 (明文, "plain")，
调用方必须把 mode 一起存下来，界面上要如实显示「未加密」。
"""
import base64
import sys

try:
    import ctypes
    from ctypes import wintypes
    _HAS_CTYPES = True
except ImportError:  # pragma: no cover - 非 Windows 环境
    _HAS_CTYPES = False

CRYPTPROTECT_UI_FORBIDDEN = 0x1
ENTROPY = b"stock-system-2026"


class _DATA_BLOB(ctypes.Structure if _HAS_CTYPES else object):
    if _HAS_CTYPES:
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_from(data):
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf


def _blob_to(blob):
    size = blob.cbData
    return ctypes.string_at(blob.pbData, size)


def available():
    return _HAS_CTYPES and sys.platform.startswith("win")


def encrypt(text):
    """返回 (存储值, 模式)。模式为 'dpapi' 或 'plain'。"""
    text = "" if text is None else str(text)
    if not text:
        return "", "empty"
    if not available():
        return text, "plain"
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        data_in, keep_in = _blob_from(text.encode("utf-8"))
        entropy, keep_entropy = _blob_from(ENTROPY)
        out = _DATA_BLOB()
        ok = crypt32.CryptProtectData(
            ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
        if not ok:
            raise OSError("CryptProtectData failed")
        try:
            raw = _blob_to(out)
        finally:
            kernel32.LocalFree(out.pbData)
        return base64.b64encode(raw).decode("ascii"), "dpapi"
    except Exception:  # noqa: BLE001 - 加密失败就明说，不假装
        return text, "plain"


def decrypt(token, mode="dpapi"):
    token = "" if token is None else str(token)
    if not token or mode in ("empty", ""):
        return ""
    if mode != "dpapi":
        return token
    if not available():
        return ""
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        raw = base64.b64decode(token.encode("ascii"))
        data_in, keep_in = _blob_from(raw)
        entropy, keep_entropy = _blob_from(ENTROPY)
        out = _DATA_BLOB()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
        if not ok:
            return ""
        try:
            return _blob_to(out).decode("utf-8", "replace")
        finally:
            kernel32.LocalFree(out.pbData)
    except Exception:  # noqa: BLE001
        return ""


def set_key(cfg, plain):
    """把明文 key 写进配置（密文 + 模式），并清掉明文字段。"""
    token, mode = encrypt(plain)
    cfg["api_key_enc"] = token
    cfg["api_key_mode"] = mode
    cfg["api_key"] = ""
    return cfg


def get_key(cfg):
    cfg = cfg or {}
    if cfg.get("api_key_enc"):
        return decrypt(cfg["api_key_enc"], cfg.get("api_key_mode", "dpapi"))
    return str(cfg.get("api_key") or "")
