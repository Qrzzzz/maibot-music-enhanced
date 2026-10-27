# 麦麦点歌增强

面向 MaiBot 的 QQ 音乐 / 网易云点歌插件。自然语言点歌后直接发送语音，支持聚合音源、歌曲身份与完整时长核验、M4A/AAC 转 MP3 和本地缓存。

**基于磐冰的 maibot-music 增强，音源接入参考 Zhalslar 的 AstrBot 插件。** 独立维护者及新增代码作者：**Qrzzzz**。来源、改动和许可全文见 [NOTICE.md](NOTICE.md)。

| 项目 | 当前值 |
| --- | --- |
| 插件 ID | `github.qrzzzz.music-enhanced` |
| 独立版本 | `1.0.0` |
| 许可证 | GPL-3.0-only，保留上游 MIT 版权及许可声明 |
| 声明兼容范围 | MaiBot `1.3.15` / Plugin SDK `2.16.0` |
| 开发验证环境 | Windows、Python `3.12`；其他系统尚未做主机实测 |
| 源码仓库 | [Qrzzzz/maibot-music-enhanced](https://github.com/Qrzzzz/maibot-music-enhanced) |

下载版本见 [GitHub Releases](https://github.com/Qrzzzz/maibot-music-enhanced/releases)，构建结果见 [GitHub Actions](https://github.com/Qrzzzz/maibot-music-enhanced/actions)。插件中心收录以官方审核结果为准。

## 功能与默认行为

- 自然语言请求由 `search_and_play_music` 工具执行；QQ 音乐优先，无可播放候选时尝试网易云。
- 聚合源使用 `music.txqq.pro`；搜索失败或无结果时回退平台原接口。
- 聚合源启用时过滤未请求的 cover/remix/live 等版本，并匹配指定歌手。
- **本地语音 + 聚合源启用**时，对照平台的歌曲 ID、标题、歌手和时长核验下载内容；明显试听或截短片段不会作为完整歌曲发送。时长允许最多 `max(3 秒, 3%)` 的误差，不代表逐采样一致性校验。
- 使用 FFmpeg 将非 MP3 音频转为 MP3；不会仅修改扩展名。QQ 语音上传可能再次压缩音质。
- 默认缓存上限 1 GB、24 小时未访问过期、单文件最多 50 MB、歌曲最多 30 分钟；保留发送期间的缓存保护和定时清理。
- 默认关闭链接、分享卡片自动解析，默认 `/点歌` 直接选取第一首；也可切换原有的选歌列表或卡片模式。

可播放范围由音乐平台、登录权益与第三方音源决定。搜索到歌曲不代表能取得完整音频，无法保证所有歌曲可播。`remote` 语音、卡片模式或关闭 `source_bridge.enabled` 时不经过完整时长核验。

## 安装

1. 确认 MaiBot / SDK 版本在上述声明范围内，且使用的适配器支持 `voiceurl` 自定义消息。
2. 安装 [FFmpeg](https://ffmpeg.org/download.html)，确保启动 MaiBot 的进程能运行 `ffmpeg -version` 和 `ffprobe -version`。Windows 安装后需重新启动 MaiBot 进程以读取新 PATH。
3. 在 MaiBot 所用的 Python 环境安装依赖：`python -m pip install -r requirements.txt`。插件 manifest 也声明了 Python 包依赖。
4. 将插件源码目录放到 `MaiBot/plugins/maibot-music-enhanced/`，保证 `_manifest.json` 与 `plugin.py` 在该目录根部。发布 ZIP 自带这一层目录，解压到 `plugins/` 即可。
5. 首次安装可将 `config.example.toml` 复制为 `config.toml` 并按部署方式修改；不复制时由 Host 根据配置模型生成默认配置。
6. 通过 WebUI 加载插件，或重启 MaiBot，确认日志出现“麦麦点歌增强 1.0.0 已加载”。

### 从原插件迁移

先在 WebUI 停用 `github.pan-ice.music`，再加载本插件。两个版本保留相同的工具名和命令名，同时启用会发生重复注册或重复响应。

按 `config.example.toml` 重新填写需要保留的配置，不要直接覆盖模板。配置中的版本号改为 `1.0.0`，补上 `[source_bridge]`；缓存可留空使用新插件的独立目录。原插件数据目录和旧试听缓存无需复制。

### 同机与容器路径

默认两个缓存路径都留空，运行时使用 `ctx.paths.data_dir / "audio_cache"`，通常对应 `MaiBot/data/plugins/github.qrzzzz.music-enhanced/audio_cache`。同机的 SnowLuma / NapCat 应以可读取该目录的账户运行。

容器部署时，两个路径必须指向同一份文件在各自进程中的路径。例如：

```toml
[music]
cache_storage_dir = "/srv/maibot/music-cache"  # MaiBot 可写
cache_napcat_dir = "/app/music-cache"        # 适配器可读
```

将同一宿主机目录分别挂载到这两个位置，适配器侧可设为只读。Windows 的 TOML 绝对路径建议使用正斜杠，如 `D:/MaiBot/music-cache`。远程适配器若无法共享文件，可切换 `voice_source = "remote"`，但该模式不提供本地完整时长核验与转码。

## 使用

自然语言示例：`@机器人 我想听 I Really Want to Stay at Your House，Rosa Walton 的版本`。

| 命令 | 作用 |
| --- | --- |
| `/点歌 歌名` | 使用默认平台搜索并播放 |
| `/点歌 qq 歌名` | 指定 QQ 音乐 |
| `/点歌 163 歌名` | 指定网易云 |
| `/选歌 1` | 关闭 `auto_select_first` 后选择列表中的歌曲 |

`music.command_prefix` 可改为 `#` 等符号。LLM 工具始终直接尝试候选并在失败时换平台；命令按指定平台执行，不自动跨平台。插件会返回实际执行结果，但最终自然语言表述仍由机器人模型决定。

## 配置

完整可用模板见 [config.example.toml](config.example.toml)。模板与代码默认值保持一致。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `music.default_platform` | `qq` | LLM 工具优先搜索的平台 |
| `music.play_mode` | `voice` | `voice` 语音或 `card` 音乐卡片 |
| `music.voice_source` | `local` | `local` 本地缓存或 `remote` 远程 URL |
| `music.auto_select_first` | `true` | 命令直接选首个候选 |
| `music.auto_parse_url` / `auto_parse_card` | `false` | 是否自动处理分享消息 |
| `music.cache_storage_dir` / `cache_napcat_dir` | 空 | 默认插件独立缓存；容器按实际映射配置 |
| `source_bridge.enabled` | `true` | 聚合源与本地完整音频处理；关闭后使用上游原生接口流程 |
| `netease.MUSIC_U` / `csrf_token` | 空 | 可选网易云登录凭证 |
| `qq.uin` / `qqmusic_key` | 空 | 原生 QQ 搜索回退所需登录凭证 |
| `napcat.http_url` / `http_token` | 本机 `9999` / 空 | NapCat 卡片直连与原消息解析使用；默认语音路径不要求该 API |

聚合源搜索不要求在本插件填写音乐 Cookie。关闭聚合源或聚合源故障后回退原生 QQ 搜索时，需要有效的 QQ 音乐登录态。凭证仅在平台对应配置中填写，不要加入仓库。

## 网络、数据与适配器

- 聚合搜索会将点歌关键词发送到 `https://music.txqq.pro/`，由第三方接收请求；QQ / 网易云 Cookie 与 NapCat token 不会交给该客户端。
- 平台请求会访问 QQ 音乐、网易云及对应媒体 CDN。聚合下载只接受代码允许的 QQ / 网易云媒体域名，并逐次检查重定向地址。
- `ffprobe` / `ffmpeg` 仅处理已下载的本地文件，不用它们拉取远程音频。系统需单独安装 FFmpeg，本仓库不分发其二进制。
- 错误日志位于本插件数据目录的 `log/error.log`，可能含歌曲查询与错误细节，分享日志前请自行脱敏；日志不自动轮转。
- 语音通过 MaiBot 的 `send.custom("voiceurl", ...)` 发送。默认本地语音使用方式沿用此前 SnowLuma 接口约定；本独立包的验证边界见 [验证记录](docs/VALIDATION.md)。
- 可选 QQ 卡片模式保留上游 NapCat HTTP 直连机制。直连卡片不写入 MaiBot 聊天历史；默认语音模式不走该直连路径。

## 开发与打包

使用 Python 3.12，在独立虚拟环境运行：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q -ra
python scripts/check_release.py
```

本地 Host 已安装时，可额外使用它的 Python 运行 `python scripts/check_host.py`，检查官方 manifest 校验与插件加载器。该脚本创建临时数据目录执行加载、配置重载和卸载，不发送 QQ 消息。

提交代码并保持工作区干净后打包：

```powershell
python scripts/build_release.py
python scripts/check_release.py --built
```

构建输出 ZIP、`SHA256SUMS` 和记录源提交的 `release-manifest.json`。打包只使用 Git 跟踪的文件，且会拒绝配置、凭证、音频、运行数据或日志。具体 GitHub Release 与插件中心提交步骤见 [发布说明](docs/RELEASING.md)。

## 发布新版本

用一条命令同步版本与更新日志，再提交、推送代码：

```powershell
python scripts/prepare_release.py 1.0.1 --note "本次更新的具体说明"
```

随后打开 [Release plugin 工作流](https://github.com/Qrzzzz/maibot-music-enhanced/actions/workflows/release.yml)，选择 `main`，填写预期版本；默认 `dry_run=true` 只做测试与打包。确认演练通过后，对同一提交运行 `dry_run=false` 即可正式发布。也支持推送与版本一致的 `vX.Y.Z` 标签触发正式发布。

工作流自动运行回归、检查版本一致性、生成 ZIP 和 SHA256、验证源码提交、暂存草稿、回读下载附件，最后公开 Release。已有版本不覆盖；完整步骤、重跑规则和权限说明见 [发布说明](docs/RELEASING.md)。

## 许可证与致谢

本项目整体采用 [GNU GPLv3](LICENSE)。感谢磐冰的 [maibot-music](https://github.com/pan-ice/maibot-music) 与 Zhalslar 的 [AstrBot 音乐插件](https://github.com/Zhalslar/astrbot_plugin_music)。保留原有署名与许可，详见 [NOTICE.md](NOTICE.md)、[上游记录](UPSTREAM.json) 和 [更新日志](CHANGELOG.md)。
