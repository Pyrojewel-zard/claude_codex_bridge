from __future__ import annotations

import subprocess

from terminal_runtime.herdr_backend_runtime.cli import HerdrCliRequestAdapter


def _adapter_with(monkeypatch, close_error: str):
    commands: list[list[str]] = []

    def run_fn(command, **kwargs):
        commands.append(command)
        joined = " ".join(command)
        if "workspace close" in joined:
            raise subprocess.CalledProcessError(1, command, stderr=close_error)
        raise AssertionError(f"unexpected command: {joined}")

    adapter = HerdrCliRequestAdapter(
        session_name="ccb-demo",
        herdr_executable="herdr",
        run_fn=run_fn,
        which_fn=lambda name: "herdr",
    )
    monkeypatch.setattr(
        adapter,
        "_logical_workspaces",
        lambda namespace_id, session_name: [{"workspace_id": "wB1"}],
    )
    # 测试环境没有真实 herdr server：让 _command 的 ensure-server 分支短路，
    # 使 server_not_running 重试耗尽后回落到 _destroy_namespace 的容忍逻辑。
    monkeypatch.setattr(adapter, "_start_server", lambda session_name, *, executable: None)
    return adapter, commands


def test_destroy_namespace_idempotent_when_workspace_not_found(monkeypatch) -> None:
    """workspace 已消失时 destroy/kill 应视为清理完成，不冒泡为失败。

    回归背景（2026-08-06-...-issue G4）：force kill 场景下 Herdr workspace
    已不存在，workspace close 返回 workspace_not_found，修复前会从
    _destroy_namespace 冒泡为 CalledProcessError 污染 prestart kill。
    """
    adapter, _ = _adapter_with(
        monkeypatch,
        close_error=(
            '{"error":{"code":"workspace_not_found","message":"workspace wB1 not found"},'
            '"id":"cli:workspace:close"}'
        ),
    )
    result = adapter("destroy_namespace", {"namespace_id": "w1"})
    assert result["status"] == "ok"
    assert result["closed_workspace_ids"] == []


def test_destroy_namespace_idempotent_when_server_not_running(monkeypatch) -> None:
    """Herdr server 未运行时 destroy 也应幂等（清理已不存在会话）。"""
    adapter, _ = _adapter_with(
        monkeypatch,
        close_error=(
            '{"error":{"code":"server_not_running",'
            '"message":"no herdr server is running at C:/tmp/herdr.sock; run `herdr session attach` '
            'to start or attach it"}}'
        ),
    )
    result = adapter("destroy_namespace", {"namespace_id": "w1"})
    assert result["status"] == "ok"
    assert result["closed_workspace_ids"] == []


def test_destroy_namespace_idempotent_when_logical_workspaces_server_not_running(monkeypatch) -> None:
    """_logical_workspaces 查询本身遇到 herdr server 未运行时也应幂等成功。

    回归背景（2026-08-06 采集暴露 lease_unmounted）：ccbd 启动/停止流程调用
    destroy_namespace，若 herdr 会话 server 未运行，_logical_workspaces 抛
    server_not_running（此前只容忍 workspace close 阶段的错误），导致 destroy
    失败、ccbd 启动中止。
    """
    from terminal_runtime.mux_backend_contract import MuxCommandErrorV2

    adapter = HerdrCliRequestAdapter(
        session_name="ccb-demo",
        herdr_executable="herdr",
        run_fn=lambda command, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected run")),
        which_fn=lambda name: "herdr",
    )

    def raise_server_not_running(namespace_id, session_name):
        raise MuxCommandErrorV2(
            category="command-failed",
            backend_impl="herdr",
            operation="destroy_namespace",
            detail=(
                '{"error":{"code":"server_not_running",'
                '"message":"no herdr server is running at C:/tmp/herdr.sock"}}'
            ),
        )

    monkeypatch.setattr(adapter, "_logical_workspaces", raise_server_not_running)
    result = adapter("destroy_namespace", {"namespace_id": "w1"})
    assert result["status"] == "ok"
    assert result["closed_workspace_ids"] == []


def test_destroy_namespace_raises_on_other_errors(monkeypatch) -> None:
    """非幂等类错误（如权限/会话名无效）仍应原样抛出。"""
    adapter, _ = _adapter_with(
        monkeypatch,
        close_error=(
            '{"error":{"code":"permission_denied","message":"access denied"},'
            '"id":"cli:workspace:close"}'
        ),
    )
    from terminal_runtime.mux_backend_contract import MuxCommandErrorV2

    try:
        adapter("destroy_namespace", {"namespace_id": "w1"})
    except MuxCommandErrorV2 as exc:
        assert exc.operation == "destroy_namespace"
        assert "permission_denied" in exc.detail
        return
    raise AssertionError("expected MuxCommandErrorV2 to propagate for non-idempotent error")
