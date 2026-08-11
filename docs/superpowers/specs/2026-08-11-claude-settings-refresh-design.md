# Claude Settings Refresh Design

## Goal

每次 CCB 启动 Claude agent 时，从源 `~/.claude/settings.json` 重新生成 managed `settings.json`，同步用户普通配置和插件配置，同时保留 CCB 注入的运行时 hooks、权限和认证状态。

## Current Problem

Claude HOME 物化会读取源 settings，但 `_merge_settings_payload()` 会把 managed 文件中的旧 `enabledPlugins` 合并回来。源文件删除插件或修改插件状态时，旧条目因此残留。

## Design

- 源 settings 是普通配置、`enabledPlugins` 和 `extraKnownMarketplaces` 的权威来源。
- managed settings 中的 CCB hooks 与权限策略继续保留；源 hooks 与 managed hooks 去重合并。
- 认证环境变量和其他受保护运行时状态继续沿用现有 carry-forward 规则。
- 启动前沿用现有 `prepare_provider_workspace()` 的 Claude HOME 物化路径，不增加新的启动阶段或配置项。

## Verification

- 源插件删除后，下一次物化会删除 managed 中对应的旧插件。
- 源插件启用状态变化后，managed 状态同步变化。
- CCB hooks、权限和普通源配置仍然保留。
- 现有 Claude provider profile 与 runtime launch 测试保持通过。
