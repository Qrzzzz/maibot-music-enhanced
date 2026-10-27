# 来源、署名与许可证

**基于磐冰的 maibot-music 增强，音源接入参考 Zhalslar 的 AstrBot 插件。**

本项目由 **Qrzzzz** 独立维护。Qrzzzz 署名为维护者和新增代码作者，原作者保留原代码的著作权。

## MaiBot 插件底座

- 作者：磐冰（[pan-ice](https://github.com/pan-ice)）。
- 项目：[pan-ice/maibot-music](https://github.com/pan-ice/maibot-music)。
- 基础版本：1.4.6，提交 `2d930f8ce54b725e1768012f3020fb1de3bf456d`。
- 原版权声明：`Copyright (c) 2026 磐冰`。
- 原许可证：MIT，完整原文保存在 [licenses/maibot-music-MIT.txt](licenses/maibot-music-MIT.txt)，不删除或替换其版权与许可声明。
- 沿用的主体包括 `music_api.py`、`audio_cache.py`、`url_parser.py`、`error_log.py`、`__init__.py` 和三个原有测试文件；`plugin.py` 在原版上修改，1.1.0 还对 `music_api.py`、`audio_cache.py` 和部分测试进行了发送路线与下载校验调整。

## AstrBot 音源接入参考

- 作者：[Zhalslar](https://github.com/Zhalslar)。
- 项目：[Zhalslar/astrbot_plugin_music](https://github.com/Zhalslar/astrbot_plugin_music)。
- 参考版本：3.4.5，提交 `dc009ce778520e740baf35de4d90c4d778e5009b`。
- 参考文件：`core/platform/txqq.py`，用于理解 TXQQ 的 HTTP 请求字段与搜索结果字段。
- 上游许可证：GNU GPLv3，完整原文保存在 [licenses/astrbot_plugin_music-GPL-3.0.txt](licenses/astrbot_plugin_music-GPL-3.0.txt)。
- `source_bridge.py` 使用 MaiBot 的数据模型和 HTTP 客户端接入音源，不依赖 AstrBot SDK，也不附带 AstrBot 主程序。

## 本项目新增与修改

`Copyright (c) 2026 Qrzzzz`，修改日期：2026-10-27。

- 聚合音源与平台原接口回退、歌曲和歌手匹配。
- 平台歌曲 ID、标题、歌手及音频时长核验，过滤试听或截短音频。
- 音频下载、MP3 转码、受限下载地址与现有缓存生命周期的整合。
- 独立插件身份、默认配置、可移植缓存路径、增强测试、文档和发布工具。

本项目作为整体以 **GPL-3.0-only** 发布，完整条款见根目录 [LICENSE](LICENSE)。原 MIT 部分的许可声明一并保留；本项目的 GPL 发布选择不撤销原作者对原代码的 MIT 授权。新提交的代码默认遵循本项目的 GPL-3.0-only 许可。

## 双端发送合约测试来源

1.1.0 的 `tests/fixtures/adapters/` 提取了 MaiBot Team 官方适配器的五个纯出站编码方法，用于离线测试 SDK 发出的语音和标准卡片格式，不包含或启动客户端。其原代码的 GPLv3-or-later 声明保留在测试夹具头部：

- [MaiBot-Napcat-Adapter](https://github.com/Mai-with-u/MaiBot-Napcat-Adapter)，提交 `d87203e2eff1835895ee34196b17a571dc6bbe24`。
- [MaiBot-SnowLuma-Adapter](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter)，提交 `ab751ae5c11f501e0158e33cacc321b33e34ef0c`。

这两处上游在 `_manifest.json` 明确声明 `GPL-v3.0-or-later`，所核对提交的根目录未附独立 LICENSE 文件。本包保留声明、作者、提交和源码哈希，GNU GPLv3 全文随根目录 LICENSE 分发。详见 `tests/fixtures/adapters/provenance.json`。

文件来源与上游文件哈希见 [UPSTREAM.json](UPSTREAM.json)。第三方在线音源服务和 FFmpeg 不随本项目分发；软件许可证不代表取得音乐内容或第三方服务的授权。
