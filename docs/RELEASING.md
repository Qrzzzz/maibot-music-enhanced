# 发布与插件中心提交

项目名：麦麦点歌增强。插件 ID：`github.qrzzzz.music-enhanced`。独立版本线从 `1.0.0` 开始，不沿用上游 1.4.6 的版本序列。

## 本地发布准备

1. 阅读 `NOTICE.md`，确认保留原 MIT 版权与许可、GPLv3 原文，以及两处上游项目和参考提交。
2. 修改代码时同步 `_manifest.json`、`plugin.py`、`config.example.toml` 与 `CHANGELOG.md` 的版本。Host / SDK 上下界只填写已验证范围。
3. 使用 Python 3.12 与 `requirements-dev.txt` 运行 `python -m pytest -q -ra` 和 `python scripts/check_release.py`。记录跳过项及未执行的实机验证，不将历史结果当作新包实测。
4. 在 MaiBot 环境运行 `python scripts/check_host.py`，检查官方 manifest 解析、加载器和隔离生命周期。实际 QQ 验证应单独进行，并先停用旧插件。
5. 提交全部发布源文件，确保 `git status --short` 为空。运行 `python scripts/build_release.py`。
6. 运行 `python scripts/check_release.py --archive dist/maibot-music-enhanced-1.0.0.zip`，验证压缩包、许可文件、配置模板与 SHA256。

`dist/` 不进入源码历史。ZIP 顶层为 `maibot-music-enhanced/`，解压到 `plugins/` 即可。压缩包附带完整源码、测试和构建脚本，不包含 `config.toml`、Cookie、token、音频缓存或运行日志。

## GitHub 发布

计划仓库：`https://github.com/Qrzzzz/maibot-music-enhanced`。确认公开发布授权后，创建该公开仓库并推送本地 `main`。如果最终使用其他仓库地址，应先同步 manifest 和文档后重新验证、打包。

在已经验证的源提交创建 `v1.0.0` Tag，发布对应的 GitHub Release。Release 内容可取自 `CHANGELOG.md` 的 1.0.0 条目，并附上 `dist/` 中的 ZIP、`SHA256SUMS`、`release-manifest.json`。不要让 Tag 指向另一个未经验证的提交。

仅本地 ZIP、仅 Tag 或 GitHub 草稿 Release 均不等同已满足插件中心的 Release 发布要求。

## 官方插件中心

依据 [官方贡献指南](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md)（核对日期：2026-10-27）：

1. 插件仓库公开，根目录包含 `_manifest.json` v2、`plugin.py`、`LICENSE`、`README.md`。
2. 至少发布一个 GitHub Release；允许预发布版和 GitHub 自动源码包，不接受仅 Tag 或草稿。
3. 到 [添加插件 Issue 模板](https://github.com/Mai-with-u/plugin-repo/issues/new/choose)选择“Add Plugin / 添加插件”。
4. 填写插件 ID `github.qrzzzz.music-enhanced` 与公开仓库地址。简介建议：

   > 麦麦点歌增强：基于磐冰的 maibot-music 增强，音源接入参考 Zhalslar 的 AstrBot 插件。支持 QQ/网易云点歌、聚合音源、本地语音完整时长核验与转码，由 Qrzzzz 独立维护。

5. 等待 CI 校验和维护者审核；提交 Issue 不代表已收录。若失败，按具体结果修复并申请重新检查。

后续每次修复递增版本并发布新 Release，不改写已收录版本的 Tag 或源提交。
