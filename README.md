# 麦麦点歌增强

面向 MaiBot 的 QQ 音乐 / 网易云点歌插件。搜索、完整时长校验、转码和缓存由插件完成，消息发送统一经过 MaiBot Host 和已配置的 QQ 适配器。

**基于磐冰的 maibot-music 增强，音源接入参考 Zhalslar 的 AstrBot 插件。** 维护者及新增代码作者：**Qrzzzz**。来源和许可见 [NOTICE.md](NOTICE.md)。

| 项目 | 当前值 |
| --- | --- |
| 插件 ID | `github.qrzzzz.music-enhanced` |
| 独立版本 | `1.1.1` |
| 许可证 | GPL-3.0-only，保留原 MIT 声明及测试夹具的原 GPLv3-or-later 声明 |
| 插件类型 | `tool`（命令及 LLM 点歌工具） |
| 声明兼容范围 | MaiBot `1.3.15–1.3.99` / Plugin SDK `2.16.0` |
| 推荐连接器 | 官方 [统一 QQ 适配器](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter)，可连接 SnowLuma 或 NapCat |
| 开发环境 | Windows、Python 3.12；CI 使用 Linux、Python 3.12 |

[源码仓库](https://github.com/Qrzzzz/maibot-music-enhanced) · [Releases](https://github.com/Qrzzzz/maibot-music-enhanced/releases) · [Actions](https://github.com/Qrzzzz/maibot-music-enhanced/actions) · [兼容性与验收边界](docs/COMPATIBILITY.md)

1.1.1 只调整插件分类和兼容声明，不改变 1.1.0 的双端发送路线。`1.3.99` 是允许同一 `1.3` 系列补丁更新的上限声明，不是已经实测的 Host 版本；实际加载验证仍为 MaiBot `1.3.15` / SDK `2.16.0`。SDK 超出声明范围时仍会被校验器阻止加载。

## 1.1.0 的发送路线

点歌请求 → 插件搜索和音频处理 → MaiBot SDK `send.custom` / `send.text` → Host → QQ 适配器 → SnowLuma 或 NapCat。

本插件不再直接调用客户端发送接口、抓取原消息或反查全量聊天流，也不再配置 NapCat HTTP 地址和 token。默认语音使用 `voiceurl`，由适配器转换成客户端可用的语音消息。源码中的双端编码合约测试不能替代真实 QQ 收发验收，验证范围见 [COMPATIBILITY.md](docs/COMPATIBILITY.md)。

## 功能与边界

- 默认 QQ 音乐优先；LLM 工具无可播放候选时尝试网易云。
- `music.txqq.pro` 聚合搜索不可用时回退平台原接口。
- 聚合源启用时过滤未请求的 cover/remix/live 等版本，并匹配指定歌手。
- **本地语音 + 聚合源启用**时，对照平台歌曲 ID、标题、歌手和时长核验下载内容。时长容差为 `max(3 秒, 3%)`，明显试听或截短片段会被拒绝，不代表逐采样一致性校验。
- FFmpeg 将非 MP3 音频实际转为 MP3；QQ 语音上传仍可能压缩音质。
- 缓存默认上限 1 GB、24 小时未访问过期、单文件最多 50 MB，完整音频模式最多 30 分钟。
- 默认关闭分享链接、卡片自动解析；自然语言点歌直接尝试候选，`/点歌` 也默认直接选取第一首。
- **卡片模式**仅尝试适配器支持的标准平台歌曲 ID。QQ 搜索通常返回 MID，不能当作标准卡片所需的数字 ID，因此改发官方歌曲链接；标准卡片发送失败也回退链接。不再构造或直发自定义 CQ 音乐卡片。
- 分享解析仅使用 Host 已提供的文本和链接；缺少歌曲链接时提示补发，不另行调用客户端 `get_msg`，也不按模糊卡片标题自动换歌。

可播放范围由平台权益、版权和音源可用性决定。`remote` 语音、卡片/链接模式或关闭 `source_bridge.enabled` 时，不经过本地完整时长核验。卡片和链接发送结果不会被表述为“已播放语音”。

## 安装

1. 确认 MaiBot / SDK 在上述范围内，QQ 客户端已通过适配器连接 Host，并支持 `voiceurl` 消息。
2. 默认本地语音模式需要 [FFmpeg](https://ffmpeg.org/download.html)：启动 MaiBot 的进程必须能执行 `ffmpeg -version`、`ffprobe -version`。仅卡片/链接模式不需要它们。
3. 在 MaiBot 所用 Python 环境安装 `requirements.txt` 中的依赖；manifest 同样声明了 Python 包依赖。
4. 将源码目录放入 `MaiBot/plugins/maibot-music-enhanced/`。ZIP 自带这一层目录，解压到 `plugins/` 即可。
5. 首次安装可复制 `config.example.toml` 为 `config.toml`；不复制时由 Host 生成默认配置。
6. 在 WebUI 加载插件，确认日志显示当前版本已加载。

## 从旧版本迁移

- 从磐冰原插件迁移时，先停用 `github.pan-ice.music`，避免同名工具和命令重复注册。
- 从本插件 1.0.0 升级时，配置归一化会将 `music.cache_napcat_dir` 迁移为 `music.cache_reader_dir`；两者同时存在时优先使用新字段。保留原有显式缓存映射。
- 废弃的 `[napcat]` 配置不再进入配置模型或创建 HTTP 客户端。Host 保存归一化配置时会去掉这些项；旧文件、历史备份和凭证由用户自行管理。
- 配置版本会归一化为当前插件版本。升级不改变音乐 Cookie 的用途和发送目的地，不要求另外填写客户端 HTTP token。
- 保留旧数据目录即可；不要用空白模板覆盖已配置的平台登录态。

## 缓存与部署

两个路径默认留空，使用 `ctx.paths.data_dir / "audio_cache"`。同机 NapCat / SnowLuma 应能读取同一文件。

```toml
[music]
cache_storage_dir = "/srv/maibot/music-cache"  # MaiBot 可写
cache_reader_dir = "/app/music-cache"        # QQ 客户端可读
```

容器部署需将同一宿主机目录挂载到对应路径，客户端侧可只读。Windows 路径建议写成 `D:/MaiBot/music-cache`。远程客户端无法读取本地缓存时，需共享文件系统；也可选择 `voice_source = "remote"`，但该模式没有本地完整时长核验与转码。

## 使用与配置

自然语言：`@机器人 我想听 I Really Want to Stay at Your House，Rosa Walton 的版本`。

| 命令 | 作用 |
| --- | --- |
| `/点歌 歌名` | 使用默认平台搜索播放 |
| `/点歌 qq 歌名` | 指定 QQ 音乐 |
| `/点歌 163 歌名` | 指定网易云 |
| `/选歌 1` | 关闭自动首选后选择列表歌曲 |

LLM 工具内置换平台尝试；命令按指定平台执行。完整配置见 [config.example.toml](config.example.toml)。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `music.default_platform` | `qq` | LLM 工具优先搜索的平台 |
| `music.play_mode` | `voice` | 语音，或 `card` 标准卡片/链接 |
| `music.voice_source` | `local` | 本地缓存，或 `remote` 远程 URL |
| `music.auto_select_first` | `true` | 命令直接选取首个候选 |
| `music.auto_parse_url` / `auto_parse_card` | `false` | 分享消息自动解析开关 |
| `music.cache_storage_dir` / `cache_reader_dir` | 空 | 写入路径及客户端读取路径 |
| `source_bridge.enabled` | `true` | 聚合源及本地完整音频处理 |
| `netease.MUSIC_U` / `csrf_token` | 空 | 可选网易云登录凭证 |
| `qq.uin` / `qqmusic_key` | 空 | 原生 QQ 搜索回退所需凭证 |

## 网络与数据

- 聚合搜索向 `https://music.txqq.pro/` 发送歌曲关键词；不发送 QQ / 网易云 Cookie 或任何客户端 token。
- 平台请求访问 QQ 音乐、网易云及其媒体 CDN。两条音频下载路径共用媒体域名规则，每次重定向均重新校验，限制次数和大小。
- FFmpeg / ffprobe 只读取已下载的本地文件，不用于拉取远程媒体。本包不分发这些二进制。
- 错误日志在本插件数据目录 `log/error.log`，可能含点歌查询与错误信息，分享前请脱敏；日志不自动轮转。
- 所有实际发送经 Host SDK；是否形成可用的 Host 历史记录及真实 QQ 回执，需按部署环境单独验收。

## 开发与发布

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q -ra
python scripts/check_release.py
```

已安装 MaiBot 的环境可运行 `python scripts/check_host.py`，验证官方加载器与隔离生命周期；它不发送 QQ 消息。

```powershell
python scripts/prepare_release.py 1.1.2 --note "本次更新的具体说明"
```

提交推送后，打开 [Release plugin](https://github.com/Qrzzzz/maibot-music-enhanced/actions/workflows/release.yml)，先运行 `dry_run=true`，通过后对同一提交运行 `false`。也支持推送匹配 manifest 的 `vX.Y.Z` 标签。完整发布、重跑和插件中心流程见 [RELEASING.md](docs/RELEASING.md)。

## 许可证与致谢

整体采用 [GNU GPLv3](LICENSE)，保留磐冰原代码的 [MIT 声明](licenses/maibot-music-MIT.txt)。感谢磐冰、Zhalslar 和 MaiBot Team。具体来源及测试代码许可见 [NOTICE.md](NOTICE.md)、[UPSTREAM.json](UPSTREAM.json) 和 [更新日志](CHANGELOG.md)。
