# Native Windows Herdr Managed Startup（`ccb herdr open`）

> 对应 Epic `windows-native-herdr-ccb` ITEM-7。C2 非对称联邦下的一键启动路径：
> WezTerm（唯一入口）→ Herdr（物理 pane owner）→ CCB（provider/编排/recovery authority）。

## 目标体验

预先配置好 WezTerm、Herdr、CCB 三份配置后，日常只运行 WezTerm，即进入
Herdr 双 pane（例如 `claude` + `codex`）多 agent 协作环境。用户看到的是 Herdr
双 pane，但 provider 生命周期、凭证、completion、ask/pend/recovery 仍由 CCB 持有。

关键边界：**不让 Herdr 配置直接长期启动 claude/codex**——那会退化成 attached 模式，
CCB 只能“观察/绑定”已有 pane。正确分层是 CCB 创建并标识 pane（managed 模式）。

## 前置条件

- Herdr 已安装，基准路径：
  ```
  C:\Users\Administrator\AppData\Local\Programs\Herdr\herdr.exe
  ```
  所有 `CCB_HERDR_EXE` 默认值、ccb8 wrapper、spike 脚本、diagnose 脚本均以此路径为
  fallback。若路径不同，通过环境变量 `CCB_HERDR_EXE` 覆盖。
- Herdr server 可启动：`ccb herdr open`（含 `--no-attach --wait-ready` 一键路径）
  会在 server 未运行时自动启动 ccbd 派生 session 的 server（复用
  `HerdrCliRequestAdapter` 的 server-start + 就绪轮询），不再要求用户先手动运行
  `herdr`。若 server 已在运行，直接复用。
- CCB 的 `.ccb/ccb.config` 声明期望 agent 拓扑（如 `main = "Main_Code:claude, code_reviewer:codex"`）。
- 使用的 provider 必须在 herdr 显式启动 allow-list 内（当前 `codex`、`claude`；
  见 `lib/cli/services/runtime_launch_runtime/ensure.py::_HERDR_NATIVE_VERIFIED_PROVIDERS`）。

## 形态 1（推荐）：WezTerm 打开 Herdr，Herdr 触发 CCB

- WezTerm 配置 `~/.wezterm.lua`：`config.default_prog = { '<herdr.exe>' }`，
  使运行 WezTerm 即 launch/attach Herdr persistent session。
  （配套 `launch_menu` 保留普通 PowerShell 入口。）
- 进入 Herdr 后，通过 Herdr 快捷键或 Herdr 插件（B-lite）触发 `ccb herdr open`。
- `ccb herdr open` 完成：
  1. 定位 `herdr.exe`（`--herdr-exe` 或自动检测）；
  2. 校验 Herdr server 运行且协议兼容，只读探测核心能力；
  3. 注入 `CCB_HERDR_EXE` / `CCB_HERDR_SESSION` / `CCB_HERDR_CAPABILITY_REPORT` env；
  4. 复用 CCB 启动流，在 Herdr 中创建 pane 并启动 `.ccb/ccb.config` 声明的 agent；
  5. 前台 attach（默认）或后台返回。

## 形态 2（备选）：`ccb herdr open` 编排整个启动链

若希望 WezTerm 直接以 `ccb herdr open` 为 `default_prog`、由命令编排“确保 Herdr + 创建 pane”，
可将 WezTerm 配置改为：

```lua
config.default_prog = { 'ccb', 'herdr', 'open' }
```

该形态让 bootstrap 同时负责 Herdr 环境就绪与 CCB 启动，职责更重；当前默认不采用，
保留为备选。使用前确认 `ccb` 可执行文件在 PATH 中。

> **形态 2 必须是前台 attach（不带 `--no-attach`）**：作为 `default_prog`，WezTerm
> 会把该命令当作 tab 的交互式前台程序运行，`ccb herdr open` 前台 attach 后驻留在
> 该 tab 控制面，用户直接看到 Herdr/CCB 环境。若误加 `--no-attach`，命令后台拉起
> CCB 后即返回，WezTerm tab 随即关闭，用户看不到任何 UI——那不是“打开 WezTerm 即
> 进入环境”。
>
> `--no-attach` 只配合后续单独打开 Herdr UI 使用：`ccb herdr open --no-attach
> --wait-ready` 后台拉起 daemon 与 agent 并等待 ccbd mounted，再通过
> `wezterm cli spawn -- <herdr.exe> session attach <session>` 打开 Herdr UI。
> 这正是 `ccb8.ps1` one-click 模式采用的组合（见下节“一键启动”）。

## 前台 / 后台切换

`ccb herdr open` 默认**前台 attach**（类似 `ccb start` 的交互驻留）。三种方式切换：

| 模式 | 命令 | 行为 |
|---|---|---|
| 前台（默认） | `ccb herdr open` | 启动后在 namespace 前台 attach，驻留控制面 |
| 后台 | `ccb herdr open --no-attach` | 启动 daemon 与 agent 后返回 CLI，不前台 attach |
| 后台 + 就绪等待 | `ccb herdr open --no-attach --wait-ready` | 同后台，但返回前阻塞等待 ccbd lifecycle 达到 `mounted`；供 `ccb8.ps1` one-click 等需要“等 CCB 就绪后再打开 UI”的调用方使用 |

`--wait-ready` 的 ccbd 就绪等待由 Python `handle_herdr_open()` 统一负责（读取
`CcbdLifecycleStore` 轮询 `phase == 'mounted'`，默认 90s 超时），不再由调用方轮询
`lifecycle.json`。

## 一键启动（`ccb8.cmd`）

裸调 `ccb8.cmd`（无参数）进入 one-click 模式。`ccb8.ps1` 只保留薄引导层，dispatch
语义全部归位到 CCB/Herdr 结构化边界：

1. **预启动清理**（PowerShell）：杀旧 ccbd、重置 state 文件、等 keeper stopped。
2. **`ccb.py herdr open --no-attach --wait-ready`**（Python）：`ensure_herdr_bootstrap_env`
   定位 Herdr 并确保 server 运行——未运行则自动启动 ccbd 派生 session 的 server
   （复用 `HerdrCliRequestAdapter.ensure_server_started`），不再由 PowerShell 预启动；
   随后 `handle_start` 后台拉起 daemon 与 agent；`--wait-ready` 让 Python 阻塞等待
   ccbd `phase == mounted`，替代原先 PowerShell 对 `lifecycle.json` 的 90s 轮询。
3. **Herdr UI attach**（PowerShell）：`wezterm cli spawn -- <herdr.exe> session attach
   <session>` 打开 Herdr UI（结构化 `herdr session attach`，替代原先
   `wezterm cli spawn` + `send-text --no-paste` 键盘注入）；wezterm 无法直接 spawn
   时回退到 send-text。

> **为什么 still 需要 WezTerm 打开 UI**：Herdr 的 agent dispatch 目前仍要求 herdr
> 进程运行在交互式终端中（见 `2026-08-10-herdr-dispatch-interactive-terminal`）。
> `wezterm cli spawn -- <prog>` 把 `herdr session attach` 作为该 tab 的前台 ConPTY
> 进程运行，满足同一交互终端约束；当 Herdr 支持纯程序化 dispatch API 后可进一步
> 去掉这一步。

## 故障排查

- **`Herdr project namespace backend selection failed`**：
  CCB daemon 已以非 Herdr backend 运行（旧 keeper 复用时 env 不含 herdr）。
  先 `ccb kill` 停止现有会话，再重试 `ccb herdr open`。
- **`Herdr server is not running`**：
  先运行 `herdr` 启动/attach persistent session，再执行 `ccb herdr open`。
- **`provider ... does not support herdr-native launch`**：
  provider 不在显式 herdr allow-list。改用 `codex`/`claude`，或移除
  `[runtime.mux] backend = "herdr"` 配置走 tmux。
