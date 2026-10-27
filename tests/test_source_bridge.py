import importlib.util
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

PLUGIN = Path(__file__).resolve().parents[1]
package = types.ModuleType('local_music_bridge_tests')
package.__path__ = [str(PLUGIN)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(package.__name__ + '.source_bridge', PLUGIN / 'source_bridge.py')
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)


@pytest.mark.parametrize('url', ['http://127.0.0.1/a.mp3', 'file:///C:/Windows/a',
    'https://qq.com.evil.test/a', 'https://aqqmusic.tc.qq.com:1234/a',
    'https://user:pass@aqqmusic.tc.qq.com/a', 'https://aqqmusic.tc.qq.com:bad/a'])
def test_rejects_untrusted_media_urls(url):
    assert not bridge._allowed_media_url(url)


def test_explicit_artist_does_not_silently_select_someone_else():
    assert bridge._matches_request('I Really Want to Stay at Your House Rosa Walton',
        'I Really Want to Stay at Your House', 'Rosa Walton,Hallie Coggins')
    assert not bridge._matches_request('I Really Want to Stay at Your House Rosa Walton',
        'I Really Want to Stay at Your House', 'Cyberpunk')
    assert not bridge._matches_request('稻香 Lucky小爱', '稻香', 'Jay')
    assert not bridge._matches_request('稻香 Lucky小爱', '晴天', 'Lucky小爱')
    assert bridge._matches_request('周杰伦的稻香', '稻香', '周杰伦')


@pytest.mark.asyncio
async def test_search_keeps_exact_recording_and_does_not_send_account_credentials():
    def handler(request):
        assert request.url.host == 'music.txqq.pro'
        assert 'cookie' not in request.headers and 'authorization' not in request.headers
        assert b'type=qq' in request.content
        return httpx.Response(200, json={'code': 200, 'data': [
            {'songid': 'cover', 'title': 'Example Song (COVER)', 'author': 'Other', 'url': 'https://aqqmusic.tc.qq.com/c.m4a'},
            {'songid': 'bad', 'title': 'Example Song', 'author': 'Artist', 'url': 'http://127.0.0.1/a'},
            {'songid': 'right', 'title': 'Example Song', 'author': 'Artist', 'url': 'https://aqqmusic.tc.qq.com/a.m4a'}]})
    client = bridge.SourceAwareSearchClient(thirdparty_enabled=True, qq_cookie={'uin': '123', 'qqmusic_key': 'private'})
    await client._public_client.aclose()
    client._public_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        songs = await client.search('Example Song Artist', 'qq', 5)
        assert [s.song_id for s in songs] == ['right']
        assert (await client.get_song_url('right', 'qq')).endswith('a.m4a')
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_redirect_to_localhost_is_rejected(tmp_path):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/internal'})
    client = bridge.SourceAwareSearchClient(thirdparty_enabled=True)
    await client._public_client.aclose()
    client._public_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(bridge.AudioCacheError):
            await client._download_media('https://aqqmusic.tc.qq.com/a', tmp_path/'audio', 'qq', 100)
        assert len(requests) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_metadata_mismatch_prevents_download():
    client = bridge.SourceAwareSearchClient(thirdparty_enabled=True)
    client._qq_client.post = AsyncMock(return_value=httpx.Response(200,
        request=httpx.Request('POST', 'https://u.y.qq.com/'), json={'req_0': {'data': {'track_info': {
            'mid': 'wrong', 'name': 'Example Song', 'interval': 240, 'singer': [{'name': 'Artist'}]}}}}))
    try:
        with pytest.raises(bridge.AudioCacheError, match='ID'):
            await client._expected_duration(bridge.SongInfo('right', 'Example Song', 'Artist', '', 'qq'))
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_source_failure_falls_back_to_official(monkeypatch):
    client = bridge.SourceAwareSearchClient(thirdparty_enabled=True)
    client._search_public = AsyncMock(side_effect=httpx.ConnectError('unavailable'))
    fallback = AsyncMock(return_value=[bridge.SongInfo('123', 'Song', 'Artist', '', '163')])
    monkeypatch.setattr(bridge.MusicSearchClient, 'search', fallback)
    try:
        result = await client.search('Song', '163')
        assert result[0].song_id == '123'
        fallback.assert_awaited_once()
    finally:
        await client.close()


@pytest.fixture
def m4a_file(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg/ffprobe unavailable')
    path = tmp_path/'fixture.m4a'
    result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        'sine=frequency=440:duration=2', '-c:a', 'aac', str(path)], capture_output=True, timeout=15)
    assert result.returncode == 0
    return path


async def prepare_test_client(tmp_path, m4a_file, expected):
    client = bridge.SourceAwareSearchClient(thirdparty_enabled=True)
    client._expected_duration = AsyncMock(return_value=expected)
    client.get_song_url = AsyncMock(return_value='https://aqqmusic.tc.qq.com/song.m4a')
    async def download(url, path, platform, max_bytes):
        shutil.copyfile(m4a_file, path)
    client._download_media = AsyncMock(side_effect=download)
    cache = bridge.MusicAudioCache(str(tmp_path/'cache'), str(tmp_path/'cache'),
        max_size_bytes=1024*1024, expire_seconds=86400, max_file_size_bytes=1024*1024,
        download_timeout_seconds=10)
    await cache.initialize()
    return client, cache


@pytest.mark.asyncio
async def test_real_aac_is_transcoded_to_mp3_and_reuses_pinned_cache(tmp_path, m4a_file):
    client, cache = await prepare_test_client(tmp_path, m4a_file, 2)
    song = bridge.SongInfo('right', 'Song', 'Artist', '', 'qq')
    try:
        first = await client.prepare_local_audio(song, cache)
        duration, codec = await bridge.probe_audio(first)
        assert codec == 'mp3' and 1.9 <= duration <= 2.2
        assert first.absolute() in cache._active_paths
        await cache.release(first)
        second = await client.prepare_local_audio(song, cache)
        assert second == first
        client._download_media.assert_awaited_once()
        await cache.release(second)
        assert not cache._active_paths and not list(cache.storage_dir.glob('*.part'))
    finally:
        await cache.close()
        await client.close()


@pytest.mark.asyncio
async def test_truncated_audio_is_not_cached_or_sent(tmp_path, m4a_file):
    client, cache = await prepare_test_client(tmp_path, m4a_file, 240)
    try:
        with pytest.raises(bridge.AudioCacheError, match='试听'):
            await client.prepare_local_audio(bridge.SongInfo('right', 'Song', 'Artist', '', 'qq'), cache)
        assert not list(cache.storage_dir.iterdir()) and not cache._active_paths
    finally:
        await cache.close()
        await client.close()
