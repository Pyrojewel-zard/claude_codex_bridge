# 无历史会话快速启动：分析任务

## 目标
分析 CCB 全项目启动速度、稳定性及无历史新 session 的关键路径与文件读写，输出可实施、可验证的完整优化计划；本轮不改业务代码。

## 阶段
1. [complete] 检查当前代码、fork 约束、现有测量设施。
2. [complete] 追踪历史判断、home 物化、启动与 readiness 的读写和等待。
3. [complete] 编写分阶段优化、读写一致性、基准与验收方案，纳入全项目 G1–G6 工作包。
4. [complete] 核对源码证据，交付计划及验证边界。

## 交付
- docs/plans/2026-09-05-fast-new-session-startup-plan.md：234 行完整计划，12 节，含 P0–P5 和 G1–G6。
- 本分析任务已完成；计划中的业务实施、实测基准与性能验收尚未开展。

## 决策
- Codex 为主要案例，Claude 和其他 provider 给出共享接口与适用边界。
- 区分无记录、记录无效、历史存在、未知/I/O 错误；不将查找超时当成无历史。
- 不把未测量的延迟或收益写成实测结论。

## 错误
- 搜索了不存在的 runtime_launcher.py/readiness.py；用 rg --files 定位实际模块，未修改源码。

## 执行状态（2026-09-06）

- 已完成 P0 观测、P1 无历史 session 决策、P2 Codex config 单次发布、G3 monotonic 启动预算：对应提交 `dd94db89`、`ecabfb07`、`5c4b67ba`、`77517275`、`66f0d6f9`、`1647c3a6`。
- P1：无绑定/受控 pristine home 快判；resume/fork/authority 仍复用同一事务决策和 payload，未知/损坏回退兼容路径。
- P2：source config 在事务内单次 snapshot，主 `config.toml` 内存合成后 if-changed 原子发布一次；sidecar/auth/skills/plugins 等仍独立持久化。
- G3：CLI→keeper→daemon 使用绝对 monotonic deadline 和 remaining budget；RPC/ready 等待不超过总预算，保留 lock、PID/cmdline/socket、generation/startup fence。
- 联合集成回归：732 passed；相关全量测试第一次运行 6932 passed、3 skipped，因外部 `CCB_CONTROL_PLANE_RPC_TIMEOUT_S=2` 与一个硬编码 `0.5` 测试断言冲突而停止；该断言已改为读取 policy，`pytest --lf` 2 passed。
- 修复 `dev_tools/perf_ccb_startup.py` 对本 fork runtime-root relocation 的路径假设：启动前后重新解析 `runtime-root-ref.json`，报告、lease/lifecycle/state、agent runtime、supervision、session/FIFO 和 pristine 校验均跟随实际 runtime root；新增回归测试。
- 隔离真实 `pristine` stub benchmark 已成功：`status=ok`、`cleanup.resource_audit.status=clean`、启动 wall `3982.7 ms`、CLI `2685.0 ms`、supervisor `801.1 ms`、agent runtime `113.0 ms`；但仅 1 sample 且 resource gate degraded，资格仍为 smoke-only，不宣称 p50/p95 加速。
- G1/G2/G4/G5 lazy import、Git/tmux snapshot、并发和 P3 历史索引仍保持 deferred，需达到正式 warmup/sample/resource 质量门槛后再做收益决策。
- 全量回归在修复前达到 7112 passed/3 skipped，暴露并修复一个与本次启动改动无关的 Windows isolation allowlist 漏项；修复项定向 12 passed。由于完整 7206 项未在该 allowlist 修复后重跑，验收记录保持诚实边界。

## 验收收口（2026-09-07）

- [x] 修复 relocated runtime root 下 benchmark 固定读取 `.ccb` 的路径错误。
- [x] 修复 never-started authority 被误判为未停止的场景构造 bug。
- [x] 验证 20 个独立新项目 pristine 序列：20/20 成功、20/20 cleanup clean，p50 3824.18ms、p95 3942.93ms（smoke/resource degraded）。
- [x] 验证受影响代码与回归：136 passed；静态检查与 sidebar wrapper 检查通过。
- [x] warm 20-sample p95：补齐 tmux pane PID 观测后 Claude warm `20/20` 成功，p50 `1625.29ms`、p95 `1671.30ms`，scenario/cleanup 通过；工具仍因资源 formal gate 保持 smoke-only。
- [ ] formal claim qualification：需要 resource profile process-IO 完整、instrumentation/A-B 和完整 scenario matrix；当前不以 smoke-only 结果宣称 formal claim。
- [x] 修复后重新跑完整 `python3 -m pytest test/ -q`：`7205 passed, 3 skipped`（44:13），无失败。
- [x] tmux PID 补丁后的最终完整回归：`7208 passed, 3 skipped`（35:32），无失败；diff/compile/sidebar wrapper 检查通过。
