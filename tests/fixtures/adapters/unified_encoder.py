# SPDX-License-Identifier: GPL-3.0-or-later
# Adapter source author: MaiBot Team. Extracted from Mai-with-u/MaiBot-SnowLuma-Adapter @ ab751ae5c11f501e0158e33cacc321b33e34ef0c.
# License declared in upstream _manifest.json; GPLv3 text is in root LICENSE. See NOTICE.md.
# Only pure outbound encoding methods are retained; this is not a running client.
from __future__ import annotations
from typing import Any, Dict, List, Mapping

class AdapterEncoder:
    def _build_voiceurl_segments(self, item: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """构造基于 URL 的语音消息段。

        Args:
            item: Host 侧语音 URL 消息段。

        Returns:
            List[Dict[str, Any]]: 构造后的 OneBot 语音消息段列表。
        """
        voice_url_segment = self._build_url_media_segment("record", item.get("data"))
        return [voice_url_segment] if voice_url_segment else []


    def _build_music_segments(self, item: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """构造音乐卡片消息段。

        Args:
            item: Host 侧音乐消息段。

        Returns:
            List[Dict[str, Any]]: 构造后的 OneBot 音乐消息段列表。
        """
        music_segment = self._build_music_segment(item.get("data"))
        return [music_segment] if music_segment else []


    def _build_music_segment(self, item_data: Any) -> Dict[str, Any]:
        """构造音乐卡片消息段。

        Args:
            item_data: Host 侧音乐段数据。

        Returns:
            Dict[str, Any]: OneBot ``music`` 段；缺少有效数据时返回空字典。
        """
        if isinstance(item_data, str):
            normalized_song_id = item_data.strip()
            if not normalized_song_id:
                return {}
            return {"type": "music", "data": {"type": "163", "id": normalized_song_id}}

        if not isinstance(item_data, Mapping):
            return {}

        platform = str(item_data.get("type") or "163").strip() or "163"
        if platform not in {"163", "qq"}:
            platform = "163"
        song_id = str(item_data.get("id") or "").strip()
        if not song_id:
            return {}
        return {"type": "music", "data": {"type": platform, "id": song_id}}


    def _build_url_media_segment(self, segment_type: str, item_data: Any) -> Dict[str, Any]:
        """构造基于 URL 或文件引用的媒体消息段。

        Args:
            segment_type: 目标消息段类型。
            item_data: Host 侧消息段数据。

        Returns:
            Dict[str, Any]: NapCat 媒体消息段；缺少有效引用时返回空字典。
        """
        if isinstance(item_data, Mapping):
            file_reference = str(item_data.get("file") or item_data.get("url") or "").strip()
        else:
            file_reference = str(item_data or "").strip()
        if not file_reference:
            return {}
        return {"type": segment_type, "data": {"file": self._normalize_file_reference(file_reference)}}


    @staticmethod
    def _normalize_file_reference(file_reference: str) -> str:
        """规范化文件引用字符串。

        Args:
            file_reference: 原始文件引用。

        Returns:
            str: 可供 对端使用的文件引用。
        """
        if file_reference.startswith(("base64://", "file://", "http://", "https://")):
            return file_reference
        return f"file://{file_reference}"

