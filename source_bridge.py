# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz. Modified 2026-10-27.
"""QQ/NetEase source bridge for MaiBot Music Enhanced.

Protocol reference: Zhalslar/astrbot_plugin_music (GPLv3), TXQQMusic at
dc009ce778520e740baf35de4d90c4d778e5009b. See NOTICE.md and licenses/.
This implementation uses the MaiBot API client, with no AstrBot runtime dependency.
No login cookies or provider secrets are sent to the aggregation service.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import shutil
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlparse
from weakref import WeakValueDictionary

import httpx

from .audio_cache import AudioCacheError, MusicAudioCache
from .music_api import MusicAPIResponseError, MusicSearchClient, SongInfo

logger = logging.getLogger(__name__)
AGGREGATOR = 'https://music.txqq.pro/'


def _normalized(value: str) -> str:
    return ''.join(c for c in value.casefold() if c.isalnum())


def _matches_request(query: str, title: str, artists: str) -> bool:
    variants = ('cover', 'remix', 'live', 'instrumental', '翻唱', '伴奏', '纯音乐', '现场', '加速', '降速')
    if any(t in title.casefold() and t not in query.casefold() for t in variants):
        return False
    base = _normalized(re.sub(r'[(（\[【].*?[)）\]】]', '', title))
    needle = _normalized(query)
    fillers = ('我想听', '我要听', '帮我放', '播放', '点歌', '完整版', '原唱', '无损', '一首', '来首', '的')
    if not base or not needle:
        return False
    if base not in needle:
        artist_parts = [_normalized(a) for a in re.split(r'[,、/&]', artists) if _normalized(a)]
        if any(needle in a for a in artist_parts):
            return True
        title_query = needle
        for artist in artist_parts:
            title_query = title_query.replace(artist, '')
        for filler in fillers:
            title_query = title_query.replace(filler, '')
        return bool(title_query) and (title_query in base or SequenceMatcher(None, title_query, base).ratio() >= .8)
    remainder = needle.replace(base, '', 1)
    for filler in fillers:
        remainder = remainder.replace(filler, '')
    actual = _normalized(artists)
    return not remainder or remainder in actual or (bool(actual) and actual in remainder)


def _allowed_media_url(url: str) -> bool:
    try:
        p = urlparse(url)
        host = (p.hostname or '').lower()
        return (p.scheme in {'http', 'https'} and not p.username and not p.password
                and p.port in {None, 80, 443}
                and (host.endswith('.qq.com') or host.endswith('.music.126.net')
                     or host in {'music.163.com', 'interface.music.163.com'}))
    except ValueError:
        return False


def _check_duration(actual: float, expected: float) -> None:
    if not math.isfinite(actual) or not math.isfinite(expected) or expected <= 0:
        raise AudioCacheError('无法核验歌曲完整时长')
    tolerance = max(3.0, expected * .03)
    if actual < expected - tolerance:
        raise AudioCacheError(f'音源只有 {actual:.1f} 秒，歌曲标称 {expected:.1f} 秒，跳过试听或截短片段')
    if actual > expected + tolerance:
        raise AudioCacheError('音频时长与歌曲详情不符，跳过不匹配版本')


async def _process(*args: str, timeout: int = 20) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    if process.returncode:
        raise AudioCacheError('音频探测或转码失败')
    return stdout


async def probe_audio(path: Path) -> tuple[float, str]:
    executable = shutil.which('ffprobe')
    if not executable:
        raise AudioCacheError('完整音频校验需要 ffprobe')
    raw = await _process(executable, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_entries',
                         'format=duration:stream=codec_type,codec_name', '-of', 'json', str(path))
    data = json.loads(raw)
    streams = data.get('streams', [])
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    if not audio or any(s.get('codec_type') not in {'audio', 'video'} for s in streams):
        raise AudioCacheError('文件不包含有效音频')
    return float(data['format']['duration']), str(audio[0]['codec_name'])


class SourceAwareSearchClient(MusicSearchClient):
    def __init__(self, *args, thirdparty_enabled: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.thirdparty_enabled = thirdparty_enabled
        self._public_client = httpx.AsyncClient(timeout=15, follow_redirects=False,
                                                headers={'User-Agent': 'Mozilla/5.0'})
        self._media_urls: dict[tuple[str, str], str] = {}
        self._audio_locks = WeakValueDictionary()

    async def close(self):
        await self._public_client.aclose()
        await super().close()

    async def search(self, query: str, platform: str, limit: int = 5) -> list[SongInfo]:
        if self.thirdparty_enabled:
            try:
                songs = await self._search_public(query, platform, limit)
                if songs:
                    return songs
            except Exception as exc:
                logger.warning('聚合音源不可用，回退平台接口: platform=%s error=%s', platform, type(exc).__name__)
        songs = await super().search(query, platform, limit)
        if self.thirdparty_enabled:
            return [s for s in songs if _matches_request(query, s.name, s.artists)]
        return songs

    async def _search_public(self, query: str, platform: str, limit: int) -> list[SongInfo]:
        source = {'qq': 'qq', '163': 'netease'}.get(platform)
        if not source:
            return []
        response = await self._public_client.post(
            AGGREGATOR, data={'input': query, 'filter': 'name', 'type': source, 'page': 1},
            headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': AGGREGATOR})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get('code') != 200 or not isinstance(data.get('data'), list):
            raise MusicAPIResponseError('聚合音源搜索响应无效')
        songs = []
        for item in data['data'][:30]:
            if not isinstance(item, dict):
                continue
            sid, title = str(item.get('songid') or ''), str(item.get('title') or '')
            artists, url = str(item.get('author') or ''), str(item.get('url') or item.get('link') or '')
            if not sid or not title or not _allowed_media_url(url):
                continue
            if not _matches_request(query, title, artists):
                continue
            self._media_urls[(platform, sid)] = url
            songs.append(SongInfo(sid, title, artists, '', platform))
        # Prefer exact titles, then query matches including artist names.
        needle = _normalized(query)
        def rank(song):
            title = _normalized(song.name)
            display = _normalized(song.name + song.artists)
            return (title == needle, title in needle or needle in title,
                    max(SequenceMatcher(None, needle, title).ratio(),
                        SequenceMatcher(None, needle, display).ratio()))
        songs.sort(key=rank, reverse=True)
        # Bound expiring URL state on this long-running client.
        if len(self._media_urls) > 300:
            self._media_urls = {key: self._media_urls[key] for key in list(self._media_urls)[-100:]}
        return songs[:max(1, min(limit, 10))]

    async def get_song_url(self, song_id, platform, media_id='', *, mp3_only=False):
        if self.thirdparty_enabled and (platform, song_id) in self._media_urls:
            return self._media_urls[(platform, song_id)]
        return await super().get_song_url(song_id, platform, media_id, mp3_only=mp3_only)

    async def _expected_duration(self, song: SongInfo) -> float:
        if song.platform == 'qq':
            response = await self._qq_client.post('https://u.y.qq.com/cgi-bin/musicu.fcg', json={
                'req_0': {'module': 'music.pf_song_detail_svr', 'method': 'get_song_detail_yqq',
                          'param': {'song_mid': song.song_id}},
                'comm': {'format': 'json', 'ct': 19, 'cv': 0}})
            response.raise_for_status()
            track = response.json()['req_0']['data']['track_info']
            sid, expected = str(track.get('mid') or ''), float(track.get('interval') or 0)
            artists = ','.join(str(s.get('name') or '') for s in track.get('singer', []))
        else:
            response = await self._netease_client.get('https://music.163.com/api/song/detail',
                params={'id': song.song_id, 'ids': json.dumps([int(song.song_id)])})
            response.raise_for_status()
            track = response.json()['songs'][0]
            sid, expected = str(track.get('id') or ''), float(track.get('duration') or track.get('dt') or 0) / 1000
            artists = ','.join(str(s.get('name') or '') for s in track.get('artists', track.get('ar', [])))
        # Verify the ID and title against the platform, rather than trusting aggregation metadata.
        if sid != song.song_id or _normalized(str(track.get('name') or '')) != _normalized(song.name):
            raise AudioCacheError('音源的歌曲 ID 或标题与平台详情不符')
        requested_artists = {_normalized(a) for a in re.split(r'[,、/&]', song.artists) if _normalized(a)}
        actual_artists = {_normalized(a) for a in re.split(r'[,、/&]', artists) if _normalized(a)}
        if requested_artists and not requested_artists.intersection(actual_artists):
            raise AudioCacheError('音源歌手与平台详情不符')
        if expected <= 0 or expected > 1800:
            raise AudioCacheError('歌曲缺少有效时长或超过 30 分钟')
        return expected

    async def _download_media(self, url: str, path: Path, platform: str, max_bytes: int):
        referer = 'https://y.qq.com/' if platform == 'qq' else 'https://music.163.com/'
        for _ in range(6):
            if not _allowed_media_url(url):
                raise AudioCacheError('音频地址不在 QQ/网易云媒体域名内')
            async with self._public_client.stream('GET', url, headers={'Referer': referer}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get('location', ''))
                    continue
                response.raise_for_status()
                length = response.headers.get('content-length', '')
                if length.isdecimal() and int(length) > max_bytes:
                    raise AudioCacheError('音频超过单文件大小限制')
                total = 0
                with path.open('wb') as output:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise AudioCacheError('音频超过单文件大小限制')
                        output.write(chunk)
                return
        raise AudioCacheError('音频重定向次数过多')

    async def prepare_local_audio(self, song: SongInfo, cache: MusicAudioCache) -> Path:
        key = (song.platform, song.song_id)
        lock = self._audio_locks.setdefault(key, asyncio.Lock())
        async with lock:
            expected = await self._expected_duration(song)
            platform = 'full_' + song.platform
            target = cache.storage_dir / (cache._build_cache_key(platform, song.song_id) + '.mp3')
            if cache._is_valid_cache_file(target):
                actual, _ = await probe_audio(target)
                _check_duration(actual, expected)
                return await cache.get_or_download(platform, song.song_id, '')
            url = await self.get_song_url(song.song_id, song.platform, song.media_id, mp3_only=False)
            if not url:
                raise AudioCacheError('音源未返回可用音频')
            fd, temporary = tempfile.mkstemp(prefix='.full-audio-', suffix='.part', dir=cache.storage_dir)
            os.close(fd)
            downloaded = Path(temporary)
            converted = downloaded.with_name(downloaded.name + '.mp3.part')
            try:
                await self._download_media(url, downloaded, song.platform, cache.max_file_size_bytes)
                actual, codec = await probe_audio(downloaded)
                _check_duration(actual, expected)
                if codec == 'mp3' and cache._is_valid_cache_file(downloaded):
                    downloaded.replace(target)
                else:
                    executable = shutil.which('ffmpeg')
                    if not executable:
                        raise AudioCacheError('M4A 转 MP3 需要 ffmpeg')
                    await _process(executable, '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(downloaded),
                        '-map', '0:a:0', '-vn', '-c:a', 'libmp3lame', '-b:a', '192k',
                        '-f', 'mp3', str(converted), timeout=120)
                    if converted.stat().st_size > cache.max_file_size_bytes or not cache._is_valid_cache_file(converted):
                        raise AudioCacheError('转码结果不是有效 MP3 或超过大小限制')
                    duration, _ = await probe_audio(converted)
                    _check_duration(duration, expected)
                    converted.replace(target)
                # Reuse the existing cache pinning, quota enforcement and eviction lifecycle.
                pinned = await cache.get_or_download(platform, song.song_id, url)
                try:
                    async with cache._state_lock:
                        await asyncio.to_thread(cache._enforce_size_limit_sync, target)
                except BaseException:
                    await cache.release(pinned)
                    raise
                logger.info('完整音频已校验: platform=%s song_id=%s expected=%.1fs actual=%.1fs',
                            song.platform, song.song_id, expected, actual)
                return pinned
            finally:
                downloaded.unlink(missing_ok=True)
                converted.unlink(missing_ok=True)
