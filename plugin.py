# SPDX-License-Identifier: GPL-3.0-only
# Portions Copyright (c) 2026 磐冰, originally under MIT; see licenses/maibot-music-MIT.txt.
# Modifications Copyright (c) 2026 Qrzzzz. Modified 2026-11-05.
"""麦麦点歌增强 — 基于 maibot-music 的独立维护版本。"""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from dataclasses import dataclass, field
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from maibot_sdk import Command, Field, HookHandler, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import HookMode, ToolParameterInfo, ToolParamType

from .audio_cache import AudioCacheError, AudioUnavailable, MusicAudioCache
from .error_log import PluginErrorLog
from .music_api import MusicAPIResponseError, SongInfo
from .source_bridge import SourceAwareSearchClient as MusicSearchClient
from .url_parser import extract_urls, parse_music_card_text, parse_music_url

PLUGIN_VERSION = "1.3.1"


# ===== 配置模型 =====


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default=PLUGIN_VERSION, description="配置版本")


class MusicConfig(PluginConfigBase):
    """音乐配置。"""

    __ui_label__ = "音乐"
    __ui_icon__ = "music"
    __ui_order__ = 1

    default_platform: str = Field(
        default="auto",
        description="默认平台: auto(合并QQ和网易云)、163(网易云) 或 qq(QQ音乐)",
    )
    command_prefix: str = Field(default="/", description="命令前缀符号，如 / 或 #")
    auto_parse_url: bool = Field(default=False, description="是否自动解析音乐链接")
    auto_parse_card: bool = Field(default=False, description="是否自动解析音乐卡片")
    search_limit: int = Field(default=10, ge=1, le=20, description="每个平台搜索结果数（1–20）")
    page_size: int = Field(default=5, ge=1, le=10, description="每页候选数量")
    selection_timeout_seconds: int = Field(default=90, ge=10, le=600, description="选歌列表有效期（秒）")
    auto_recall_selection: bool = Field(default=True, description="自动撤回列表，需要 SnowLuma 支持消息 ID 回执和撤回")
    group_cross_platform_results: bool = Field(default=True, description="合并歌名、歌手和专辑一致的跨平台候选")
    auto_select_first: bool = Field(
        default=False,
        description="搜索到多首歌曲时是否跳过选歌阶段，直接发送第一首",
    )
    play_mode: Literal["voice", "card", "link"] = Field(
        default="voice",
        description="默认发送方式: voice(语音)、card(标准卡片，失败回退链接)、link(链接)",
    )
    voice_source: Literal["local", "remote"] = Field(
        default="local",
        description="语音音频来源: local(本地缓存) 或 remote(远程URL)",
    )
    cache_storage_dir: str = Field(
        default="",
        description="MaiBot 缓存目录；留空使用本插件数据目录下的 audio_cache",
    )
    cache_reader_dir: str = Field(
        default="",
        description="适配器读取缓存的路径；同机留空，容器部署填写同一目录的容器内路径",
    )
    cache_max_size_mb: int = Field(default=1024, gt=0, description="音乐缓存最大容量（MB）")
    cache_expire_hours: int = Field(default=24, gt=0, description="超过此小时数未访问的缓存将被清理")
    cache_cleanup_interval_hours: int = Field(default=24, gt=0, description="缓存清理任务执行间隔（小时）")
    cache_max_file_size_mb: int = Field(default=50, gt=0, description="单个音乐缓存文件最大大小（MB）")
    cache_download_timeout_seconds: int = Field(default=30, gt=0, description="下载音乐文件超时时间（秒）")


class NeteaseConfig(PluginConfigBase):
    """网易云音乐配置。"""

    __ui_label__ = "网易云音乐"
    __ui_icon__ = "cloud"
    __ui_order__ = 2

    MUSIC_U: str = Field(
        default="",
        description="MUSIC_U — 登录凭证，用于获取高音质",
    )
    csrf_token: str = Field(
        default="",
        description="__csrf — CSRF 令牌，与 MUSIC_U 配对",
    )


class QQMusicConfig(PluginConfigBase):
    """QQ音乐配置。"""

    __ui_label__ = "QQ音乐"
    __ui_icon__ = "headphones"
    __ui_order__ = 3

    uin: str = Field(
        default="",
        description="uin — QQ音乐登录账号；回退原生 QQ 搜索时需要",
    )
    qqmusic_key: str = Field(
        default="",
        description="qqmusic_key — 回退原生 QQ 搜索时需要的凭证；账号权益影响可播放范围",
    )


class SourceBridgeConfig(PluginConfigBase):
    __ui_label__ = "完整音频音源"
    enabled: bool = Field(default=True, description="向 music.txqq.pro 发送点歌关键词；本地语音模式下载后校验完整时长并转为 MP3。关闭则使用原生平台接口")


class MusicPluginConfig(PluginConfigBase):
    """音乐插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    music: MusicConfig = Field(default_factory=MusicConfig)
    netease: NeteaseConfig = Field(default_factory=NeteaseConfig)
    qq: QQMusicConfig = Field(default_factory=QQMusicConfig)
    source_bridge: SourceBridgeConfig = Field(default_factory=SourceBridgeConfig)


# ===== 待选状态 =====

@dataclass
class PendingSelection:
    query: str
    platform: str
    mode: str = ""
    results: list[SongInfo] = field(default_factory=list)
    page: int = 0
    created: float = field(default_factory=time.monotonic)
    busy: bool = False
    owner_id: str = ""
    transport: str = ""
    alternatives: dict[int, list[SongInfo]] = field(default_factory=dict)
    netease_origins: dict[str, int] = field(default_factory=dict)
    menu_id: str = ""
    expiry: asyncio.TimerHandle | None = None
    queued: bool = False


@dataclass
class RecentSelection:
    song: SongInfo
    created: float = field(default_factory=time.monotonic)
    busy: bool = False


# ===== 插件主类 =====


class MusicPlugin(MaiBotPlugin):
    """音乐插件 — 搜索点歌、解析音乐链接，发送语音音频。"""

    config_model = MusicPluginConfig

    def __init__(self) -> None:
        super().__init__()
        self._api: MusicSearchClient | None = None
        self._audio_cache: MusicAudioCache | None = None
        self._error_log: PluginErrorLog | None = None
        self._cache_cleanup_task: asyncio.Task[None] | None = None
        self._voice_send_condition = asyncio.Condition()
        self._active_voice_sends = 0
        self._stopping_audio_cache = False
        # User identity is supplied by Host, never accepted as an LLM tool parameter.
        self._pending_choices: dict[tuple[str, str], PendingSelection] = {}
        self._recent_selections: dict[tuple[str, str], RecentSelection] = {}
        self._pending_lock = asyncio.Lock()
        self._menu_tasks: set[asyncio.Task[None]] = set()

    def _clean_expired_pending(self) -> None:
        """清理已过期的待选状态。"""
        now = time.monotonic()
        expired = [sid for sid, item in self._pending_choices.items()
                   if not item.busy and now - item.created >= self.config.music.selection_timeout_seconds]
        for sid in expired:
            self._drop_pending(sid)

    def _clean_recent_selections(self) -> None:
        deadline = time.monotonic() - self.config.music.selection_timeout_seconds
        for key, recent in list(self._recent_selections.items()):
            if not recent.busy and recent.created <= deadline:
                del self._recent_selections[key]

    def _drop_pending(self, key: tuple[str, str]) -> None:
        pending = self._pending_choices.pop(key)
        if pending.expiry:
            pending.expiry.cancel()
        if pending.transport == "qq":
            self._recall_menu(pending.menu_id)

    def _recall_menu(self, message_id: str) -> None:
        if not re.fullmatch(r"-?[0-9]+", message_id) or not self.config.music.auto_recall_selection:
            return

        async def recall() -> None:
            try:
                result = await self.ctx.api.call(
                    "maibot-team.snowluma-adapter.adapter.napcat.message.delete_msg",
                    version="1", message_id=message_id,
                )
                if not isinstance(result, Mapping) or result.get("retcode") != 0:
                    self.ctx.logger.warning("选歌列表撤回未确认，请检查 SnowLuma 撤回支持")
            except Exception:
                self.ctx.logger.warning("选歌列表撤回失败，请检查 SnowLuma 撤回支持")

        task = asyncio.create_task(recall())
        self._menu_tasks.add(task)
        task.add_done_callback(self._menu_tasks.discard)

    def _expire_menu(self, key: tuple[str, str], pending: PendingSelection) -> None:
        if self._pending_choices.get(key) is pending:
            if pending.busy:
                self._recall_menu(pending.menu_id)
                pending.menu_id = ""
            else:
                self._drop_pending(key)

    async def _send_selection_menu(self, key: tuple[str, str], pending: PendingSelection, text: str) -> bool:
        if self._pending_choices.get(key) is not pending or pending.busy:
            return False
        pending.busy = True
        try:
            receipt = await self.ctx.send.text(text, key[0], return_details=True)
        except Exception:
            return False
        finally:
            pending.busy = False
        sent = bool(receipt.get("sent")) if isinstance(receipt, Mapping) else bool(receipt)
        if not sent:
            return False
        message_id = (str(receipt.get("message_id") or "")
                      if isinstance(receipt, Mapping) and pending.transport == "qq" else "")
        if self._pending_choices.get(key) is not pending:
            self._recall_menu(message_id)
            return False
        self._recall_menu(pending.menu_id)
        pending.menu_id = message_id
        if pending.expiry is None:
            pending.created = time.monotonic()
            pending.expiry = asyncio.get_running_loop().call_later(
                self.config.music.selection_timeout_seconds, self._expire_menu, key, pending)
        self._clean_expired_pending()
        return True

    def normalize_plugin_config(self, config_data: Mapping[str, Any] | None) -> tuple[dict[str, Any], bool]:
        """Migrate old cache paths and discard obsolete client HTTP credentials."""
        raw = dict(config_data) if isinstance(config_data, Mapping) else {}
        changed = "napcat" in raw
        raw.pop("napcat", None)
        if isinstance(raw.get("music"), Mapping):
            music = dict(raw["music"])
            if "cache_napcat_dir" in music:
                music.setdefault("cache_reader_dir", music.pop("cache_napcat_dir"))
                changed = True
            raw["music"] = music
        if isinstance(raw.get("plugin", {}), Mapping):
            plugin = dict(raw.get("plugin", {}))
            changed = changed or plugin.get("config_version") != PLUGIN_VERSION
            plugin["config_version"] = PLUGIN_VERSION
            raw["plugin"] = plugin
        normalized, updated = super().normalize_plugin_config(raw)
        return normalized, changed or updated

    def _get_api(self) -> MusicSearchClient:
        """获取或创建 API 客户端。"""
        if self._api is None:
            netease_cookie: dict[str, str] = {}
            if self.config.netease.MUSIC_U:
                netease_cookie["MUSIC_U"] = self.config.netease.MUSIC_U
            if self.config.netease.csrf_token:
                netease_cookie["__csrf"] = self.config.netease.csrf_token

            qq_cookie: dict[str, str] = {}
            if self.config.qq.uin:
                qq_cookie["uin"] = self.config.qq.uin
            if self.config.qq.qqmusic_key:
                qq_cookie["qqmusic_key"] = self.config.qq.qqmusic_key

            self._api = MusicSearchClient(
                thirdparty_enabled=self.config.source_bridge.enabled,
                netease_cookie=netease_cookie,
                qq_cookie=qq_cookie,
            )
        return self._api

    async def _start_audio_cache(self) -> None:
        """按当前配置初始化语音音频缓存。"""
        # Per-request voice is available even when the default mode is card/link.
        if self.config.music.voice_source != "local":
            async with self._voice_send_condition:
                self._stopping_audio_cache = False
                self._voice_send_condition.notify_all()
            return

        async with self._voice_send_condition:
            self._stopping_audio_cache = True

        if self.config.source_bridge.enabled:
            missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
            if missing and self.config.music.play_mode == "voice":
                raise AudioCacheError("完整音频模式缺少 " + ", ".join(missing) + "，请安装 FFmpeg 并加入 PATH")

        storage_dir = (
            Path(self.config.music.cache_storage_dir).expanduser().resolve()
            if self.config.music.cache_storage_dir.strip()
            else self.ctx.paths.data_dir / "audio_cache"
        )
        reader_dir = self.config.music.cache_reader_dir.strip() or str(storage_dir)
        audio_cache = MusicAudioCache(
            str(storage_dir),
            reader_dir,
            max_size_bytes=self.config.music.cache_max_size_mb * 1024 * 1024,
            expire_seconds=self.config.music.cache_expire_hours * 3600,
            max_file_size_bytes=self.config.music.cache_max_file_size_mb * 1024 * 1024,
            download_timeout_seconds=self.config.music.cache_download_timeout_seconds,
        )
        try:
            await audio_cache.initialize()
        except BaseException:
            await audio_cache.close()
            raise

        self._audio_cache = audio_cache
        self._cache_cleanup_task = asyncio.create_task(
            self._cache_cleanup_loop(),
            name="maibot-music-enhanced-cache-cleanup",
        )
        async with self._voice_send_condition:
            self._stopping_audio_cache = False
            self._voice_send_condition.notify_all()

    async def _stop_audio_cache(self) -> None:
        """等待语音发送结束后停止缓存任务和下载客户端。"""
        async with self._voice_send_condition:
            self._stopping_audio_cache = True
            await self._voice_send_condition.wait_for(lambda: self._active_voice_sends == 0)

        if self._cache_cleanup_task is not None:
            self._cache_cleanup_task.cancel()
            try:
                await self._cache_cleanup_task
            except asyncio.CancelledError:
                pass
            self._cache_cleanup_task = None

        if self._audio_cache is not None:
            await self._audio_cache.close()
            self._audio_cache = None

    async def _acquire_voice_send(self) -> tuple[Literal["local", "remote"], MusicAudioCache | None]:
        """注册一次语音发送并返回音频来源与缓存快照。"""
        async with self._voice_send_condition:
            await self._voice_send_condition.wait_for(lambda: not self._stopping_audio_cache)
            self._active_voice_sends += 1
            return self.config.music.voice_source, self._audio_cache

    async def _release_voice_send(self) -> None:
        """结束一次语音发送并唤醒等待中的缓存重载。"""
        async with self._voice_send_condition:
            self._active_voice_sends -= 1
            if self._active_voice_sends == 0:
                self._voice_send_condition.notify_all()

    async def _cache_cleanup_loop(self) -> None:
        """定期删除过期缓存并执行容量淘汰。"""
        interval_seconds = self.config.music.cache_cleanup_interval_hours * 3600
        while True:
            await asyncio.sleep(interval_seconds)
            if self._audio_cache is None:
                continue
            try:
                await self._audio_cache.cleanup()
            except Exception:
                self.ctx.logger.exception("清理音乐缓存失败")

    @staticmethod
    def _platform(value: str) -> str:
        aliases = {"auto": "auto", "全部": "auto", "自动": "auto", "all": "auto",
                   "qq": "qq", "qq音乐": "qq", "qqmusic": "qq",
                   "163": "163", "网易": "163", "网易云": "163", "网易云音乐": "163", "netease": "163"}
        key = value.strip().lower()
        if key not in aliases:
            raise ValueError("平台请选择 QQ、网易云或全部")
        return aliases[key]

    def _resolve_platform(self, platform: str = "") -> str:
        return self._platform(platform or self.config.music.default_platform)

    def _mode(self, value: str = "") -> str:
        aliases = {"voice": "voice", "语音": "voice", "card": "card", "卡片": "card",
                   "link": "link", "链接": "link", "文本": "link"}
        if not value or value == "auto":
            return self.config.music.play_mode
        if value.lower() not in aliases:
            raise ValueError("发送方式请选择语音、卡片或链接")
        return aliases[value.lower()]

    @staticmethod
    def _public_song_url(song: SongInfo) -> str:
        song_id = quote(song.song_id, safe="")
        if song.platform == "qq":
            return f"https://y.qq.com/n/ryqq/songDetail/{song_id}"
        if song.platform == "163":
            return f"https://music.163.com/song?id={song_id}"
        return ""

    async def _send_song_link(self, song: SongInfo, stream_id: str, *, fallback: bool = False) -> bool:
        link = self._public_song_url(song)
        if not link:
            return False
        note = "ℹ️ 标准音乐卡片不可用，已改发歌曲链接。\n" if fallback else ""
        try:
            return bool(await self.ctx.send.text(f"{note}🔗 {song.display()}\n{link}", stream_id))
        except Exception:
            self.ctx.logger.warning("歌曲链接发送失败: %s %s", song.platform, song.song_id)
            return False

    async def _send_music_card(self, song: SongInfo, stream_id: str, *, silent: bool = False) -> bool:
        """Only standard cards through Host; never bypass the adapter with client APIs."""
        del silent
        card_id = song.numeric_id if song.platform == "qq" else song.song_id
        if song.platform == "qq" and not card_id:
            if song.song_id.isascii() and song.song_id.isdecimal():
                card_id = song.song_id
            else:
                try:
                    detail = await self._get_api().get_qq_song_detail(song.song_id)
                    if detail and detail.song_id == song.song_id:
                        card_id = detail.numeric_id
                except Exception:
                    self.ctx.logger.warning("QQ卡片歌曲ID查询失败，回退链接")
        if song.platform in {"qq", "163"} and card_id.isascii() and card_id.isdecimal():
            try:
                if await self.ctx.send.custom("music", {"type": song.platform, "id": card_id}, stream_id):
                    return True
            except Exception:
                self.ctx.logger.warning("平台音乐卡片不可用，改发歌曲链接")
        return await self._send_song_link(song, stream_id, fallback=True)

    def _format_results(self, pending: PendingSelection) -> str:
        size = self.config.music.page_size
        start = pending.page * size
        pages = (len(pending.results) + size - 1) // size
        mode_label = {"voice": "语音", "card": "卡片", "link": "链接"}[self._mode(pending.mode)]
        lines = [f"🎵 「{pending.query}」的搜索结果",
                 f"📄 第 {pending.page + 1}/{pages} 页 · 共 {len(pending.results)} 首 · 发起人 {pending.owner_id}", ""]
        for i, song in enumerate(pending.results[start:start + size], start + 1):
            platform = "QQ" if song.platform == "qq" else "网易云"
            alternatives = pending.alternatives.get(i, [])
            if alternatives:
                platform = "QQ / 网易云"
            netease = next((item for item in (song, *alternatives) if item.platform == "163"), None)
            origin = pending.netease_origins.get(netease.song_id) if netease else None
            badge = {1: "🌟 原曲", 2: "🎙️ 翻唱"}.get(origin)
            line = f"{i}. [{platform}] {song.display()}"
            if badge:
                line += f" · {badge}"
                if alternatives:
                    line += "（网易云）"
            lines.append(line)
        pfx = self.config.music.command_prefix
        lines.extend(["", f"▶️ 直接回复数字 {start + 1}（本次发{mode_label}）"])
        if pending.page > 0:
            lines.append(f"⬅️ {pfx}歌单 上一页")
        if pending.page + 1 < pages:
            lines.append(f"➡️ {pfx}歌单 下一页")
        other_platform = "QQ" if pending.platform == "163" else "网易"
        lines.extend([f"🔄 {pfx}换源 {other_platform}　·　✖️ {pfx}取消选歌",
                      f"⏳ 仅发起人可选，{self.config.music.selection_timeout_seconds} 秒内有效。翻页后序号连续。"])
        if self.config.music.auto_recall_selection:
            lines.append("🧹 自动撤回已开启，需要 SnowLuma 支持回执和撤回。")
        return "\n".join(lines)

    async def _do_search_and_send(self, query: str, platform: str = "", stream_id: str = "",
                                  *, user_id: str = "", send_mode: str = "", transport: str = "") -> tuple[bool, str]:
        if not stream_id or not user_id:
            return False, "Host 未提供聊天或用户身份，请由本人使用点歌命令，不能建立共享选歌列表"
        if not query.strip() or len(query) > 200:
            return False, "请提供1–200字的歌曲名或歌手"
        try:
            resolved = self._resolve_platform(platform)
            self._mode(send_mode)
        except ValueError as exc:
            return False, str(exc)
        key = (stream_id, user_id)
        pending = PendingSelection(query.strip(), resolved, send_mode, owner_id=user_id, transport=transport)
        async with self._pending_lock:
            self._clean_expired_pending()
            self._clean_recent_selections()
            recent = self._recent_selections.get(key)
            old = self._pending_choices.get(key)
            if (old and old.busy) or (recent and recent.busy):
                return False, "这首歌正在发送，请稍后再操作"
            if key not in self._pending_choices and len(self._pending_choices) >= 256:
                return False, "当前点歌请求较多，请稍后再试"
            if old is not None:
                self._drop_pending(key)
            self._recent_selections.pop(key, None)
            self._pending_choices[key] = pending
        api = self._get_api()
        platforms = ["qq", "163"] if resolved == "auto" else [resolved]
        failures = []

        async def search_one(name: str) -> list[SongInfo]:
            try:
                return await asyncio.wait_for(api.search(pending.query, name,
                    limit=self.config.music.search_limit), timeout=25)
            except MusicAPIResponseError as exc:
                failures.append(name)
                self.ctx.logger.error("音乐搜索失败(%s): %s", name, exc)
                if self._error_log is not None:
                    self._error_log.error("音乐搜索失败(%s): %s", name, exc.diagnostic_message())
                return []
            except Exception as exc:
                failures.append(name)
                self.ctx.logger.exception("音乐搜索异常(%s)", name)
                if self._error_log is not None:
                    self._error_log.exception("音乐搜索异常: platform=%s error=%s", name, type(exc).__name__)
                return []

        groups = await asyncio.gather(*(search_one(name) for name in platforms))
        if self._pending_choices.get(key) is not pending:
            return False, "该搜索已被更新或取消"
        if not self.config.music.auto_select_first and sum(map(len, groups)) > 1:
            ids = [song.song_id for group in groups for song in group if song.platform == "163"]
            if ids:
                try:
                    pending.netease_origins = await asyncio.wait_for(api.get_netease_origin_types(ids), timeout=2)
                except Exception as exc:
                    self.ctx.logger.warning("网易云版本标签查询失败: %s", type(exc).__name__)
        # Round robin preserves each provider's ranking and shows both platforms on page one.
        seen = set()
        recordings: dict[tuple[str, ...], int] = {}
        for i in range(max((len(group) for group in groups), default=0)):
            for group in groups:
                if i < len(group):
                    song = group[i]
                    identity = (song.platform, song.song_id)
                    if identity not in seen:
                        seen.add(identity)
                        metadata = tuple(" ".join(value.casefold().split()) for value in
                                         (song.name, song.artists, song.album))
                        can_group = self.config.music.group_cross_platform_results and all(metadata)
                        previous = recordings.get(metadata) if can_group else None
                        if previous is not None and pending.results[previous - 1].platform != song.platform:
                            variants = pending.alternatives.setdefault(previous, [])
                            if not variants:
                                variants.append(song)
                                continue
                        pending.results.append(song)
                        if can_group:
                            recordings.setdefault(metadata, len(pending.results))
        async with self._pending_lock:
            if self._pending_choices.get(key) is not pending:
                return False, "该搜索已被更新或取消"
            if not pending.results:
                del self._pending_choices[key]
                return False, "音源搜索暂不可用，请稍后再试" if failures else "没有找到匹配歌曲，请换关键词或音源"
        if (len(pending.results) == 1 and not pending.alternatives) or self.config.music.auto_select_first:
            return await self._selection_action(stream_id, user_id, "select", index=1, send_mode=send_mode)
        try:
            menu = self._format_results(pending)
            if failures:
                unavailable = "、".join("QQ 音乐" if name == "qq" else "网易云音乐" for name in sorted(failures))
                menu += f"\n⚠️ {unavailable}暂时查不到结果，已列出其他平台的候选。"
            sent = await self._send_selection_menu(key, pending, menu)
        except Exception:
            sent = False
        if not sent:
            async with self._pending_lock:
                if self._pending_choices.get(key) is pending:
                    del self._pending_choices[key]
            return False, "候选列表发送失败，请重新点歌"
        suffix = "；部分音源查询失败，可稍后换源重试" if failures else ""
        return True, f"已列出{len(pending.results)}首候选，请等待用户选择，不要自动替用户选歌{suffix}"

    async def _selection_action(self, stream_id: str, user_id: str, action: str, *, index: int = 0,
                                 send_mode: str = "", music_platform: str = "") -> tuple[bool, str]:
        if not user_id or not stream_id:
            return False, "Host 未提供用户身份，无法选择歌曲"
        key = (stream_id, user_id)
        async with self._pending_lock:
            self._clean_expired_pending()
            recent = self._recent_selections.get(key)
            if recent and recent.busy:
                return False, "这首歌正在发送，请稍后再操作"
            pending = self._pending_choices.get(key)
            if pending is None:
                return False, f"没有找到你的待选歌曲，列表可能已过期。\n🔎 发送 {self.config.music.command_prefix}点歌 歌名 重新搜索"
            if pending.busy:
                return False, "这首歌正在发送，请稍后再操作"
            if action == "cancel":
                self._drop_pending(key)
                self._recent_selections.pop(key, None)
                return True, "已取消选歌"
            if action == "source":
                query, mode = pending.query, pending.mode
            elif not pending.results:
                return False, "正在搜索，请稍候"
            elif action in {"next", "previous"}:
                old_page = pending.page
                page = pending.page + (1 if action == "next" else -1)
                if page < 0 or page * self.config.music.page_size >= len(pending.results):
                    return False, "已经是第一页" if page < 0 else "已经是最后一页"
                pending.page = page
            elif action == "select":
                if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= len(pending.results):
                    return False, f"序号超出范围，请输入1–{len(pending.results)}"
                try:
                    mode = self._mode(send_mode or pending.mode)
                except ValueError as exc:
                    return False, str(exc)
                song = pending.results[index - 1]
                alternate = None
                if mode == "voice" and pending.platform == "auto" and not music_platform:
                    alternate = next(iter(pending.alternatives.get(index, [])), None)
                if music_platform:
                    try:
                        platform = self._platform(music_platform)
                    except ValueError as exc:
                        return False, str(exc)
                    options = [song, *pending.alternatives.get(index, [])]
                    match = next((item for item in options if item.platform == platform), None)
                    if match is None:
                        return False, "该候选没有这个平台的版本，可以先换源搜索"
                    song = match
                pending.busy = True
            else:
                return False, "不支持的选歌操作"
        if action == "source":
            return await self._do_search_and_send(query, music_platform, stream_id, user_id=user_id,
                                                  send_mode=mode, transport=pending.transport)
        if action in {"next", "previous"}:
            try:
                sent = await self._send_selection_menu(key, pending, self._format_results(pending))
            except Exception:
                sent = False
            if not sent:
                pending.page = old_page
            return sent, "已更新候选页" if sent else "候选页发送失败，请重试翻页"
        sent = False
        completed = False
        switched = False
        try:
            if alternate is None:
                sent = await self._send_song(song, stream_id, mode=mode, silent=True)
            else:
                try:
                    sent = await self._send_song(song, stream_id, mode=mode, silent=True, report_unavailable=True)
                except AudioUnavailable:
                    sent = await self._send_song(alternate, stream_id, mode=mode, silent=True)
                    if sent:
                        song, switched = alternate, True
            completed = True
        finally:
            async with self._pending_lock:
                pending.busy = False
                if completed and self._pending_choices.get(key) is pending:
                    self._clean_recent_selections()
                    self._recent_selections.pop(key, None)
                    if len(self._recent_selections) >= 256:
                        oldest = next((k for k, value in self._recent_selections.items() if not value.busy), None)
                        if oldest is not None:
                            del self._recent_selections[oldest]
                    if len(self._recent_selections) < 256:
                        self._recent_selections[key] = RecentSelection(song)
                    if sent:
                        self._drop_pending(key)
                self._clean_expired_pending()
        kind = {"voice": "语音", "card": "标准卡片或回退链接", "link": "歌曲链接"}[mode]
        followup = "\n💡 回复「链接」或「卡片」可改发这首歌" if key in self._recent_selections else ""
        if sent:
            source = "QQ 音乐" if song.platform == "qq" else "网易云音乐"
            note = f" · 原平台音频不可用，已改用{source}" if switched else ""
            return True, f"已发送{kind}{note}\n🎵 {song.display()}{followup if mode == 'voice' else ''}"
        if key not in self._pending_choices:
            hint = followup or " 请重新点歌。"
            return False, f"「{song.name}」发送未成功，列表已过期。{hint}"
        return False, f"「{song.name}」发送未成功，已保留候选。\n🔁 回复 {index} 重试{followup}"

    @Tool("search_and_play_music", description=(
        "搜索音乐并列出候选，等待用户选歌。可指定音乐平台、歌手和本次发送方式；"
        "不要自动替用户选择候选，也不要失败后重复调用。"), parameters=[
        ToolParameterInfo(name="query", param_type=ToolParamType.STRING, description="歌曲名", required=True),
        ToolParameterInfo(name="artist", param_type=ToolParamType.STRING, description="指定歌手，可留空", required=False),
        ToolParameterInfo(name="music_platform", param_type=ToolParamType.STRING, description="auto/qq/163，留空用默认值", required=False),
        ToolParameterInfo(name="send_mode", param_type=ToolParamType.STRING, description="voice/card/link，留空用默认值", required=False),
    ])
    async def handle_search_music(self, query: str = "", artist: str = "", music_platform: str = "",
                                   send_mode: str = "", stream_id: str = "", **kwargs: Any) -> dict[str, str]:
        ok, text = await self._do_search_and_send(" ".join(part for part in (query.strip(), artist.strip()) if part),
            music_platform, stream_id, user_id=str(kwargs.get("user_id") or ""), send_mode=send_mode,
            transport=str(kwargs.get("platform") or ""))
        return {"name": "search_and_play_music", "content": text, "status": "success" if ok else "failed"}

    @Tool("select_music", description="用户明确要求选第几首、翻页、换源或取消选歌时使用；只操作当前用户自己的候选。", parameters=[
        ToolParameterInfo(name="action", param_type=ToolParamType.STRING, description="select/next/previous/source/cancel", required=True),
        ToolParameterInfo(name="index", param_type=ToolParamType.INTEGER, description="整份候选列表中的序号，选择时必填", required=False),
        ToolParameterInfo(name="send_mode", param_type=ToolParamType.STRING, description="voice/card/link", required=False),
        ToolParameterInfo(name="music_platform", param_type=ToolParamType.STRING, description="换源时指定 auto/qq/163，选择合并候选时可指定 qq/163", required=False),
    ])
    async def handle_select_music(self, action: str = "select", index: int = 0, send_mode: str = "",
                                   music_platform: str = "", stream_id: str = "", **kwargs: Any) -> dict[str, str]:
        if action == "source" and not music_platform:
            return {"name": "select_music", "content": "换源需要指定平台", "status": "failed"}
        ok, text = await self._selection_action(stream_id, str(kwargs.get("user_id") or ""), action,
            index=index, send_mode=send_mode, music_platform=music_platform)
        return {"name": "select_music", "content": text, "status": "success" if ok else "failed"}

    @Command("点歌", description="搜索音乐，支持平台与 --模式 语音/卡片/链接",
             pattern=r"^(?P<pfx>\S)点歌\s+(?P<args>.+)$")
    async def handle_music_command(self, stream_id: str = "", **kwargs: Any) -> tuple[bool, str, bool]:
        text = str(kwargs.get("text") or "")
        groups = kwargs.get("matched_groups") or {}
        prefix = self.config.music.command_prefix
        if groups.get("pfx", text[:1]) != prefix:
            return False, "", False
        args = str(groups.get("args") or text[len(prefix + "点歌"):]).strip()
        mode = ""
        if " --模式 " in args:
            args, mode = args.rsplit(" --模式 ", 1)
            mode = mode.strip()
        first, space, rest = args.partition(" ")
        platform = ""
        try:
            platform = self._platform(first)
        except ValueError:
            pass
        else:
            args = rest.strip() if space else ""
        ok, result = await self._do_search_and_send(args, platform, stream_id,
            user_id=str(kwargs.get("user_id") or ""), send_mode=mode,
            transport=str(kwargs.get("platform") or ""))
        if not ok:
            await self.ctx.send.text(f"⚠️ {result}", stream_id)
        return ok, result, True

    def _queue_numeric_selection(self, stream_id: str, user_id: str, text: str) -> bool:
        if not re.fullmatch(r"[0-9]{1,3}", text.strip()):
            return False
        self._clean_expired_pending()
        key = (stream_id, user_id)
        pending = self._pending_choices.get(key)
        if pending is None or not pending.results:
            return False
        if pending.queued or pending.busy:
            return True
        pending.queued = True

        async def select() -> None:
            pending.queued = False
            if self._pending_choices.get(key) is not pending:
                return
            try:
                ok, result = await self._selection_action(stream_id, user_id, "select", index=int(text))
                await self.ctx.send.text(f"{'✅' if ok else '⚠️'} {result}", stream_id)
            except Exception:
                self.ctx.logger.exception("数字选歌处理失败")

        task = asyncio.create_task(select())
        self._menu_tasks.add(task)
        task.add_done_callback(self._menu_tasks.discard)
        return True

    def _queue_recent_delivery(self, stream_id: str, user_id: str, text: str) -> bool:
        mode = {"链接": "link", "卡片": "card"}.get(text.strip())
        if mode is None:
            return False
        self._clean_recent_selections()
        key = (stream_id, user_id)
        recent = self._recent_selections.get(key)
        if recent is None:
            return False
        pending = self._pending_choices.get(key)
        if recent.busy or (pending and (pending.busy or pending.queued)):
            return True
        recent.busy = True

        async def deliver() -> None:
            try:
                sent = await self._send_song(recent.song, stream_id, mode=mode, silent=True)
                if sent:
                    async with self._pending_lock:
                        if pending is not None and self._pending_choices.get(key) is pending:
                            self._drop_pending(key)
                elif self._recent_selections.get(key) is recent:
                    await self.ctx.send.text(f"⚠️ 「{recent.song.name}」改发未成功", stream_id)
            except Exception:
                self.ctx.logger.exception("改发歌曲失败")
            finally:
                recent.busy = False

        task = asyncio.create_task(deliver())
        self._menu_tasks.add(task)
        task.add_done_callback(self._menu_tasks.discard)
        return True

    @Command("歌单", description="翻页、换源、取消和查看音源",
        pattern=r"^(?P<pfx>\S)(?P<action>歌单|换源|取消选歌|音源)(?:\s+(?P<args>.*))?$")
    async def handle_select_command(self, stream_id: str = "", **kwargs: Any) -> tuple[bool, str, bool]:
        prefix = self.config.music.command_prefix
        text = str(kwargs.get("text") or "")
        groups = kwargs.get("matched_groups") or {}
        if not groups:
            match = re.fullmatch(r"(?P<pfx>\S)(?P<action>歌单|换源|取消选歌|音源)(?:\s+(?P<args>.*))?", text)
            groups = match.groupdict() if match else {}
        if groups.get("pfx") != prefix:
            return False, "", False
        action, args = groups.get("action"), (groups.get("args") or "").strip()
        if action == "音源":
            bridge = "聚合接口优先，失败回退平台原接口" if self.config.source_bridge.enabled else "平台原接口"
            default = {"auto": "QQ 音乐 + 网易云音乐", "qq": "QQ 音乐", "163": "网易云音乐"}
            label = default.get(self.config.music.default_platform, self.config.music.default_platform)
            message = (f"🎧 点歌音源\n⭐ 默认搜索 {label}\n⚙️ {bridge}（配置状态）\n\n"
                       f"🔎 {prefix}点歌 QQ 歌名\n🔎 {prefix}点歌 网易 歌名\n"
                       f"🔄 已有候选时，发送 {prefix}换源 全部 重新搜索两个平台")
            await self.ctx.send.text(message, stream_id)
            return True, message, True
        params: dict[str, Any] = {}
        if action == "取消选歌":
            verb = "cancel"
        elif action == "换源":
            if not args:
                await self.ctx.send.text(f"🔄 请指定要换到的平台。\n{prefix}换源 QQ / 网易 / 全部（三选一）", stream_id)
                return False, "缺少平台", True
            verb, params = "source", {"music_platform": args}
        else:
            verb = {"下一页": "next", "上一页": "previous", "next": "next", "previous": "previous"}.get(args, "")
            if not verb:
                await self.ctx.send.text(f"📄 请指定翻页方向。\n➡️ {prefix}歌单 下一页\n⬅️ {prefix}歌单 上一页", stream_id)
                return False, "缺少有效翻页方向", True
        ok, result = await self._selection_action(stream_id, str(kwargs.get("user_id") or ""), verb, **params)
        if verb not in {"source", "next", "previous"} or not ok:
            await self.ctx.send.text(f"{'✅' if ok else '⚠️'} {result}", stream_id)
        return ok, result, True


    async def _send_voice_audio(self, song: SongInfo, stream_id: str, *, silent: bool = False) -> bool:
        """获取歌曲音频并以语音消息发送。"""
        voice_source, audio_cache = await self._acquire_voice_send()
        cache_path = None
        try:
            api = self._get_api()

            bridge_enabled = getattr(getattr(self.config, "source_bridge", None), "enabled", False)
            if voice_source == "local" and bridge_enabled:
                if audio_cache is None:
                    raise RuntimeError("本地音乐缓存尚未初始化")
                cache_path = await api.prepare_local_audio(song, audio_cache)
                voice_reference = audio_cache.adapter_path(cache_path)
            else:
                media_id = song.media_id
                if song.platform == "qq" and not media_id:
                    detail = await api.get_qq_song_detail(song.song_id)
                    if detail:
                        media_id = detail.media_id
                audio_url = await api.get_song_url(song.song_id, song.platform, media_id,
                                                   mp3_only=voice_source == "local")
                if not audio_url:
                    raise AudioUnavailable("音乐平台未返回可用音频")
                voice_reference = audio_url
                if voice_source == "local":
                    if audio_cache is None:
                        raise RuntimeError("本地音乐缓存尚未初始化")
                    cache_path = await audio_cache.get_or_download(song.platform, song.song_id, audio_url)
                    voice_reference = audio_cache.adapter_path(cache_path)

            sent = await self.ctx.send.custom(
                "voiceurl",
                {"url": voice_reference},
                stream_id,
            )
            if sent:
                return True

            self.ctx.logger.warning(
                "发送语音音频失败: platform=%s song_id=%s source=%s",
                song.platform,
                song.song_id,
                voice_source,
            )
            if not silent:
                await self.ctx.send.text(song.display(), stream_id)
            return False
        finally:
            if cache_path is not None and audio_cache is not None:
                await audio_cache.release(cache_path)
            await self._release_voice_send()

    async def _send_song(self, song: SongInfo, stream_id: str, *, silent: bool = False,
                         mode: str = "", report_unavailable: bool = False) -> bool:
        """发送歌曲语音音频或音乐卡片，根据 play_mode 配置分发。"""
        mode = self._mode(mode)
        if mode == "link":
            return await self._send_song_link(song, stream_id)
        if mode == "card":
            return await self._send_music_card(song, stream_id, silent=silent)

        try:
            return await self._send_voice_audio(song, stream_id, silent=silent)
        except AudioUnavailable:
            if report_unavailable:
                raise
            if not silent:
                await self.ctx.send.text(f"找到「{song.display()}」但音乐平台未返回可用音频", stream_id)
            return False
        except AudioCacheError as exc:
            self.ctx.logger.warning("缓存音乐音频失败: %s %s: %s", song.platform, song.song_id, exc)
        except Exception:
            self.ctx.logger.exception("发送语音音频异常: %s %s", song.platform, song.song_id)

        if not silent:
            await self.ctx.send.text(f"「{song.display()}」的语音音频发送失败", stream_id)
        return False

    # ===== 生命周期 =====

    async def on_load(self) -> None:
        """插件加载，初始化本地音乐缓存。"""
        self._error_log = PluginErrorLog(self.ctx.paths.data_dir / "log")
        try:
            await self._start_audio_cache()
        except Exception:
            self._error_log.close()
            self._error_log = None
            raise
        self.ctx.logger.info("麦麦点歌增强 %s 已加载", PLUGIN_VERSION)

    async def on_unload(self) -> None:
        """插件卸载，关闭 HTTP 客户端和缓存任务。"""
        try:
            self._recent_selections.clear()
            tasks = tuple(self._menu_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._stop_audio_cache()
            if self._api is not None:
                await self._api.close()
                self._api = None
            for key in list(self._pending_choices):
                self._drop_pending(key)
        finally:
            if self._error_log is not None:
                self._error_log.close()
                self._error_log = None
        self.ctx.logger.info("音乐插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        """配置热重载，重建 API 客户端和本地音乐缓存。"""
        del config_data, version
        if scope != "self":
            return

        async with self._pending_lock:
            self._recent_selections.clear()
            for key in list(self._pending_choices):
                self._drop_pending(key)
        await self._stop_audio_cache()
        if self._api is not None:
            await self._api.close()
            self._api = None
        await self._start_audio_cache()
        self.ctx.logger.info("音乐插件配置已更新，API 客户端和音乐缓存已重置")

    # ===== EventHandler 组件 =====


    @HookHandler(
        "chat.receive.after_process",
        name="music_url_parser",
        description="处理有效候选的数字回复，以及音乐链接和卡片",
        mode=HookMode.BLOCKING,
        order="normal",
        timeout_ms=15000,
    )
    async def handle_music_url_parse(self, **kwargs: Any) -> dict[str, Any]:
        """Parse only Host-provided message content; never fetch raw messages from a client."""
        message = kwargs.get("message")
        if not isinstance(message, dict):
            return {"action": "continue"}
        session_id = str(message.get("session_id") or "")
        text = str(message.get("processed_plain_text") or "")
        if not text:
            parts = []
            for segment in message.get("raw_message", []) if isinstance(message.get("raw_message"), list) else []:
                if not isinstance(segment, dict) or segment.get("type") != "text":
                    continue
                data = segment.get("data", "")
                parts.append(str(data.get("text") or "") if isinstance(data, dict) else str(data))
            text = " ".join(parts).strip()
        if not text or not session_id:
            return {"action": "continue"}
        info = message.get("message_info")
        user = info.get("user_info") if isinstance(info, Mapping) else None
        user_id = str(user.get("user_id") or "") if isinstance(user, Mapping) else ""
        if user_id and (self._queue_numeric_selection(session_id, user_id, text)
                        or self._queue_recent_delivery(session_id, user_id, text)):
            return {"action": "abort"}
        card = parse_music_card_text(text) if self.config.music.auto_parse_card else None
        if not self.config.music.auto_parse_url and card is None:
            return {"action": "continue"}
        urls = list(dict.fromkeys(([card.url] if card and card.url else []) + extract_urls(text)))
        for url in urls:
            parsed = parse_music_url(url)
            if not parsed:
                continue
            platform, song_id = parsed
            api = self._get_api()
            try:
                if platform in {"163_short", "qq_short"}:
                    resolved = await api.resolve_short_url(url)
                    parsed = parse_music_url(resolved) if resolved else None
                    if not parsed or parsed[0] in {"163_short", "qq_short"}:
                        continue
                    platform, song_id = parsed
                song = await api.get_song_detail(song_id, platform)
                if song is None:
                    continue
                sent = await self._send_song(song, session_id)
                return {"action": "abort" if sent else "continue"}
            except Exception as exc:
                self.ctx.logger.warning("分享歌曲解析失败: platform=%s error=%s", platform, type(exc).__name__)
                return {"action": "continue"}
        if card is not None:
            try:
                sent = await self.ctx.send.text("这张音乐分享没有可解析的歌曲链接，请补发 QQ 音乐或网易云歌曲链接。", session_id)
                return {"action": "abort" if sent else "continue"}
            except Exception:
                self.ctx.logger.warning("补充歌曲链接提示发送失败")
        return {"action": "continue"}


def create_plugin() -> MusicPlugin:
    """创建音乐插件实例。"""
    return MusicPlugin()
