# CCB HAPI 集成

CCB 可以把项目内的 Claude 和 Codex teammate 作为独立会话接入现有 HAPI
Hub。CCB 继续管理 tmux pane、workspace、provider home、恢复和停止；HAPI
wrapper 负责远程消息、权限、文件、skills、terminal 和 Hub 重连。

## 前置条件

1. 安装包含 CCB metadata v1 支持的 HAPI CLI 和 Hub。
2. 启动全局 HAPI Hub，并为 CLI 配置 `HAPI_API_URL` 和认证。可用
   `hapi auth login` 完成交互式登录。
3. 确认当前环境满足集成契约：

```bash
hapi doctor --json
```

输出必须是一个 JSON 对象，且 `authConfigured`、`hubReachable`、
`capabilities.ccbMetadataV1` 和
`capabilities.disableRunnerAutoStart` 均为 `true`。CCB 启动前会重复执行该
检查，并在不满足时整体停止启动，不会静默退化为本地模式。

## 开启项目集成

在项目的 `.ccb/ccb.config` 中加入：

```toml
[hapi]
enabled = true
command = "hapi"
```

`command` 也可以是 HAPI 可执行文件的绝对路径，但不能包含 shell 管道或
额外参数。第一阶段只支持 `claude` 和 `codex`；项目中存在其他 provider，
或 agent 显式配置了 `provider_command_template` 时，校验会报错。

然后正常启动 CCB：

```bash
ccb config validate
ccb
```

不需要由 HAPI runner 启动 teammate。CCB 会在各自 pane 中执行兼容的 HAPI
wrapper，并禁止 wrapper 自动启动 runner。Hub 的会话列表按 CCB project 和
可选 workgroup 分组，每一行对应一个 teammate；reload/restart 会保留旧代
历史并优先显示当前 active generation。

## 停止与排查

正常使用 CCB 的 stop/kill 流程。启用 HAPI 时，CCB 会先给 wrapper 最多三秒
的优雅退出窗口，使 HAPI 归档 Hub session，然后继续现有 pane 和残留进程
清理。Hub 不可达时，本地清理仍会完成。

常见失败先运行：

```bash
ccb doctor
hapi doctor --json
```

- `authentication is not configured`：运行 `hapi auth login` 或配置全局
  `CLI_API_TOKEN`。
- `Hub is not reachable`：检查全局 Hub 和 `HAPI_API_URL`；CCB 不负责启动
  或停止 Hub。
- provider/template 校验失败：第一阶段只保留 Claude/Codex，并移除该
  agent 的显式 `provider_command_template`，或关闭 `[hapi].enabled`。

CCB 配置文件和运行时缓存都不会保存 HAPI token。项目关闭集成时，将
`enabled` 设为 `false`；后续启动恢复原生 provider 命令。
