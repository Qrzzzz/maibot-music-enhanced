# 1.1.0 兼容性与验收范围

## 推荐路线

`点歌插件 → MaiBot SDK → Host → 统一 QQ 适配器 → NapCat 或 SnowLuma`。

推荐使用 [MaiBot-SnowLuma-Adapter](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter)。虽然名称包含 SnowLuma，它是支持两类客户端的统一连接器；客户端差异由连接器处理。本插件不管理客户端 HTTP 令牌，也不直接访问其发送或查询接口。

## 本版已覆盖的合约

| 组合 | 覆盖范围 |
| --- | --- |
| 插件 + 实际 SDK 能力代理 | 群聊、私聊流 ID 经 `cap.call / send.custom` 传递，语音使用 `voiceurl`，不查群号或用户号 |
| 官方 NapCat 旧适配器编码方法 | 语音转换为 `record`，本地路径转换为 `file://` 引用，数字 ID 转换为标准平台卡片 |
| 官方统一 QQ 适配器编码方法 | 相同的语音和卡片输入合约；该连接器可以连接 NapCat / SnowLuma |
| 卡片降级 | QQ MID 不冒充数字歌曲 ID；改发公开歌曲链接；标准卡片返回失败时同样回退链接 |
| 配置迁移 | 旧缓存读取目录保留，新字段优先，废弃 NapCat HTTP 配置与凭证不进入模型 |
| 下载边界 | 聚合及原生下载共用域名规则，重定向逐跳检查，异常后释放缓存引用并清理临时文件 |

旧 [MaiBot-Napcat-Adapter](https://github.com/Mai-with-u/MaiBot-Napcat-Adapter)当前 manifest 标明不再更新。因此测试保留其已有发送格式，但新的部署优先选择统一连接器。

## 固定的上游代码版本

离线测试夹具只提取五个纯编码方法，不启动真实客户端：

- NapCat 适配器：`d87203e2eff1835895ee34196b17a571dc6bbe24`。
- 统一 QQ 适配器：`ab751ae5c11f501e0158e33cacc321b33e34ef0c`。

提取时核对了 Git blob 哈希及上游 manifest 的 GPLv3-or-later 声明。`tests/fixtures/adapters/provenance.json` 记录源码哈希、夹具哈希及方法列表；测试再次检查夹具完整性。它们证明特定版本的编码格式兼容，不代表运行过完整适配器或所有后续版本。

```powershell
python -m pytest tests/test_host_routing.py -q
```

## 真实部署仍需验收

本次 SDK、编码合约及隔离 Host 检查不发送 QQ 消息。下面项目必须在各自的实际客户端环境逐项确认，不能用 Mock 或编码测试代替：

1. NapCat、SnowLuma 分别连接统一 QQ 适配器，群聊和私聊均能点歌。
2. QQ 中实际收到且能播放语音，歌曲身份及完整时长正确。
3. 同机、容器或共享目录中，客户端确实能读取缓存文件。
4. Host 发送链路记录、聊天历史、真实消息回执与失败原因符合预期。
5. 卡片不可用时链接可用，且工具不将链接发送表述为语音播放成功。
6. 失败或投递未确认时检查客户端与适配器日志，避免手动重复操作造成重复消息。

在真实验收完成前，本版结论为“支持双端的 SDK/消息格式合约”，而不是“双端真实 QQ 全流程已通过”。如果 NapCat 出现实际兼容阻碍，应记录具体客户端、适配器版本和失败链路，再决定是否暂时收窄支持范围。
