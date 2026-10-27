# 发布与插件中心提交

项目：麦麦点歌增强。插件 ID：`github.qrzzzz.music-enhanced`。公开仓库：[Qrzzzz/maibot-music-enhanced](https://github.com/Qrzzzz/maibot-music-enhanced)。

## 推荐：同步版本后在 Actions 发布

1. 完成功能修改与验证，保留 `NOTICE.md` 中的来源、原 MIT 版权及许可和 GPLv3 原文。Host / SDK 兼容范围只填写实际验证范围。
2. 在项目根目录执行以下命令，`--note` 可以重复填写。它同步 manifest、代码版本常量、配置模板、README 版本及更新日志，不提交或发布代码。

   ```powershell
   python scripts/prepare_release.py 1.1.1 --note "修复一个具体问题" --note "新增一个具体功能"
   git diff --check
   git add _manifest.json plugin.py config.example.toml README.md CHANGELOG.md
   git commit -m "release: prepare 1.1.1"
   git push origin main
   ```

3. 打开 [Actions → Release plugin](https://github.com/Qrzzzz/maibot-music-enhanced/actions/workflows/release.yml)，点击 **Run workflow**，选择已推送的分支，预期版本填 `1.1.1`，保持 **dry_run=true**。也可使用 CLI：

   ```powershell
   gh workflow run release.yml --ref main -f dry_run=true -f version=1.1.1
   ```

4. 查看工作流摘要、测试结果和 `plugin-release-<源 SHA>-<尝试次数>` Artifact。独立的 verify job 按本次构建返回的 Artifact ID 下载并核对源码。演练只验证、打包并保存 Actions 产物，不创建标签、Release 或插件中心申请。已有版本也可演练，但演练包不等于该版本曾经公开的安装包。
5. 确认演练通过且目标分支未变化后，对同一分支与版本运行 **dry_run=false**。正式运行会重新验证所选提交；不需要事先创建标签。

   ```powershell
   gh workflow run release.yml --ref main -f dry_run=false -f version=1.1.1
   ```

6. 成功后到 [Releases](https://github.com/Qrzzzz/maibot-music-enhanced/releases)核对版本。工作流摘要和 `plugin-publication-<源 SHA>-<尝试次数>` Artifact 保存公开 URL、源提交和附件核验结果。

整个过程使用 GitHub 自动提供的 `GITHUB_TOKEN`，不需要新增 PAT 或配置个人密钥。构建 job 只有源码读取权限；仅正式发布 job 获得 `contents: write`，用于创建标签与 Release。Actions 中的“Workflow permissions”若被组织策略限制，按实际报错处理，不使用个人 token 绕过策略。

## 另一种入口：推送版本标签

对于已经提交、检查并推送的版本，也可直接使用：

```powershell
git tag -a v1.1.1 -m "麦麦点歌增强 1.1.1"
git push origin v1.1.1
```

`v*` 标签触发正式发布。标签必须精确等于 `v` 加 manifest 的三段式版本，例如 `v1.1.1`，版本不符即失败。普通分支 CI 不处理标签，避免同一标签重复执行普通 CI；Release 工作流自身完整执行回归。

手动工作流用 `GITHUB_TOKEN` 创建标签不会再触发一份标签工作流，这是 GitHub 的[事件触发规则](https://docs.github.com/en/actions/concepts/security/github_token)。本工作流不依赖二次触发，创建标签后在当前运行中完成发布。

## 自动执行的检查与发布顺序

1. 固定 checkout 到触发运行的源 SHA；检查工作区干净、manifest / 代码常量 / 配置版本一致、更新日志包含该版本、标签和预期版本一致。
2. 准备 Python 3.12、依赖与 FFmpeg / ffprobe，运行全部测试。
3. 从该提交的 Git 文件生成确定顺序和时间戳的 ZIP，并检查目录、完整源码、来源许可和空凭证模板。
4. 检查 ZIP 中每个文件与源提交一致，生成 SHA256 和记录源提交的 `release-manifest.json`。发布说明取自该版本 CHANGELOG，附来源署名、源 SHA 和工作流链接。
5. 将构建产物传递到发布 job；发布 job 再次固定到同一 SHA 并核验产物。
6. 确认远程标签未指向其他提交；缺少标签时创建标签，上传附件到草稿 Release。
7. 核对 GitHub 附件 API 的 SHA256 与大小，再下载草稿附件检查压缩包及所有源码，全部通过后将草稿公开。
8. 回读 Release 公开状态和附件摘要，保存发布记录。

正式附件为 `maibot-music-enhanced-<版本>.zip`、`SHA256SUMS`、`release-manifest.json`。ZIP 顶层为 `maibot-music-enhanced/`，解压到 MaiBot 的 `plugins/` 即可。测试、构建脚本和许可一并分发，不包含实际 `config.toml`、Cookie、token、音频、数据库或运行日志。

## 失败与重跑

- 所有 Release 运行串行排队，不取消正在发布的旧运行。
- 测试或回读失败时不公开草稿。修复源代码时必须准备新的版本；若是临时网络失败，可重跑同一提交。
- 已存在的标签必须解析到同一源提交，不能移动或重写。
- 已存在的草稿只有在附件名称、数量、大小、SHA256 全部一致时才可继续。附件缺失或不符会明确失败，不删除、覆盖或自动替换；需要维护者检查后处理。
- 同一源提交的已公开 Release 如附件完全一致，重跑只验证并报告 `already_published`。相同版本指向新提交、附件不符或预发布状态不同，均不会被改写。
- 现有 `v1.0.0` 标签与 Release 保持原样。新增工作流不会自动重新发布已有版本。

## 本地检查

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q -ra
python scripts/check_release.py
```

在已经安装 MaiBot 的 Python 环境，可额外运行 `python scripts/check_host.py`。它检查官方 manifest 校验与隔离生命周期，不发送 QQ 消息。QQ 真机验收仍需独立进行。

提交源码、保持工作区干净后，可做不联网的发布演练：

```powershell
python scripts/release.py plan --dry-run true
python scripts/build_release.py
python scripts/release.py verify
```

`dist/` 中的构建产物与运行记录不进入源码历史。

## 官方插件中心

当前登记申请：[Mai-with-u/plugin-repo #1060](https://github.com/Mai-with-u/plugin-repo/issues/1060)。申请是否获批以该 Issue 及官方索引为准，工作流只发布 GitHub Release，不冒充维护者批准，也不自动发送 Issue 或评论。

依据[官方贡献指南](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md)（核对日期：2026-10-27）：首次收录需要公开仓库、根目录 manifest v2 / plugin.py / LICENSE / README，以及至少一个已发布 GitHub Release。正式 Release、预发布版及 GitHub 自动源码包可以满足 Release 要求；仅 Tag 或草稿不满足。

首次登记通过官方“Add Plugin / 添加插件”Issue 模板提交。登记后，后续新版本发布 Release，保持插件 ID 不变，等待官方每日同步及版本审核；已收录版本不改写标签或源提交。工作流成功不代表插件中心已收录新版本。
