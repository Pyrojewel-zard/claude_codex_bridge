# 代码证据与性能发现

- 2026-09-05：开始时 git 工作树干净；用户要求完整计划，重点为无历史新 session、启动速度、读写方案。
- 上一轮全量测试并未全绿完成，不能沿用为本方案验收证据。
- Codex load_resume_session_id 已在 session 路径/记录缺失时直接返回；不能假设无历史必然做全盘扫描。存在记录时 _latest_linear_descendant 才会扫描 session_root 的 JSONL。
- Claude restore=False 已直接返回；restore=True 在项目绑定无法给出结果时仍调用历史定位器。prepare_start_agents 的 workspace 与 provider prepare 是两个顺序循环。
- fork 要求每次启动从 source 重建 Codex config，不能用长期缓存跳过；优化方向是事务内复用和内容不变免写。
- Claude history.py 在候选目录无历史时枚举 managed home 下全部 projects；按 JSONL mtime 选最新并多次 stat。Codex descendant 修复会 sorted(glob('**/*.jsonl'))，但有 base_id/path/root/cwd 守卫。
- storage.atomic 已有 atomic_write_text_if_changed/json_if_changed，并非需要从零实现。标准 durable write 包含文件 fsync、replace、目录 fsync；必须按数据类别优化，不能全局删除持久化屏障。
- 已有 StartupReadinessRecorder T0–T6 与 dev_tools/perf_ccb_startup.py；应扩展既有测量设施，避免新造互不兼容的时间轴。
- _codex_args 在调用缺失即返回的 resolver 之前已求值 authority/memory fingerprint；resume 未命中后 continuation 分支再次计算 authority fingerprint。这是无记录路径的具体可删重复工作。
- prepare_provider_workspace 当前明确 materialize_home=False，随后只在 _materialize_provider_home 物化；旧性能文档的“三次物化”不能直接当作当前事实。
- Codex config 当前先写主配置，再由 role MCP/model catalog/model 等 helper 更新；应改为内存合成最终配置后单次发布。
- keeper 第一次 reconcile 在 sleep 之前，不能宣称每次冷启动固定浪费 0.5 秒。
- 追加范围：全项目启动速度与稳定性。已查 ccb.py 顶层导入、keeper startup_lock 二次检查、running intent 对 stop 竞态的保护、workspace worktree add/prune/validate、startup_policy 与 wall-clock wait。
- 广义 except/ready 兜底需要调用链验证，不能据此断言丢任务。源码直接给出的风险候选：Codex execution readiness 读 pane 异常或无输出超时可能返回 True。
- 旧性能文档的 0.555 秒 warm p50 和 2.20 秒 cold 是别的机器/旧版本/stub 证据，且 warm prepare=0 不满足当前 fork 的 Codex 重建约定，不用作本机基线。

## 执行后的验证证据

- 无历史/有效恢复/配置发布/启动预算的联合回归共 732 passed；单独 Task 4 启动稳定性集 110 passed。
- 启动预算已覆盖 CLI lifecycle、keeper ready/exit、daemon readiness、daemon/PID release wait；子进程 timeout 通过 control-plane allowlist 传播，错误带 `stage` 与 `remaining_budget_s`。
- 墙钟跳变测试证明 persisted wall timestamp 只在 marker 变化的观察边界转换为 monotonic deadline，等待期间不会因 wall clock 调整延长。
- 全量首次执行结果为 6932 passed、3 skipped 后在 `test_v2_tmux_cleanup_history.py` 的硬编码 `0.5` 断言停止；当前环境实际 `CCB_CONTROL_PLANE_RPC_TIMEOUT_S=2`。断言改为 policy 常量后 `pytest --lf` 2 passed，但未重新跑完整 7206 项，故不记录“全量全绿”。

## Benchmark path correction and first valid smoke

- 本 fork 的 `choose_runtime_state_placement()` 默认将 `.ccb/ccbd`、`.ccb/agents` 等 mutable state 迁移到 `~/.local/ccb/projects/<project_id>/`，仅留下项目锚定配置和 `runtime-root-ref.json`。
- `dev_tools/perf_ccb_startup.py` 原先固定读取 `project/.ccb/ccbd`，因此真实启动虽成功写出报告，工具仍返回 `startup report was not created or updated`。这是 harness 路径错误，不是 ccbd 启动失败。
- 已修复为：锚定数据继续从 `project/.ccb` 读取；启动前后根据 `runtime-root-ref.json` 解析 active runtime root；报告、authority、namespace、agent runtime、supervision、session/FIFO 和 pristine/unmount 检查全部使用 active root。
- 真实隔离 `pristine` stub smoke（1 sample）通过：wall `3982.667 ms`，CLI `2685.029 ms`，supervisor `801.142 ms`，agent runtime `112.964 ms`，agent provider prepare `19.710 ms`；readiness T1 `1643.453 ms`，T4 `3583.784 ms`；cleanup resource audit clean。
- 该样本的 resource gate 为 degraded、formal thresholds 为 `warmup=0/sample=1`，所以只能证明测量闭环和首个数量级，不能作为正式性能收益或 p95 结论。

## Full-suite boundary finding

- 完整回归（修复 allowlist 前）实际达到 `7112 passed, 3 skipped`，唯一失败是 `test/test_windows_pr_isolation.py::test_current_shared_windows_reverse_dependencies_do_not_expand`。
- 根因是已提交 `7a49d4ef` 在 `lib/ccbd/app_runtime/service_graph.py` 引入按需的 `platforms.windows.herdr.lifecycle_bridge`，但 `platforms/windows/tools/check_pr_isolation.py` 的 frozen existing-debt allowlist 漏记该 pair；不是本次启动 benchmark/runtime-root 修改引入的依赖。
- 已加入精确 allowlist 项，Windows isolation 文件 12 tests 全部通过；完整 7206 项未在 allowlist 修复后重跑，最终状态按证据边界报告。

## 2026-09-07 验收边界

- `authority_records=absent` 是“从未启动”的合法安全状态；scenario constructor 以前只接受完整 stopped records，现已修复并加回归。
- Codex reused binding 的 provider preparation 不是重复 bug：既有测试明确要求每次 `ccb start` 重建 managed Codex config，以使模型/MCP/plugins 源配置立即生效。性能报告应把该成本单列，而不是删除一致性保证。
- warm formal harness 还要求 agent runtime PID 和 provider preparation=0；当前 Claude source stub 不能提供 runtime PID，Codex 又有合法 preparation 成本，因此当前证据只能报告 cold/pristine smoke 和 targeted regression，不能报告 warm formal p95。
- 全量最后一次完整 run 的唯一失败已由测试隔离修复；修复后的三个受影响测试文件为 `136 passed`。未重新等待约 33 分钟的 7206 项全量，因此不写“修复后全量绿”。
- 随后已完成修复后的完整回归：`7205 passed, 3 skipped`（44:13），因此全量代码回归现已闭环；剩余未闭环的是需要真实 runtime PID/真实 provider 的 warm formal 性能资格，不是测试失败。
- 后续发现并修复 warm 观测链路的实际缺口：tmux backend 没有 pane PID 查询，且下游只允许 herdr resolver；现已让 tmux/`%N` pane 回填 `runtime_pid`。Claude stub warm 20-sample 已成功，p50 `1625.29ms`、p95 `1671.30ms`，但资源质量门禁仍使 `formal_claim_allowed=false`。
- tmux PID 补丁后的完整回归为 `7208 passed, 3 skipped`（35:32），所以当前工作树的代码稳定性验收已完成；未完成项仅是 benchmark 工具的 formal claim qualification（资源 process-IO、A/B、完整矩阵门禁）。
