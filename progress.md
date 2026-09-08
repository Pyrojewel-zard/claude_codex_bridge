# 工作记录

## 2026-09-05
- 已读取用户指定 planning-with-files 技能并调用 session-catchup。
- 新建计划、发现和进度文件；接下来进行源码追踪。
- 已核对 Codex/Claude 历史解析、provider prepare、配置写入、原子写入、keeper 初次循环及既有性能设施；形成分阶段方案。
- session-catchup 无恢复报告输出。源码路径搜索两处未命中已改用文件列表定位。
- 按用户追加要求扩展到全项目导入、Git workspace、keeper/daemon、tmux/Herdr、持久化及并发失败恢复。
- 完成 docs/plans/2026-09-05-fast-new-session-startup-plan.md，234 行/12 节；已核对范围、代码出处和状态，无业务代码变化。
- 检查 git status：仅新增四份计划文档。未运行性能基准或业务测试，未宣称已获得性能改善；历史测量与当前目标已明确区分。

## 2026-09-06 执行记录

- 在分支 `perf/startup-stability-20260905` 完成计划前四项实现；保持 upstream merge 基线 `1a7ca9e7` 和 sidebar wrapper 不变。
- 关键提交：`5c4b67ba` session-start decision，`77517275` Codex config single publish，`66f0d6f9` monotonic deadline，`1647c3a6` configurable RPC timeout test contract。
- 732 项 Task 1–4 联合回归通过；`python3 -m pytest test/ -x` 首次跑到 6932 passed、3 skipped 后暴露环境敏感断言，修正后 `python3 -m pytest test/ --lf -q` 为 2 passed。未重新耗时重跑 7206 全量，因此最终全量不标记为全绿。
- `file bin/ccb-agent-sidebar` 仍为 Bourne-Again shell script；`git diff --check` clean。
- 外部 benchmark 仍无有效时延样本；不实施无证据的 G1/G2/G4/G5/P3/P4 性能缓存或并发改动。

## 2026-09-07 全量验收补充

- 第二次完整回归实际达到 `7203 passed, 3 skipped, 1 failed`，唯一失败是直接构造 provider state 的测试在默认 relocated runtime state 下复用了同一临时项目身份；加 `CCB_RUNTIME_STATE_ANCHOR=1` 隔离后，受影响联合测试 `136 passed`。
- 新增 benchmark 回归：从未启动项目的 authority records 为 `absent` 时，场景构造器应视为已停止；已存在但脏的 lifecycle/lease 仍拒绝。`test_perf_ccb_startup.py` 当前 `107 passed`。
- 20 个不同新项目的 pristine 外部序列全部成功、cleanup 全部 `ok`；wall p50 `3824.18 ms`、p95 `3942.93 ms`。每个单样本仍是 smoke-only/resource gate degraded，因此不宣称 formal qualification。
- warm formal 验收发现两个边界：Codex fork 策略要求复用 binding 仍重建 managed `config.toml`，故 provider preparation 非零是预期成本；Claude stub 缺少可验证 runtime PID，warm identity 门禁拒绝，不能伪造 warm p95。
- 静态验收：`git diff --check` clean、目标文件 compileall 通过、`bin/ccb-agent-sidebar` 仍为 Bash wrapper。外部 EDA CCB 只读审计已提交，未修改外部项目且按 ask 约定不轮询。
- 修复后完整 `python3 -m pytest test/ -q` 最终通过：`7205 passed, 3 skipped in 2653.09s (0:44:13)`，无失败；pytest 进程已退出。
- 为 tmux pane-backed provider 增加 best-effort `pane_process_info`（`#{pane_pid}`），并在 agent runtime resolver 接入 tmux/未显式标注 backend 的 `%N` pane；定向回归 `26 passed`。这补齐了 Claude 等没有 provider-session PID 的 warm identity/资源审计观测。
- 补丁后 Claude warm benchmark 已完整闭环：`status=ok`、`20/20` measured、`3` warmups、scenario gate `24/24` pass、cleanup/resource audit clean；external p50 `1625.29 ms`、p95 `1671.30 ms`、agent duration p50 `5.03 ms`。工具仍为 smoke-only（resource profiles quality/process IO formal gate 未完全满足），不冒充 formal claim。
- tmux PID 观测补丁后的最终完整回归：`python3 -m pytest test/ -q` 为 `7208 passed, 3 skipped in 2132.78s (0:35:32)`，无失败；`git diff --check`、目标 compileall、sidebar wrapper 检查均通过，pytest 已退出。

## 2026-09-07 Codex paginated lineage 自动修复

- 复现 EDA 项目 `leadwork2` 的真实链路：当前 rollout `01a06749…` → `01a0667b…` → 缺失的源 rollout `01a05fcb…`；仅有 `session_index.jsonl` 记录不足以支持 Codex `thread/resume`。
- `session_paths.resolve_resume_payload()` 现在在把 session id 交给 Codex 前递归校验 `forked_from_id` lineage；检测到 `missing_source_rollout` 或 `lineage_cycle` 时，仅加锁隔离 binding，保留所有历史 rollout，并清除 resume 参数，让下一次启动自动建立新 session。
- 扫描目录发生 I/O 异常时不自动清除 binding，避免把“暂时不可读”误判成历史损坏。
- 新增多级 lineage/quarantine 回归；相关测试 `50 passed`，启动/决策联合测试 `191 passed`；真实 EDA binding 只读检测结果为 `missing_source_rollout`，未直接修改外部项目。

## 2026-09-06 后续执行

- 找到并修复 benchmark 的真实 fork 兼容性缺陷：CCB 默认把 mutable runtime state 迁移到 `~/.local/ccb/projects/<id>/`，但基准工具仍固定读取项目 `.ccb/ccbd`，导致启动报告存在却被误报为缺失。
- `dev_tools/perf_ccb_startup.py` 现在在启动前后动态解析 `runtime-root-ref.json`；锚定配置仍读取项目 `.ccb/ccb.config`，状态/报告读取迁移后的 runtime root，并允许 session/FIFO 在 anchor 或 active runtime root 下。
- `python3 -m pytest test/test_perf_ccb_startup.py -q`：106 passed。
- 全新隔离 fixture 的真实 `pristine` benchmark：`status=ok`，`abort_reason=null`，`scenario_construction_gate=pass`，最终 cleanup resource audit=clean；单样本 wall `3982.667 ms`。由于 `n=1`、formal thresholds 未满足且 resource gate degraded，只作为 smoke evidence。
- 完整 `python3 -m pytest test/ -x -q` 重跑到 `7112 passed, 3 skipped` 后发现一个独立的 Windows PR isolation allowlist 漏项：已存在的 `7a49d4ef` Herdr lifecycle bridge import 未列入 frozen allowlist；加入精确 allowlist 项后 `test/test_windows_pr_isolation.py` 为 `12 passed`。未再次耗时重跑全部 7206 项，故最终记录为“全量基线 + 修复项定向验证”，不虚报全量绿。
