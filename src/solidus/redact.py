"""把密钥从将要落盘或发出去的文本里拿掉。"""

from __future__ import annotations


def redact(text: str, secrets: list[str]) -> tuple[str, bool]:
    leaked = False
    cleaned = text
    for secret in secrets:
        if secret and secret in cleaned:
            cleaned = cleaned.replace(secret, "[已省略]")
            leaked = True
    return cleaned, leaked
