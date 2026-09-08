# CCB 全项目启动速度、稳定性与无历史新会话优化完整计划

日期：2026-09-05。代码基线：`1a7ca9e7`。状态：分析完成，按下列任务进入分阶段实施。

范围补充：按用户追加要求，覆盖整个 CCB 项目启动链及稳定性。第 10–12 节为全局优化工作包，与前面的无历史 session 专项共同构成实施计划。

## 1. 结论与边界

优先做“无记录早判 + 单次决策复用 + 配置内存合成、单次发布”。Codex 缺少绑定记录时的 resolver 已经直接返回，不能把启动慢一概归因于搜索历史。更直接的开销来自 resolver 外部提前求值的指纹、重复回退查询、配置反复读写，以及多 agent 的顺序准备。Claude 的 fallback 历史枚举和已有 Codex 绑定的 fork 后代扫描，需要单独处理。

本轮仅分析仓库实现并制定计划，没有启动真实 provider、访问个人会话正文、实施业务修改或测出本机端到端加速比例。下面的性能数字是拟定验收预算，必须由 P0 基准校准。用户所说“new session”分成三个不同结果：

1. CCB 生成新的 launch generation/ccb_session_id。
2. provider 进程启动并可以接收输入。
3. provider 产生自己的 native session ID 和首个持久化记录。

第三项可能要到首次输入才发生；不能等待不存在的 transcript 才宣告第二项完成，也不能用 CCB ID 冒充 native ID。计划默认覆盖 Codex 和 Claude，其他 provider 通过适配器逐步接入；hapi 模式保留既有集成和独立就绪证据。

## 2. 当前路径与证据

| 路径 | 当前证据 | 对方案的约束 |
|---|---|---|
| workspace/binding 准备 | `lib/ccbd/start_preparation.py:prepare_start_agents` 顺序处理 spec 保存、workspace、binding，再顺序 prepare provider | 并发之前必须分清共享 namespace 与 agent 私有写入 |
| Codex 缺记录 | `lib/provider_backends/codex/launcher_runtime/session_paths.py:load_resume_session_id` 在路径/数据缺失时返回 None | 不新增常驻全库索引来解决已经 O(1) 的路径 |
| resolver 外开销 | `command_runtime/service.py:_codex_args` 提前求值 authority/memory 指纹；resume 未命中后 continuation 再算 authority | 把判定输入读一次，延迟指纹计算，去重 fallback |
| Codex 后代查找 | `session_paths.py:_latest_linear_descendant` 对有效 base binding 才 glob 全部 JSONL、读 meta、构建 children | 索引优先服务旧绑定修复，不跳过分叉/authority 校验 |
| Claude 历史查找 | `claude/launcher_runtime/history.py:latest_session_id_for_candidates` 候选无历史后枚举全部 managed projects | 新 home 可跳过；已有 home 要保留 Windows/Linux slug 回退 |
| 当前物化去重 | `lib/cli/services/provider_hooks.py:prepare_provider_workspace` 已传 materialize_home=False，再物化 home | 旧文档“三次物化”不代表当前实现；先数实际调用 |
| config 读写 | `lib/provider_profiles/codex_home_config.py:materialize_codex_home_config` 主配置、role MCP、catalog、model、hook 等分阶段操作目标文件 | 在内存中完成语义合并，再写最终结果 |
| 持久化 | `lib/storage/atomic.py` 已有 if_changed；durable write 做 fsync/replace/目录 fsync | 复用已有设施；按数据类别优化，禁止全局去 fsync |
| readiness | `lib/runtime_observability/startup_readiness.py` 已有 T0–T6 | 沿用时间轴，补 native ID/首次可输入的独立指标 |
| Codex 输入 readiness | `codex/execution_runtime/readiness.py` 0.2s 轮询、0.5s 稳定窗、成功后额外 0.2s | 该函数属于 execution 路径，必须先证明处于首个任务关键路径，不能直接算进每次启动 |
| keeper | `lib/ccbd/keeper_runtime/loop.py` 先 reconcile 再 sleep | 0.5s loop 周期不等于每次 cold start 固定延迟 |

既有性能资料位于 `docs/plantree/plans/ccb-runtime-performance/`，测量工具为 `dev_tools/perf_ccb_startup.py`。旧记录约 2.20s cold、0.555s warm p50 来自其他环境和 stub，且 warm prepare=0 与本 fork 每次 Codex 重建约定不同，不作为此次性能基线。

## 3. 无历史快速决策

新增不可变 `SessionStartDecision`（建议放 provider_core，名称为设计草案），由 prepare 阶段生成并经 PreparedStartAgent/prepared_state 显式传递。内容：project_id、agent、provider、workspace、runtime home、generation、restore policy、decision、reason、已验证的记录版本、需要时才有 authority/memory 指纹。不要传未脱敏 auth payload 到日志。

决策状态不是简单 bool：

| 状态 | 条件 | 动作 |
|---|---|---|
| NEW_EXPLICIT | 用户明确不恢复 | 跳过历史查找；保留旧记录；生成新 launch |
| NEW_PRISTINE | 当前受控事务创建全新私有 home，确认不存在绑定和原生历史 | 跳过旧历史解析、后代扫描、旧会话指纹比较；执行必要配置/auth 检查后直接启动 |
| NEW_NO_BINDING | 当前 provider 的权威绑定记录确实 ENOENT | Codex 保持现有“无绑定新启动”语义；Claude 只有进一步确认 home 无历史才 new |
| RESUME / FORK | 有效绑定或 linked continuation，authority、路径、父子关系匹配 | 同一决策中完成一次校验，按原语义恢复 |
| NEW_INCOMPATIBLE | 明确跨 provider/authority 不兼容且现有策略要求 new | 保留历史和拒绝原因；不能误写成无历史 |
| UNKNOWN / INVALID | 权限错、损坏 JSON、部分写入、目录查询失败、超时 | 保留原因并进入兼容恢复/诊断；不得写入“无历史”缓存 |

Codex 具体修改：先加载绑定记录一次；无绑定不计算仅用于历史比较的 memory/authority 指纹，不调用 linked continuation 二次读。同样的 payload 提供给 resume、fork 和 provider compatibility 校验。即使跳过恢复比较，仍须执行启动配置/auth 必需验证。历史解析与持久化修复先保留原安全顺序，后续才拆纯判定和 CAS 提交。

Claude：全新 home 的快判依据必须由创建事务证明，不能仅凭 `.ccb` session 文件缺失。已有 home 仍有用户手动启动、slug 迁移或绑定丢失的可能。事务内缓存一次 locator 结果，兼容项目 cwd 变化；不要默认取消跨 slug fallback。

负缓存第一期仅在同一启动事务有效，不使用长期 `no_history=true`。失效条件包括 generation、home/workspace、restore policy、binding version 变化和 provider 创建事件。后续如果持久化负缓存，必须有受控写入 generation；目录 mtime/TTL 无法证明多层目录和外部 provider 没有新增历史，只能作为提示。

## 4. 读写方案

### 4.1 一次读取与一致快照

启动事务开始时解析 project config、每个 agent spec/profile。source config 按规范化路径在本事务读取一次并解析为不可变对象；相同 source home 的 agent 共享只读输入，输出仍各自隔离。snapshot key 至少含 source identity、schema、配置内容/版本、env 覆盖和 agent policy；auth 不进入磁盘缓存。

绑定读使用 open/read 并处理 ENOENT，避免到处 exists→read 双重探测。文件被替换时用 stat identity/版本前后检查，发生竞争重读一次或退回标准路径。优化前用计数确认真实重复；不把所有 stat 都去掉，因为 symlink/ownership 检查有独立作用。

每次 `ccb start` 仍从 source 重新派生 Codex config：禁止“目标存在就直接复用”。同一次启动内的下游用准备结果，不重复 materialize。若 source 在准备后改变，定义快照边界；提交前检测关键输入变化，有限重试或要求下一次启动，不允许无限重试。

### 4.2 config 一次发布

将 source TOML → sanitize → profile/env/agent model → MCP/plugins → catalog 引用 → project trust → managed hooks → source-test shim 等操作改为纯内存转换；按当前实现顺序建立语义 golden 测试。最终 render 一次，使用已有 if_changed 原子写入接口在私有目标目录发布。

发布前验证 catalog sidecar、hooks 和权限。source 不存在、非法 TOML、copy/symlink/none auth 分支保持兼容；不能以空配置静默覆盖解析错误。目标被 provider 改写时，与重新派生的最终内容比较，发现偏差必须纠正。检查目标类型、symlink 和私有目录所有权后才允许免写，不把内容相等当成权限安全证明。

配置缺失时一次写；配置不变时零写；多个 model/catalog/hook 分支同时启用时最多一次主 config 发布。sidecar 独立计数，不以减少主配置写入掩盖额外复制成本。

### 4.3 数据分类及落盘契约

| 数据 | 读策略 | 写策略 | 时机/崩溃语义 |
|---|---|---|---|
| session binding、launch generation、lease/ownership | 当前权威记录、版本检查 | 原有锁 + 原子 durable 写；必要时 CAS | 承诺 launch/ready 前完成；不合并掉 fence |
| config、spec/profile 投影 | source snapshot + 目标内容比较 | if_changed；保留既有持久化要求 | spawn 前发布，错误阻止本 agent 启动 |
| auth | 当前授权来源及 symlink 状态 | 保持 fork symlink 优先、copy fallback、none；不缓存明文 | spawn 前验证；不覆盖 source |
| skills/plugins/catalog | 受控 manifest/revision + 必要路径校验 | 不变免复制；共享不可变资源按 bundle 锁发布 | 首次启动所需资源不可延后 |
| history index（P3 可选） | 精确 key + 有效性验证 | 可重建派生数据，原子发布 | 索引损坏回源；不具备删历史或改 authority 权力 |
| startup 计时/计数 | 内存累计 | 启动结尾批量输出一次 | 诊断丢失不影响启动正确性 |
| 审计/任务交付事件 | 保持消费者要求 | 按现有 JSONL 契约，不能套用诊断批量策略 | 不损失 mailbox/ack/任务完成证据 |

跨多个文件的 atomic replace 不构成事务。第一期保留现有顺序，只合并一个 config 的构建过程。若后期引入 generation manifest：先写私有 staging、校验全部必需文件，再 durable 发布版本指针；失败保留旧 generation，恢复程序清理未引用 staging。不能把 auth symlink 或动态可写 provider home 整体当成不可变 bundle。

### 4.4 大历史目录

P3 才考虑每个 managed home 的派生索引：session ID → path/meta identity，parent ID → children，cwd/authority → latest verified binding。先采用当前单写者能维护的小 manifest；规模测量证明有必要再选 SQLite，避免额外连接、锁和迁移开销。无论 JSON 还是 SQLite，原生 transcript 仍是事实来源。

bridge 观察到新 session 时更新索引；外部 CLI、bridge 停机期间新增文件必须被识别为索引覆盖未知。不能仅凭过期索引排除分支。恢复路径必要时仍回源扫描，后台构建只降低后续开销，不改变当前恢复决定。读取 meta 采用已有有界读取能力并测量字节数，不随意截断未找到的 session_meta 然后当作空历史。

## 5. 启动速度与并发

拆时间：T_cli/import、T_keeper/daemon、T_workspace、T_home、T_history、T_spawn、T_input_ready、T_native_id。总时延以关键路径实测，不能简单相加各并行 span。新增 session 并不消除 provider 自身 MCP/plugin 加载和网络握手。

P1/P2 保持顺序启动，先去掉重复计算和重复 I/O。P4 再做有界并发：默认实验 cap=2，同时测 1/2/4；私有 agent home 的准备可并行，Git worktree、共享 plugin bundle、namespace/layout 变更按资源加锁，最终 registry/ownership 发布受 coordinator 管理。已存在的 process_parent_snapshot 是否跨线程安全须先核查；上下文计数和 trace 通过显式上下文传递。

可先调度前台目标，但不静默改变“全部请求 agent 就绪才成功”的 CLI 契约。若引入前台优先模式，要显式提供 partial-ready 状态、后台失败通知和完整 readiness 时间点；作为独立后期功能。

不直接缩短所有 timeout。真实 provider ready 事件若可靠，可替代 text 稳定轮询；其余路径保留退避与超时。Codex execution readiness 的 0.5s 稳定窗加 0.2s 采样及成功后 sleep，可能产生额外输入延迟，但要验证首个任务实际调用和误判率。空 pane、登录提示、插件加载中不得误标 ready。native ID 为 pending 时可输入，但后续投递与绑定必须基于当前 generation，禁止沿用上一会话 ID。

## 6. 基准与验收

P0 在仓库外临时项目通过 ccb_test 构造数据。固定 commit、Python/provider CLI 版本、机器、磁盘、OS、依赖状态。不清用户缓存，不启动个人已有项目。先 fake/stub 验证 CCB 本身，再真实 Codex/Claude 无输入与首次输入两组。真实网络耗时单列，不能用 stub 结果宣称真实会话收益。

矩阵：新 daemon/已有 daemon × 全新 home/已准备无历史/有效历史/损坏记录/跨 authority × 1/4/10 agents × local relocated/anchor；补大目录 0/1k/10k 合成 JSONL、并发写入和 Windows/WSL。cold daemon 不等于冷 OS page cache，两者分别记录。

沿用 perf_ccb_startup 的 cli-only/warm/mixed-recovery/full-cold/pristine。pristine 当前限制 iterations=1、warmup=0，应由外层驱动创建至少 30 个不同新项目，不能反复用同一 home 冒充无历史；warm 至少 50 次，p99 需更多样本。报告 p50/p95、样本数、失败率、原始样本与配置，交错运行 before/after，检查 instrumentation 开销。

统计每个阶段 wall time、CPU、read/write syscall/字节、stat/getdents、JSON/TOML parse、fsync 次数与耗时、子进程数、tmux 调用、锁等待、history 文件数、prepare 次数。计数优先复用 startup_operation；strace 等详细追踪仅用于独立诊断轮次，以无追踪 wall 验收。

拟定预算（P0 后冻结，非实测承诺）：

- 已确证 NEW 分支：历史 JSONL 扫描/读取数为 0；restore-only 指纹为 0；绑定读取不重复。
- 每 agent 每启动事务：主 config 最多一次发布；内容不变为零；按 fork 要求重新派生一次；重复 home materialize 为零。
- 无历史 resolver 在本地盘 p95 目标 ≤10ms，单列含/不含 import；不把慢网络盘强制纳入这个预算。
- 无历史 1-agent 的 CCB prepare/history 阶段 p95 目标降低 ≥30%；stub T0→ready 目标降低 ≥20%，若该阶段基线极小则以操作计数与无回退为主要收益，不夸大比例。
- 有历史恢复 p95 不回退超过 5%（结合重复试验误差）；authority、fork 分叉、旧会话保留正确率必须 100%。
- 并发只有在 4/10-agent p95 改善、单 agent 无明显回退且峰值内存/锁竞争可接受时启用。

收益上界计算：若历史/准备只占总启动比例 f，该部分加速 k 倍，总加速为 1/((1-f)+f/k)。例如占 10% 的部分即使消除，也只能约 1.11 倍；因此优先按 P0 火焰图/阶段表排序。

## 7. 实施步骤与交付物

| 阶段 | 改动与范围 | 验证/退出标准 | 依赖 |
|---|---|---|---|
| P0 基准 | 扩展现有 perf 工具与计数，生成无历史构造证据；补首次可输入和 native ID pending 观测 | 保存 baseline.json、samples.jsonl、环境与阶段分解；能重复重现 | 无 |
| P1 NEW 决策 | _codex_args/session_paths，Claude restore/history；不可变决定通过准备对象复用 | 无记录不计算历史指纹、不重复读；损坏不缓存为 absent；resume/fork 原语义 | P0 |
| P2 配置读写 | codex_home_config 内存合并、if_changed；事务 source snapshot；prepare 结果复用 | 主配置 0/1 次写；所有优先级与安全投影回归通过；读取字节减少 | P0；与 P1 可独立开发 |
| P3 历史索引 | 仅当大目录扫描占比达到显著瓶颈才实施；bridge 更新与失效机制 | 外部写入、fork 分支、索引损坏都正确回源，无历史无额外磁盘索引开销 | P1，P0 证明需要 |
| P4 并发与 readiness | 私有 prepare 并行、共享资源锁、事件驱动 ready 的 provider 适配 | cap 矩阵、首条任务不丢失、同 agent 双启动 fencing、部分失败可恢复 | P1/P2 稳定 |
| P5 交付 | 完整对比报告、fork 约束复核、上线开关/回滚 | 相关回归 + 全量测试 + 真 provider smoke 有证据；未完成项明确标注 | 所有启用阶段 |

每阶段独立提交，P3/P4 不与低风险 P1/P2 捆绑。优先实施顺序 P0→P1→P2→评估 P3/P4。粗略工作量：P0 1–2 天、P1 1–2 天、P2 2–3 天、P3/P4 各 2–4 天（条件阶段）；取决于真实 provider 和跨平台验证，不作为交付日期承诺。

## 8. 测试与故障恢复

先运行受影响文件：test_codex_launcher_session_paths、test_codex_start_cmd_parsing、test_hapi_command、test_ccbd_start_preparation、test_provider_profiles、test_v2_runtime_launch、test_projected_assets、test_storage_atomic、test_runtime_env_control_plane、test_path_relocation_defaults、test_startup_readiness_timeline、test_perf_ccb_startup。针对变更增补关键回归，不为简单字段逐一复制实现。

必须覆盖：无目录/空目录/有绑定无 transcript/空或损坏 JSON/权限错误；same provider 与跨 provider；linked/native fork、分叉与 cycle；source config 改变、target 被 provider 修改；symlink auth 与 copy/none；首次启动中途崩溃、提交前后 crash、第二个启动争用同 agent；ready 后 native ID 延迟出现；首条 ask 不丢失。

不修改 test/conftest.py；anchor fixture 放各自测试文件。默认 relocated 与 opt-out 都测试，确认 CLI→keeper→daemon 环境一致。资源 stub/role catalog 应预置或明确单列网络步骤，不能把网络失败算优化回归，也不能把人工中断说成通过。完成实现后按仓库要求运行 python3 -m pytest test/ -x；缺 helper 先验证构建依赖，禁止构建脚本覆盖 sidebar wrapper。

回滚：P1 保留原 resolver 路径作为兼容回退；P2 保留原渲染输出 golden、出错不启动；P3 索引可忽略重建；P4 回到 cap=1。回滚禁止清除 native sessions、auth、lease 或用户运行中状态。性能埋点不改变启动语义，诊断日志不含 token、完整配置、会话正文。

## 9. 本轮交付与未决项

本轮完成源码分析和计划落盘。没有测量本机 startup p95，没有执行性能优化，也未重复上一轮 20 分钟以上全量测试。待 P0 确认：用户感知慢主要出现在 CLI 返回、UI 可输入还是第一条请求；真实 provider 插件/网络所占比例；fork 重建是否要求每次物理写入（本方案默认要求重新派生、允许结果不变免写）；各 provider readiness 事件的可用性。

这些问题不阻止先实现测量和 P1/P2 的可验证部分；若实测证明 import/worktree 才是主要开销，调整后续排序并记录证据，不坚持预设历史扫描瓶颈。

## 10. 全项目启动链的代码优化

整体链路为 CLI/import → project/config/path → running intent/keeper → daemon/lease → workspace/binding → provider home → namespace/pane → session publication → input readiness。稳定性工作贯穿所有阶段，不能以 CLI 提前退出替代完成启动。

### G1：CLI 导入与路由

源码证据：ccb.py 在 main 前导入 cli.entrypoint、terminal 和平台能力模块，并执行平台检测；provider_hooks.py 顶层导入多个 provider home 实现。是否造成大部分延迟必须由当前版本 import profile 判断，不能沿用旧版本 211ms 数据。

改法：以命令分支/选中 provider 为界延迟导入；帮助/版本路径尽量不构造完整 service graph。保留 source runtime guard、Windows 编码和真正启动时的 Herdr gate。注册表优先存轻量 provider 描述，只有需要 launcher/home/execution 时再加载实现。模块缓存用 Python 自带机制，不增加全局可变业务 singleton。

验证：隔离环境测 --help/--print-version、config validate、pristine/warm startup 的 process entry→dispatch；用 -X importtime 单独采集诊断，不混入 wall 对比；检查选中 provider 缺依赖时错误仍准确，未使用 provider 缺依赖不应拖垮无关命令。测试入口保护和 Windows 行为必须保持。

### G2：project/config/path 与 Git workspace

源码证据：prepare_start_agents 对每 agent 执行 materializer/validator，WorkspaceMaterializer 对 worktree 检查仓库、已有 workspace、注册、分支，创建失败时有 prune/retry。这些 Git 调用在多 agent 上可能重复，当前总次数待测。

改法：项目级一次解析配置与 path placement，事务内共享 Git repo identity、HEAD 和 worktree list 快照；已有 workspace 用精确路径/branch/binding 验证，不每次重建。涉及 add/prune 的写操作按 Git common dir 串行，完成后使快照失效。COPY 模式首次复制单列成本，不能默认改 INPLACE 或丢文件来提速；超大仓库可后续提供显式复制策略。

验收：warm start 不应执行 worktree add/copy；同仓库只读 inventory 次数不随 agent 数线性倍增；用户 worktree 不被 prune/覆盖；branch 切换、外部 worktree、路径迁移、无 Git 仓库均有明确结果。

### G3：keeper/daemon、超时与环境契约

源码证据：ensure_keeper_started 已在 startup_lock 内二次检查；record_running_intent 故意重复清 shutdown intent 以防并发 stop；daemon ready 检查包含 startup/generation 身份。这些不是可以直接删掉的冗余。keeper/daemon wait 使用 time.time 与 50ms polling；startup_policy 定义多层 timeout。

改法：把超时计算统一为 monotonic absolute deadline，下游使用 remaining budget，限制 RPC timeout 不超过剩余预算；保留配置的总预算和错误阶段。区分 keeper_ready、daemon_ready、namespace_ready、agent_ready 与 attach deadline，不让层层重试累计远超用户预算。保留 lock 内 recheck、stop/start 排序、generation fence、PID+cmdline+socket 校验。

核查 CLI→keeper→daemon 的 control_plane_env allowlist 与所有 startup_policy 配置传播。上次历史曾出现 anchor 变量漏传；此次需用实际代码和子进程回归逐项验证 timeout/accelerator/source-home，不把旧会话诊断当成当前缺陷列表。可将启动相关配置解析为明确的只读启动策略并显式传递，禁止宽泛继承全部 CCB_*。

### G4：tmux/Herdr 布局与探测

源码证据：run_start_flow 已分阶段处理 layout、namespace 和 active panes，prepare_start_agents 接受 namespace_pane_records/process snapshot。先统计当前已有复用效果，再改缓存。

改法：每次事务为同 socket/session/namespace epoch 获取一次 pane/window 快照；所有 agent 绑定校验共享，发生 create/respawn/layout mutation 后更新或失效。多条无依赖 tmux 配置可批量提交，错误要精确归属命令；不能为批处理删除 ownership 检查。稳定 warm 场景不重复设相同 pane 元数据、不重排用户布局；重连单个 dead pane 只修复该对象。

跨平台分别验证 tmux 与 Herdr：命令批处理能力不可假设相同。sidebars、mobile/HAPI attach 共用后端接口但各有身份信息，UI 可见不等于 backend ready。

### G5：写入、索引和诊断

实施第 4 节分类表，先以实际计数找热点。spec、profile、namespace 等不变内容优先复用已有 if_changed；不要盲目新增 mtime/hash 文件，避免缓存维护比原始读取更贵。startup report 只写稳定结构和阶段统计；频繁 poll 的诊断写入可以汇总，但 lease heartbeat、mailbox ack、任务事件按独立可靠性契约保留。

### G6：并发、ready 和后台任务

实施 P4 的 bounded concurrency，并建立依赖图：workspace→home→spawn→ready；共享资源发布和 registry 提交可串行。后台更新检查、完整诊断、可重建历史索引只有在确认不参与启动所需认证/插件/角色/任务约束后才能延后。首次 roles/依赖安装若启动必须依赖，则标记 bootstrap 阶段并给出进度和超时，不能后台隐藏失败。

## 11. 稳定性设计与故障注入

| 故障 | 必须保持的性质 | 验证方式 |
|---|---|---|
| 两个 start、start 与 stop 竞态 | 同 project/generation 只有一个权威 owner；stop 不被旧 start 复活 | 并发子进程、屏障控制锁前后顺序 |
| keeper/daemon 退出 | restart 有界退避，旧 generation 不提交新结果 | 在 intent、spawn、lease、ready 各点注入退出 |
| 进程 PID 重用、socket 残留 | 不误附着、不误杀无关进程 | 仿真身份不匹配及真实临时进程 |
| home/config 发布失败 | 不发布半成品、不覆盖 source、保留可恢复旧状态 | ENOSPC、EACCES、replace/fsync 失败、源变更 |
| 单 provider 失败 | 成功 agent 的运行状态不被全局误回滚；整体结果准确列出失败 | N-agent 中一个 auth/exec/ready 失败 |
| 历史/索引损坏 | UNKNOWN 与 ABSENT 区分；不丢历史、不跨 authority resume | 损坏/空文件/循环 fork/外部写入 |
| readiness 误判 | 旧 pane 文本、空屏、登录提示不能接受错误 generation 的任务 | 首条任务投递及 delayed native ID |
| 时钟跳变 | deadline 不随墙钟跳变延长或提前结束 | mock wall clock 调整，monotonic 保持 |
| 依赖或网络不可用 | bounded failure + 具体 stage/cause，不无限等待 | provider 缺失、catalog 拉取失败、RPC 无响应 |
| 跨平台/路径差异 | relocated/anchor、symlink/copy fallback、短 socket 路径契约保持 | Linux/WSL/Windows 支持矩阵 |

审计 broad except 时逐个判断：诊断失败可吞但需有限计数；权威记录、认证、安全投影失败不得变成“无历史/已 ready”。例如 Codex execution readiness 当前读取 pane 异常返回 True、无输出超时返回 True，可能是兼容兜底，需追踪调用方投递策略并设计更明确 UNKNOWN 结果；本轮不能仅凭该函数断言生产必然丢任务。

观测字段：trace_id、project/agent 标识、generation、stage、duration、attempt、remaining_budget、decision_reason、readiness evidence、error_class、recovered_from。脱敏记录、不输出 secrets。失败报告必须说明停在哪阶段、哪些 agent 已启动、哪些可重试；重试沿原幂等/fencing 契约执行。

稳定性验收：关键竞态/持久化注入用例零错误 owner、零会话覆盖、零错误恢复；建议 nightly 1000 次 fake/stub start-stop-restart 和多 agent 局部失败循环记录失败率、孤儿进程/FD/内存增长。真实 provider 30 轮人工可复核样本，网络失败单列。零次失败仅说明样本观察，不能宣称绝对可靠。

## 12. 全项目实施顺序与统一验收

1. P0/G0：统一 T0–T6、input ready/native ID、I/O/子进程/锁等待基准，检查 import 和 workspace 占比，建立失败归因。
2. P1 + G3 稳定性基础：无历史决策、事务上下文、跨进程策略、deadline；保留既有 fencing。先补新改动涉及的竞态回归。
3. P2 + G5：配置单次发布、source snapshot、不变状态免写，验证 crash 和 symlink 安全。
4. G1/G2/G4：按实测贡献排序实施 lazy import、Git inventory、tmux snapshot/batching；各自独立提交与 A/B。
5. P3 条件实施；P4/G6 最后启用并发及前台优先选项。稳定性门槛不过则默认 cap=1。
6. P5：相关测试、完整 pytest、stub soak、真实 provider smoke、跨平台回归，发布 before/after 与未决限制。

全项目建议目标（待 P0 冻结）：pristine/cold/recovery 的 stub T0→全部 requested ready p95 改善 ≥20%；warm attach p95 改善 ≥15%；无关 provider 导入和 warm 重建 workspace 次数为零；同机对照无明显 CPU/峰值内存回退；失败必须落在总 deadline 与明确清理宽限以内。真实 provider 的 total、CCB overhead、first input 分开报告，不把 provider 外部网络时延算作代码改动收益。

补充测试映射：G1→test_ccb_python_launcher/test_source_runtime_guard；G2→test_workspace_git_worktree；G3→test_cli_daemon_keeper_runtime/test_ccbd_process_env/test_ccbd_startup_fence/test_v2_ccbd_start_matrix；G4→test_ccbd_startup_pane_snapshot/test_v2_runtime_launch/test_herdr_lifecycle_bridge；G5→test_storage_atomic/test_ccbd_startup_operation_counts；并发→同项目 start/stop、部分失败与连续 restart 的新增关键测试。

完成定义：全项目与无历史两套基准都有可复核结果；所有新增快路径均有退回标准路径和错误原因；auth/history/ownership 不变量未改变；全量测试无已知失败（外部依赖阻塞单列且不得称全绿）；剩余条件阶段明确未启用。估计在前述专项外，G1/G2/G4 各 1–3 天，G3/故障注入 2–4 天；先 P0 再细化排期。

## Global Constraints

- 不修改 `test/conftest.py`；锚定运行时状态的 fixture 只能放在对应测试文件。
- 保留 Codex fork 的每次 source→managed-home 重建语义；只允许同内容免写，不能以长期缓存跳过重新派生。
- 权威 session binding、generation、lease、ownership、auth 和 mailbox/ack 事件继续使用原有锁、原子 durable write、CAS/fencing 语义。
- `UNKNOWN`、损坏、权限错误、超时与 `ABSENT/NEW` 必须区分；任何 I/O 错误不得被负缓存成“无历史”。
- 所有优化必须有标准路径回退、可观测 reason/stage，并覆盖 relocated 与 `CCB_RUNTIME_STATE_ANCHOR=1` 两种布局。
- 每个任务独立提交；变更后运行受影响测试，最终按仓库要求运行 `python3 -m pytest test/ -x`；`file bin/ccb-agent-sidebar` 必须仍显示 shell script。
- 不运行 `bin/build-ccb-agent-sidebar`；若构建其他 Rust helper 产生覆盖，立即恢复 wrapper 并重新检查。

## Task 1 — P0 基准与启动操作可观测性

在不改变启动语义的前提下，完善现有 `dev_tools/perf_ccb_startup.py` 与 startup-operation/readiness 观测，使无历史、有效恢复、损坏记录、warm attach 和多 agent 场景可按阶段、读写与失败原因比较。沿用既有 T0–T6 和计数协议，补充 session 决策/历史解析、native-id pending、I/O 读写字节与 durable write skip 的明确字段；不把诊断写入放到 provider 关键路径。先在仓库外临时 fixture 做最小可重复 stub 基线，保存到本计划 SDD workspace，不提交个人运行状态或 secrets。若环境阻塞真实 benchmark，记录阻塞和已有静态/单测证据，不伪造性能数字。新增或调整测试必须断言数据内容、阶段关系和失败分类，而不是只断言字段存在。

## Task 2 — P1 Codex/Claude 无历史快速决策

为 Codex 首先实现一次事务内的 session-start decision：明确 `NEW_EXPLICIT`、`NEW_PRISTINE`、`NEW_NO_BINDING`、`RESUME`、`FORK`、`NEW_INCOMPATIBLE` 与 `UNKNOWN/INVALID`，并让 launch command 使用同一决策输入。无绑定/受控全新 home 时跳过历史指纹、linked continuation 和后代扫描；绑定文件读取与 authority/memory fingerprint 不重复；损坏、权限错误和超时必须保留兼容路径并返回 UNKNOWN。有效 resume/fork、provider authority、memory projection、旧记录保留和 fork 分支安全语义不能改变。Claude 只对事务证明的全新 managed home 走快路径，已有 home 继续保留跨 slug fallback。决策对象不可变、日志脱敏；按现有注入点补单测和恢复/分叉/竞态回归。

## Task 3 — P2 Codex 配置内存合成与单次发布

重构 `materialize_codex_home_config` 的主 config 路径：source TOML、authority、profile/env、MCP/plugins、catalog/model、project trust、managed hooks 和 test shim 在内存中按当前语义合并，最终 render 一次；目标内容相同时零写，变化时最多一次主 `config.toml` durable atomic publish，继续复用 `atomic_write_text_if_changed`/相关既有设施。sidecar、auth symlink/copy/none、skills/plugins、memory marker 等独立资源保持各自安全与持久化契约；非法 source 不能静默覆盖为空配置。用 golden/优先级/权限/崩溃测试证明输出不变和失败不半成品。

## Task 4 — G3 启动 deadline 与跨进程稳定性

把 keeper/daemon/startup wait 的内部时间预算统一为 monotonic absolute deadline，向下游传递剩余预算，禁止层层重试超过总 timeout；保留 startup lock 二次检查、running-intent stop 竞态保护、PID/cmdline/socket 身份核验、generation fence 和既有 control-plane 环境白名单。区分 keeper、daemon、namespace、agent 和 attach readiness；错误报告包含 stage/cause/remaining budget。补充时钟跳变、双 start/start-stop、残留 socket/PID 重用、keeper/daemon 退出和单 agent 失败测试，确认失败清理不误杀、不复活旧 generation。

## Task 5 — G1/G2/G4/G5 低风险启动路径收敛

以 Task 1 的测量结果排序实施：对无关 provider 采用按需导入；事务内共享 project/config/path 与只读 Git inventory snapshot；warm 场景复用 pane/window snapshot，变更后显式失效；不变的 source shim、spec/profile 投影和诊断输出使用 if-changed/批量内存构建。只读快照不得跨事务缓存 auth 或权威状态，Git add/prune、tmux ownership/layout mutation 必须按资源串行并保留安全校验。每一子改动独立小提交与 A/B 测试；若测量未证明收益，记录为 deferred，不为“优化”新增无效缓存。

## Task 6 — 条件阶段评估与统一验收

基于前述基线决定是否实施 P3 历史索引和 P4/G6 有界并发/readiness 事件；默认 cap=1，只有 4/10-agent p95 改善且稳定性门槛通过才启用。运行受影响回归、stub soak、并发故障注入、provider smoke 和全量测试；报告 before/after 的 p50/p95/p99、失败率、读写/parse/fsync/stat/tmux/锁等待/子进程计数，并明确外部网络或依赖阻塞。未满足条件的阶段保持关闭并写出回滚路径，不宣称未测量收益。
