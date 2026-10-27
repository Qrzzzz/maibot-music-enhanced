# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""Shared media URL policy for aggregator and native-platform downloads."""
from urllib.parse import urlparse


def allowed_media_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return (parsed.scheme in {"http", "https"} and not parsed.username and not parsed.password
                and parsed.port in {None, 80, 443}
                and (host.endswith(".qq.com") or host.endswith(".music.126.net")
                     or host in {"music.163.com", "interface.music.163.com"}))
    except ValueError:
        return False
