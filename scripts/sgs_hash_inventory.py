# -*- coding: utf-8 -*-
"""唯一 canonical hash helper（R1-NEW-001）。

仓库内所有“SHA-256 inventory”都必须调用本模块的
``git_normalized_sha256``，禁止在生成时用 Git blob SHA-1（git hash-object
默认输出40位SHA-1）而验证时用 hashlib.sha256。

字节规范（文档化契约）：
* 以 UTF-8 读取文件原始内容（不转码、不丢失）；
* 若存在 UTF-8 BOM（EF BB BF）则去除；
* 行结束统一为 LF（CRLF→LF，与 Git core.autocrlf=true 的归一化一致）；
* 对该归一化字节计算 SHA-256，输出 64 位小写十六进制。

自引用规则：包含自身 inventory 的文件（如 CHECKPOINT_MANIFEST.json）
必须标记 ``self_excluded=true`` 并从自身 inventory 排除，否则会形成
“manifest 包含自身最终哈希”的自引用不可能条件。
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def git_normalized_sha256(relpath: str | Path) -> str:
    """对仓库相对路径文件计算 Git-normalized 内容的 SHA-256（64 hex）。"""

    path = Path(relpath)
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    normalized = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized).hexdigest()


__all__ = ["git_normalized_sha256"]
