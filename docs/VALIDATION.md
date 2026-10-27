# 1.0.0 验证记录

核对日期：2026-10-27。环境：Windows、Python 3.12、MaiBot 1.3.15、SDK 2.16.0、httpx 0.28.1、cryptography 50.0.2、pytest 9.1.1、pytest-asyncio 1.4.1，系统提供 FFmpeg / ffprobe。

| 检查 | 结果与边界 |
| --- | --- |
| `python -m pytest -q -ra` | **98 passed, 1 skipped**；跳过的是 Windows 当前账户无法创建符号链接的用例 |
| 音频处理回归 | 使用 FFmpeg 生成合成 AAC，实际转 MP3；核对时长、缓存复用与截短拒绝，不下载音乐内容 |
| 增强逻辑回归 | 覆盖指定歌手、版本过滤、媒体地址、恶意重定向、平台信息不符、源失败回退与 Cookie 隔离 |
| 发布默认配置 | 模板与 SDK 生成默认值完全一致，测试同机缓存、容器映射、热重载、缺少 FFmpeg 的提示和发送失败后的缓存释放 |
| `python scripts/check_host.py` | 官方 manifest 校验与插件加载器通过；收集到 4 个组件，隔离执行加载、重载、卸载，Host RPC 为 0 次 |
| `python scripts/check_release.py` | 源码文件、独立身份、版本、GPL/MIT 许可、空凭证模板校验通过 |
| 原上游来源 | 本地基础源码的 14 个 Git blob 与记录的上游提交树一致；新仓库在此基础上整理和增强 |

每次构建会再次检查归档文件名、单层安装目录、必需源码与许可文件、空凭证模板和 SHA256。当前产物的源提交、文件数量、压缩包哈希与自动检查结果写入 `dist/release-manifest.json`，另有 `dist/SHA256SUMS`。不将压缩包自身哈希写入包内文件，避免循环引用。

以下验收尚未完成，不作为已经通过的结论：

- 当前独立插件 ID 的真实 QQ 收发验收；本次隔离 Host 检查没有发送 QQ 消息。
- Linux / macOS 的主机与适配器验收，以及其他 MaiBot / SDK 版本。
- GitHub Actions 远程执行、GitHub Release 发布、插件中心提交或收录。

此前机器人本地增强版的音源与 QQ 运行记录属于迁移前证据。本项目保留其代码基础，但独立包的完整性验证与真实账号收发验证分别记录。当前机器人目录未替换为新插件。
