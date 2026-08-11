from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.config_loader import load_project_config
from ccbd.app import CcbdApp
from ccbd.reload_plan import build_reload_dry_run_plan
from ccbd.services.project_namespace import ProjectNamespaceController
from ccbd.services.project_namespace_runtime import (
    assert_preserved_agent_panes,
    build_namespace_topology_plan,
    snapshot_preserved_agent_panes,
)
from ccbd.services.project_namespace_runtime.sidebar_helper import SIDEBAR_HELPER_ID_OPTION
from ccbd.services.project_namespace_state import ProjectNamespaceState, ProjectNamespaceStateStore
from storage.paths import PathLayout
from terminal_runtime.mux_backend_contract import make_capabilities, make_pane_ref


BASE_CONFIG = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""


ADD_WINDOW_CONFIG = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"
review = "agent3:codex, agent4:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""


ADD_TOOL_WINDOW_CONFIG = BASE_CONFIG + """
[tool_windows.files]
command = "ccb-workbench files"
label = "files"
"""


ADD_RICH_ALIAS_WINDOW_CONFIG = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"
review = "agent3:codex, rich"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""


@dataclass
class _PatchFakeBackend:
    socket_path: str | None = None
    sessions: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    pane_options: dict[str, dict[str, str]] = field(default_factory=dict)
    pane_titles: dict[str, str] = field(default_factory=dict)
    pane_widths: dict[str, int] = field(default_factory=dict)
    window_widths: dict[str, int] = field(default_factory=dict)
    session_options: dict[str, dict[str, str]] = field(default_factory=dict)
    split_calls: list[tuple[str, str, int]] = field(default_factory=list)
    tmux_calls: list[tuple[str, ...]] = field(default_factory=list)
    respawn_calls: list[tuple[str, str]] = field(default_factory=list)
    pane_counter: int = 0
    window_counter: int = 0

    def add_window(self, session_name: str, window_name: str) -> str:
        pane_id = self._alloc_pane()
        self.window_counter += 1
        self.sessions.setdefault(session_name, []).append(
            {
                'id': f'@{self.window_counter}',
                'name': window_name,
                'panes': [pane_id],
            }
        )
        return pane_id

    def split_pane(self, parent_pane_id: str, direction: str, percent: int, cmd=None, cwd=None) -> str:
        del cmd, cwd
        self.split_calls.append((parent_pane_id, direction, percent))
        for windows in self.sessions.values():
            for record in windows:
                panes = record['panes']
                if parent_pane_id in panes:
                    pane_id = self._alloc_pane()
                    panes.append(pane_id)
                    return pane_id
        raise RuntimeError(f'pane not found: {parent_pane_id}')

    def list_panes_by_user_options(self, expected: dict[str, str]) -> list[str]:
        matches = []
        for pane_id, options in self.pane_options.items():
            if all(str(options.get(key, '') or '') == str(value) for key, value in expected.items()):
                matches.append(pane_id)
        return matches

    def respawn_pane(self, pane_id: str, *, cmd: str, cwd: str | None = None, remain_on_exit: bool = True) -> None:
        del cwd, remain_on_exit
        self.respawn_calls.append((pane_id, cmd))

    def kill_pane(self, pane_id: str) -> None:
        self.tmux_calls.append(('kill-pane', '-t', pane_id))
        for windows in self.sessions.values():
            for record in windows:
                panes = record['panes']
                if pane_id in panes:
                    panes.remove(pane_id)
        self.pane_options.pop(pane_id, None)

    def set_pane_title(self, pane_id: str, title: str) -> None:
        self.pane_titles[pane_id] = title

    def set_pane_user_option(self, pane_id: str, name: str, value: str) -> None:
        self.pane_options.setdefault(pane_id, {})[name] = value

    def set_pane_style(self, pane_id: str, *, border_style=None, active_border_style=None) -> None:
        if border_style:
            self.set_pane_user_option(pane_id, 'pane-border-style', border_style)
        if active_border_style:
            self.set_pane_user_option(pane_id, 'pane-active-border-style', active_border_style)

    def _format_pane(self, session_name: str, record: dict[str, object], pane_id: str, fmt: str) -> str:
        options = self.pane_options.get(pane_id, {})
        values = {
            'pane_id': pane_id,
            'session_name': session_name,
            'window_id': str(record['id']),
            'window_name': str(record['name']),
            'pane_dead': '0',
            'pane_title': str(self.pane_titles.get(pane_id, '') or ''),
            'window_width': str(self.window_widths.get(str(record['name']), 120)),
            'pane_width': str(self.pane_widths.get(pane_id, 20)),
        }
        for option in (
            '@ccb_role',
            '@ccb_slot',
            '@ccb_window',
            '@ccb_sidebar_instance',
            '@ccb_sidebar_helper_id',
            '@ccb_project_id',
            '@ccb_managed_by',
            '@ccb_namespace_epoch',
            '@ccb_agent',
            '@ccb_label_style',
            '@ccb_border_style',
            '@ccb_active_border_style',
            '@ccb_session_id',
        ):
            values[option] = str(options.get(option, '') or '')
        rendered = fmt
        for key, value in values.items():
            rendered = rendered.replace(f'#{{{key}}}', value)
        return rendered

    def _tmux_run(self, args: list[str], *, check=False, capture=False, input_bytes=None, timeout=None):
        del check, capture, input_bytes, timeout
        self.tmux_calls.append(tuple(args))
        if args and args[0] == 'move-pane':
            source_pane = args[args.index('-s') + 1]
            target_pane = args[args.index('-t') + 1]
            source_record = None
            target_record = None
            for windows in self.sessions.values():
                for record in windows:
                    panes = record['panes']
                    if source_pane in panes:
                        source_record = record
                    if target_pane in panes:
                        target_record = record
            if source_record is None or target_record is None:
                return SimpleNamespace(returncode=1, stdout='', stderr='pane not found')
            source_record['panes'].remove(source_pane)
            target_panes = target_record['panes']
            target_index = target_panes.index(target_pane)
            target_panes.insert(target_index + 1, source_pane)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if args[:2] == ['has-session', '-t']:
            return SimpleNamespace(returncode=0 if args[2] in self.sessions else 1, stdout='', stderr='')
        if len(args) >= 7 and args[:2] == ['new-window', '-d']:
            session_name = args[args.index('-t') + 1]
            window_name = args[args.index('-n') + 1]
            self.add_window(session_name, window_name)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if len(args) >= 4 and args[:2] == ['list-windows', '-t']:
            session_name = args[2]
            rows = []
            for record in self.sessions.get(session_name, []):
                rows.append(f"{record['id']}\t{record['name']}\t0")
            return SimpleNamespace(returncode=0, stdout='\n'.join(rows), stderr='')
        if len(args) >= 4 and args[:2] == ['list-panes', '-a']:
            fmt = args[args.index('-F') + 1] if '-F' in args else '#{pane_id}'
            rows = []
            for session_name, windows in self.sessions.items():
                for record in windows:
                    for pane_id in record['panes']:
                        rows.append(self._format_pane(session_name, record, str(pane_id), fmt))
            return SimpleNamespace(returncode=0, stdout='\n'.join(rows), stderr='')
        if len(args) >= 4 and args[:2] == ['list-panes', '-t']:
            target = args[2]
            session_name, _, window_ref = target.partition(':')
            record = self._window(session_name, window_ref)
            panes = list(record['panes']) if record is not None else []
            return SimpleNamespace(returncode=0, stdout='\n'.join(str(item) for item in panes), stderr='')
        if len(args) >= 4 and args[:3] == ['select-layout', '-E', '-t']:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if len(args) >= 3 and args[:2] == ['select-window', '-t']:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if len(args) >= 5 and args[:3] == ['show-option', '-qv', '-t']:
            session_name = args[3]
            option = args[4]
            value = self.session_options.get(session_name, {}).get(option, '')
            return SimpleNamespace(returncode=0, stdout=f'{value}\n' if value else '', stderr='')
        if len(args) >= 5 and args[:2] == ['set-option', '-t']:
            session_name = args[2]
            option = args[3]
            value = args[4]
            self.session_options.setdefault(session_name, {})[option] = value
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if len(args) >= 5 and args[:3] == ['set-option', '-u', '-t']:
            session_name = args[3]
            option = args[4]
            self.session_options.setdefault(session_name, {}).pop(option, None)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if len(args) >= 5 and args[:2] == ['resize-pane', '-t'] and args[3] == '-x':
            self.pane_widths[args[2]] = int(args[4])
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if len(args) >= 5 and args[:3] == ['display-message', '-p', '-t']:
            pane_id = str(args[3])
            fmt = str(args[4])
            for session_name, windows in self.sessions.items():
                for record in windows:
                    if pane_id in record['panes']:
                        return SimpleNamespace(
                            returncode=0,
                            stdout=f'{self._format_pane(session_name, record, pane_id, fmt)}\n',
                            stderr='',
                        )
            return SimpleNamespace(returncode=1, stdout='', stderr='pane not found')
        if len(args) >= 3 and args[:2] == ['kill-window', '-t']:
            session_name, _, window_ref = args[2].partition(':')
            windows = self.sessions.get(session_name, [])
            removed_panes = [
                pane
                for record in windows
                if record['name'] == window_ref or record['id'] == window_ref
                for pane in record['panes']
            ]
            self.sessions[session_name] = [
                record for record in windows if record['name'] != window_ref and record['id'] != window_ref
            ]
            for pane in removed_panes:
                self.pane_options.pop(str(pane), None)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError(f'unexpected tmux command in additive patch test: {args}')

    def _window(self, session_name: str, window_ref: str) -> dict[str, object] | None:
        for record in self.sessions.get(session_name, []):
            if record['name'] == window_ref or record['id'] == window_ref:
                return record
        return None

    def _alloc_pane(self) -> str:
        self.pane_counter += 1
        return f'%{self.pane_counter}'


class _PatchFakeHerdrBackend:
    backend_impl = 'herdr'

    def __init__(self, *, session_name: str = 'ccb-herdr', support_reflow: bool = True) -> None:
        self.session_name = session_name
        self.calls: list[tuple[str, object]] = []
        self.windows: dict[str, dict[str, object]] = {}
        self.window_panes: dict[str, list[str]] = {}
        self.pane_options: dict[str, dict[str, str]] = {}
        self.pane_refs: dict[str, dict[str, object]] = {}
        self.pane_counter = 0
        if not support_reflow:
            self.reflow_window = None

    def capabilities(self) -> dict[str, object]:
        return make_capabilities(
            backend_impl='herdr',
            command_status={
                'session_attach': 'supported',
                'workspace_list': 'supported',
                'workspace_create': 'supported',
                'workspace_focus': 'supported',
                'workspace_metadata': 'supported',
                'workspace_close': 'supported',
                'pane_list': 'supported',
                'pane_spawn': 'supported',
                'pane_split': 'supported',
                'pane_run': 'supported',
                'pane_metadata': 'supported',
                'send_input': 'supported',
                'read_output': 'supported',
                'kill_pane': 'supported',
            },
            semantic_status={
                'session_attach': 'supported',
                'workspace_list': 'supported',
                'workspace_create': 'supported',
                'workspace_focus': 'supported',
                'workspace_metadata': 'supported',
                'workspace_close': 'supported',
                'pane_list': 'supported',
                'pane_spawn': 'supported',
                'pane_split': 'supported',
                'pane_run': 'supported',
                'pane_metadata': 'supported',
                'send_input': 'supported',
                'read_output': 'supported',
                'kill_pane': 'supported',
            },
        )

    def namespace_alive(self, namespace: dict[str, object]) -> bool:
        self.calls.append(('namespace_alive', namespace))
        return True

    def list_windows(self, namespace: dict[str, object]) -> list[dict[str, object]]:
        self.calls.append(('list_windows', namespace))
        return list(self.windows.values())

    def create_window(
        self,
        namespace: dict[str, object],
        *,
        window_name: str,
        cwd: str,
        select: bool,
    ) -> dict[str, object]:
        self.calls.append(('create_window', {'namespace': namespace, 'window_name': window_name, 'cwd': cwd, 'select': select}))
        pane_id = self.add_window(str(namespace['session_name']), window_name)
        del pane_id
        return self.windows[window_name]

    def ensure_window(
        self,
        namespace: dict[str, object],
        *,
        window_name: str,
        cwd: str,
        select: bool,
    ) -> dict[str, object]:
        if window_name not in self.windows:
            return self.create_window(namespace, window_name=window_name, cwd=cwd, select=select)
        self.calls.append(('ensure_window', {'namespace': namespace, 'window_name': window_name, 'cwd': cwd, 'select': select}))
        return self.windows[window_name]

    def window_root_pane(self, namespace: dict[str, object], *, window_name: str) -> dict[str, object]:
        self.calls.append(('window_root_pane', {'namespace': namespace, 'window_name': window_name}))
        pane_id = self.window_panes[window_name][0]
        return dict(self.pane_refs[pane_id])

    def split_pane(
        self,
        pane: dict[str, object],
        *,
        direction: str,
        percent: int,
        command: list[str],
        cwd: str,
        env: dict[str, str],
        title: str,
    ) -> dict[str, object]:
        self.calls.append(('split_pane', {'pane': pane, 'direction': direction, 'percent': percent, 'command': command, 'cwd': cwd, 'env': env, 'title': title}))
        window_name = self._window_for_pane(str(pane['pane_id']))
        child = self._alloc_pane(str(pane['session_name']), window_name)
        panes = self.window_panes[window_name]
        index = panes.index(str(pane['pane_id']))
        panes.insert(index + 1, child['pane_id'])
        return child

    def respawn_pane(self, pane: dict[str, object], *, command: list[str], cwd: str, env: dict[str, str]) -> None:
        self.calls.append(('respawn_pane', {'pane': pane, 'command': command, 'cwd': cwd, 'env': env}))

    def set_pane_identity(self, pane: dict[str, object], **kwargs) -> None:
        self.calls.append(('set_pane_identity', {'pane': pane, **kwargs}))
        pane_id = str(pane['pane_id'])
        self.pane_options.setdefault(pane_id, {}).update(
            {
                '@ccb_project_id': str(kwargs.get('project_id') or ''),
                '@ccb_role': str(kwargs.get('role') or ''),
                '@ccb_slot': str(kwargs.get('slot_key') or ''),
                '@ccb_window': str(kwargs.get('window_name') or ''),
                '@ccb_managed_by': str(kwargs.get('managed_by') or ''),
                '@ccb_namespace_epoch': str(kwargs.get('namespace_epoch') or ''),
            }
        )

    def move_pane(self, source: dict[str, object], anchor: dict[str, object], *, direction: str) -> None:
        self.calls.append(('move_pane', {'source': source, 'anchor': anchor, 'direction': direction}))
        source_id = str(source['pane_id'])
        anchor_id = str(anchor['pane_id'])
        source_window = self._window_for_pane(source_id)
        target_window = self._window_for_pane(anchor_id)
        self.window_panes[source_window].remove(source_id)
        target_panes = self.window_panes[target_window]
        target_panes.insert(target_panes.index(anchor_id) + 1, source_id)
        self.pane_refs[source_id]['window_name'] = target_window

    def kill_pane(self, pane: dict[str, object]) -> None:
        self.calls.append(('kill_pane', pane))
        pane_id = str(pane['pane_id'])
        for panes in self.window_panes.values():
            if pane_id in panes:
                panes.remove(pane_id)
                break
        self.pane_options.pop(pane_id, None)
        self.pane_refs.pop(pane_id, None)

    def kill_window(self, namespace: dict[str, object], *, window_id: str | None, target: str) -> None:
        self.calls.append(('kill_window', {'namespace': namespace, 'window_id': window_id, 'target': target}))
        window_name = str(window_id or target.rsplit(':', 1)[-1])
        for pane_id in self.window_panes.pop(window_name, []):
            self.pane_options.pop(pane_id, None)
            self.pane_refs.pop(pane_id, None)
        self.windows.pop(window_name, None)

    def reflow_window(
        self,
        namespace: dict[str, object],
        *,
        window_name: str,
        window_id: str | None,
        target: str,
        prefer_topology_layout: bool,
    ) -> None:
        self.calls.append(('reflow_window', {'namespace': namespace, 'window_name': window_name, 'window_id': window_id, 'target': target, 'prefer_topology_layout': prefer_topology_layout}))

    def list_panes_by_user_options(self, expected: dict[str, str]) -> list[str]:
        matches = []
        for pane_id, options in self.pane_options.items():
            if all(str(options.get(key, '') or '') == str(value) for key, value in expected.items()):
                matches.append(pane_id)
        return matches

    def describe_pane(self, pane_id: str, *, user_options: tuple[str, ...]) -> dict[str, object]:
        window_name = self._window_for_pane(pane_id)
        options = self.pane_options.get(pane_id, {})
        return {
            'pane_id': pane_id,
            'session_name': self.session_name,
            'window_id': self.windows[window_name]['window_id'],
            'window_name': window_name,
            'pane_dead': '0',
            **{option: options.get(option, '') for option in user_options},
        }

    def add_window(self, session_name: str, window_name: str) -> str:
        pane = self._alloc_pane(session_name, window_name)
        self.windows[window_name] = {
            'window_id': window_name,
            'window_name': window_name,
            'active': False,
        }
        self.window_panes[window_name] = [pane['pane_id']]
        return str(pane['pane_id'])

    def _alloc_pane(self, session_name: str, window_name: str) -> dict[str, object]:
        self.pane_counter += 1
        pane = make_pane_ref(
            backend_impl='herdr',
            pane_id=f'herdr-pane-{self.pane_counter}',
            session_name=session_name,
            window_name=window_name,
        )
        self.pane_refs[pane['pane_id']] = pane
        return pane

    def _window_for_pane(self, pane_id: str) -> str:
        for window_name, panes in self.window_panes.items():
            if pane_id in panes:
                return window_name
        raise RuntimeError(f'pane not found: {pane_id}')


class _MemoryProjectNamespaceStateStore:
    def __init__(self, state: ProjectNamespaceState | None = None) -> None:
        self.state = state

    def load(self) -> ProjectNamespaceState | None:
        return self.state

    def save(self, state: ProjectNamespaceState) -> None:
        self.state = state


def test_apply_add_window_creates_only_new_window_sidebar_and_agent_panes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv('CCB_TMUX_THEME_PROFILE', raising=False)
    current = _load_config(tmp_path / 'current', BASE_CONFIG)
    new = _load_config(tmp_path / 'new', ADD_WINDOW_CONFIG)
    project_root = _project(tmp_path / 'repo', BASE_CONFIG)
    layout = PathLayout(project_root)
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(
        layout,
        'proj-1',
        clock=lambda: '2026-05-29T00:00:00Z',
        backend_factory=lambda socket_path=None: backend,
    )
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(
        current,
        new,
        project_id='proj-1',
        current_namespace=controller.load(),
    )

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ('review',)
    assert result.agent_panes == {'agent3': '%4', 'agent4': '%5'}
    assert result.sidebar_panes == {'review': '%3'}
    assert backend.pane_options['%3'][SIDEBAR_HELPER_ID_OPTION].startswith('sha256:')
    assert result.preserved_before == {'agent1': '%1', 'agent2': '%2'}
    assert result.preserved_after == {'agent1': '%1', 'agent2': '%2'}
    assert result.diagnostics['graph_published'] is False
    assert result.diagnostics['runtime_authority_written'] is False
    assert result.diagnostics['lease_or_lifecycle_written'] is False
    assert ('new-window', '-d', '-t', layout.ccbd_tmux_session_name, '-n', 'review') in {
        call[:6] for call in backend.tmux_calls
    }
    assert all('kill' not in ' '.join(call) for call in backend.tmux_calls)
    assert backend.split_calls == [('%3', 'right', 85), ('%4', 'bottom', 50)]
    assert backend.respawn_calls[0][0] == '%3'
    assert backend.respawn_calls[0][1].startswith('CCB_SIDEBAR_THEME_PROFILE=default ')
    assert '--theme' not in backend.respawn_calls[0][1]
    assert backend.pane_options['%3']['@ccb_role'] == 'sidebar'
    assert backend.pane_options['%3']['@ccb_slot'] == 'sidebar:review'
    assert backend.pane_options['%3']['@ccb_managed_by'] == 'ccbd'
    assert backend.pane_options['%4']['@ccb_slot'] == 'agent3'
    assert backend.pane_options['%5']['@ccb_slot'] == 'agent4'
    assert {backend.pane_options[pane]['@ccb_window'] for pane in ('%3', '%4', '%5')} == {'review'}
    assert ProjectNamespaceStateStore(layout).load().layout_signature is None


def test_apply_herdr_append_agent_uses_v2_namespace_ref_without_tmux_runner(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-herdr-add-agent', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-herdr-add-agent',
        BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex, agent2:claude, agent3:codex'),
    )
    layout = PathLayout(_project(tmp_path / 'repo-herdr-add-agent', BASE_CONFIG))
    backend = _PatchFakeHerdrBackend()
    first_pane = backend.add_window('ccb-herdr', 'main')
    second = backend._alloc_pane('ccb-herdr', 'main')
    backend.window_panes['main'].append(str(second['pane_id']))
    _seed_agent_pane(backend, first_pane, project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, str(second['pane_id']), project_id='proj-1', window='main', agent='agent2')
    controller = ProjectNamespaceController(
        layout,
        'proj-1',
        backend_factory=lambda socket_path=None: backend,
        state_store=_MemoryProjectNamespaceStateStore(_herdr_namespace_state(project_id='proj-1')),
    )
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.agent_panes == {'agent3': 'herdr-pane-3'}
    assert result.reflowed_windows == ('main',)
    assert not hasattr(backend, '_tmux_run')
    call_names = [call[0] for call in backend.calls]
    assert 'namespace_alive' in call_names
    assert 'split_pane' in call_names
    assert 'set_pane_identity' in call_names
    assert 'reflow_window' in call_names
    assert call_names.count('reflow_window') == 1
    assert any(
        isinstance(call[1], dict) and call[1].get('restore_token') == 'restore-secret'
        for call in backend.calls
        if call[0] == 'namespace_alive'
    )


def test_apply_herdr_remove_agent_uses_v2_kill_pane_and_reflow(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-herdr-remove-agent', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-herdr-remove-agent',
        BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex'),
    )
    layout = PathLayout(_project(tmp_path / 'repo-herdr-remove-agent', BASE_CONFIG))
    backend = _PatchFakeHerdrBackend()
    first_pane = backend.add_window('ccb-herdr', 'main')
    second = backend._alloc_pane('ccb-herdr', 'main')
    backend.window_panes['main'].append(str(second['pane_id']))
    _seed_agent_pane(backend, first_pane, project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, str(second['pane_id']), project_id='proj-1', window='main', agent='agent2')
    controller = ProjectNamespaceController(
        layout,
        'proj-1',
        backend_factory=lambda socket_path=None: backend,
        state_store=_MemoryProjectNamespaceStateStore(_herdr_namespace_state(project_id='proj-1')),
    )
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.removed_agents == {'agent2': 'herdr-pane-2'}
    assert result.removed_panes == ('herdr-pane-2',)
    assert result.reflowed_windows == ('main',)
    assert 'kill_pane' in [call[0] for call in backend.calls]
    assert 'reflow_window' in [call[0] for call in backend.calls]


def test_apply_herdr_move_agent_uses_v2_move_pane_and_identity(tmp_path: Path, monkeypatch) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"
review = "agent3:codex"
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex"
review = "agent3:codex, agent2:claude"
"""
    current = _load_config(tmp_path / 'current-herdr-move-agent', current_text)
    new = _load_config(tmp_path / 'new-herdr-move-agent', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-herdr-move-agent', current_text))
    backend = _PatchFakeHerdrBackend()
    first_pane = backend.add_window('ccb-herdr', 'main')
    second = backend._alloc_pane('ccb-herdr', 'main')
    backend.window_panes['main'].append(str(second['pane_id']))
    review_pane = backend.add_window('ccb-herdr', 'review')
    _seed_agent_pane(backend, first_pane, project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, str(second['pane_id']), project_id='proj-1', window='main', agent='agent2')
    _seed_agent_pane(backend, review_pane, project_id='proj-1', window='review', agent='agent3')
    controller = ProjectNamespaceController(
        layout,
        'proj-1',
        backend_factory=lambda socket_path=None: backend,
        state_store=_MemoryProjectNamespaceStateStore(_herdr_namespace_state(project_id='proj-1')),
    )
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.moved_agents == {'agent2': 'herdr-pane-2'}
    assert result.moved_agent_windows == {'agent2': 'review'}
    assert backend.window_panes['main'] == ['herdr-pane-1']
    assert backend.window_panes['review'] == ['herdr-pane-3', 'herdr-pane-2']
    assert 'move_pane' in [call[0] for call in backend.calls]
    assert backend.pane_options['herdr-pane-2']['@ccb_window'] == 'review'


def test_apply_herdr_reload_missing_reflow_primitive_fails_closed(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-herdr-missing-reflow', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-herdr-missing-reflow',
        BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex, agent2:claude, agent3:codex'),
    )
    layout = PathLayout(_project(tmp_path / 'repo-herdr-missing-reflow', BASE_CONFIG))
    backend = _PatchFakeHerdrBackend(support_reflow=False)
    first_pane = backend.add_window('ccb-herdr', 'main')
    second = backend._alloc_pane('ccb-herdr', 'main')
    backend.window_panes['main'].append(str(second['pane_id']))
    _seed_agent_pane(backend, first_pane, project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, str(second['pane_id']), project_id='proj-1', window='main', agent='agent2')
    controller = ProjectNamespaceController(
        layout,
        'proj-1',
        backend_factory=lambda socket_path=None: backend,
        state_store=_MemoryProjectNamespaceStateStore(_herdr_namespace_state(project_id='proj-1')),
    )
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'failed'
    assert result.partial is True
    assert result.diagnostics['reason'] == 'namespace_patch_failed'
    assert result.diagnostics['error_type'] == 'MuxCommandErrorV2'
    assert result.diagnostics['graph_published'] is False
    assert result.diagnostics['runtime_authority_written'] is False
    assert result.diagnostics['lease_or_lifecycle_written'] is False


def test_apply_add_window_materializes_rich_alias_as_tool_pane(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-rich-alias', BASE_CONFIG)
    new = _load_config(tmp_path / 'new-rich-alias', ADD_RICH_ALIAS_WINDOW_CONFIG)
    project_root = _project(tmp_path / 'repo-rich-alias', BASE_CONFIG)
    layout = PathLayout(project_root)
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(
        layout,
        'proj-1',
        clock=lambda: '2026-05-29T00:00:00Z',
        backend_factory=lambda socket_path=None: backend,
    )
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(
        current,
        new,
        project_id='proj-1',
        current_namespace=controller.load(),
    )

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ('review',)
    assert result.agent_panes == {'agent3': '%4'}
    assert result.tool_panes == {'rich': '%5'}
    assert backend.respawn_calls[-1] == ('%5', 'CCB_WORKBENCH_PROFILE=rich CCB_WORKBENCH_FORCE_RICH=1 ccb-workbench files')
    assert backend.pane_options['%5']['@ccb_role'] == 'tool'
    assert backend.pane_options['%5']['@ccb_slot'] == 'tool:rich'
    assert backend.pane_options['%5']['@ccb_window'] == 'review'
    assert 'rich' not in result.agent_panes
    assert result.preserved_after == {'agent1': '%1', 'agent2': '%2'}


def test_preserved_snapshot_and_assertion_use_fake_identity_data(tmp_path: Path) -> None:
    current = _load_config(tmp_path / 'current-preserved', BASE_CONFIG)
    layout = PathLayout(_project(tmp_path / 'repo-preserved', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    first_pane = backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, first_pane, project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    namespace = SimpleNamespace(
        namespace_epoch=3,
        tmux_session_name=layout.ccbd_tmux_session_name,
    )

    snapshot = snapshot_preserved_agent_panes(
        controller,
        SimpleNamespace(
            backend=backend,
            current=namespace,
            desired_session_name=namespace.tmux_session_name,
        ),
        topology_plan=build_namespace_topology_plan(current),
        agents=('agent1', 'agent2', 'agent-missing'),
    )

    assert snapshot == {'agent1': '%1', 'agent2': '%2'}
    assert_preserved_agent_panes(snapshot, {'agent1': '%1', 'agent2': '%2'})
    with pytest.raises(RuntimeError, match='changed=agent2'):
        assert_preserved_agent_panes(snapshot, {'agent1': '%1', 'agent2': '%99'})


def test_apply_add_window_failure_returns_partial_without_side_effect_contract(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-fail', BASE_CONFIG)
    new = _load_config(tmp_path / 'new-fail', ADD_WINDOW_CONFIG)
    project_root = _project(tmp_path / 'repo-fail', BASE_CONFIG)
    layout = PathLayout(project_root)

    class _FailingBackend(_PatchFakeBackend):
        def split_pane(self, parent_pane_id: str, direction: str, percent: int, cmd=None, cwd=None) -> str:
            raise RuntimeError('split failed')

    backend = _FailingBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'failed'
    assert result.partial is True
    assert result.created_windows == ('review',)
    assert result.diagnostics['graph_published'] is False
    assert result.diagnostics['runtime_authority_written'] is False
    assert result.diagnostics['lease_or_lifecycle_written'] is False
    assert ProjectNamespaceStateStore(layout).load().layout_signature is None


def test_apply_add_window_fails_when_preserved_agent_pane_changes(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-preserve-change', BASE_CONFIG)
    new = _load_config(tmp_path / 'new-preserve-change', ADD_WINDOW_CONFIG)
    project_root = _project(tmp_path / 'repo-preserve-change', BASE_CONFIG)
    layout = PathLayout(project_root)

    class _MovingBackend(_PatchFakeBackend):
        mutate_preserved_on_review_create = False

        def add_window(self, session_name: str, window_name: str) -> str:
            pane_id = super().add_window(session_name, window_name)
            if window_name == 'review' and self.mutate_preserved_on_review_create:
                self.pane_options.pop('%2', None)
                for record in self.sessions.get(session_name, []):
                    if '%2' in record['panes']:
                        record['panes'][record['panes'].index('%2')] = '%99'
                _seed_agent_pane(self, '%99', project_id='proj-1', window='main', agent='agent2')
            return pane_id

    backend = _MovingBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    backend.mutate_preserved_on_review_create = True
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'failed'
    assert result.diagnostics['reason'] == 'preserved_agent_pane_changed'
    assert result.preserved_before == {'agent1': '%1', 'agent2': '%2'}
    assert result.preserved_after == {'agent1': '%1', 'agent2': '%99'}
    assert result.diagnostics['graph_published'] is False
    assert result.diagnostics['runtime_authority_written'] is False
    assert result.diagnostics['lease_or_lifecycle_written'] is False


def test_apply_append_add_agent_creates_only_new_agent_pane(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-add-agent', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-add-agent',
        BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex, (agent2:claude; agent3:codex)'),
    )
    layout = PathLayout(_project(tmp_path / 'repo-add-agent', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ()
    assert result.created_panes == ('%3',)
    assert result.agent_panes == {'agent3': '%3'}
    assert result.reflowed_windows == ('main',)
    assert result.reflow_errors == {}
    assert result.sidebar_panes == {}
    assert result.preserved_before == {'agent1': '%1', 'agent2': '%2'}
    assert result.preserved_after == {'agent1': '%1', 'agent2': '%2'}
    assert backend.split_calls == [('%2', 'right', 50)]
    assert ('select-layout', '-E', '-t', f'{layout.ccbd_tmux_session_name}:main') in backend.tmux_calls
    assert backend.pane_options['%3']['@ccb_project_id'] == 'proj-1'
    assert backend.pane_options['%3']['@ccb_role'] == 'agent'
    assert backend.pane_options['%3']['@ccb_slot'] == 'agent3'
    assert backend.pane_options['%3']['@ccb_window'] == 'main'
    assert backend.pane_options['%3']['@ccb_namespace_epoch'] == '3'
    assert backend.pane_options['%3']['@ccb_managed_by'] == 'ccbd'
    assert result.diagnostics['graph_published'] is False
    assert result.diagnostics['runtime_authority_written'] is False
    assert result.diagnostics['lease_or_lifecycle_written'] is False


def test_apply_append_multiple_agents_reflows_between_splits_in_narrow_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = _load_config(tmp_path / 'current-narrow-append', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-narrow-append',
        BASE_CONFIG.replace(
            'agent1:codex, agent2:claude',
            'agent1:codex, agent2:claude, agent3:codex, agent4:claude, agent5:codex, agent6:claude',
        ),
    )
    layout = PathLayout(_project(tmp_path / 'repo-narrow-append', BASE_CONFIG))

    class NarrowAppendBackend(_PatchFakeBackend):
        splits_without_reflow = 0

        def split_pane(self, parent_pane_id: str, direction: str, percent: int, cmd=None, cwd=None) -> str:
            if self.splits_without_reflow >= 1:
                raise RuntimeError('no space for new pane')
            pane_id = super().split_pane(parent_pane_id, direction, percent, cmd=cmd, cwd=cwd)
            self.splits_without_reflow += 1
            return pane_id

        def _tmux_run(self, args: list[str], *, check=False, capture=False, input_bytes=None, timeout=None):
            completed = super()._tmux_run(
                args,
                check=check,
                capture=capture,
                input_bytes=input_bytes,
                timeout=timeout,
            )
            if args[:2] == ['select-layout', '-E']:
                self.splits_without_reflow = 0
            return completed

    backend = NarrowAppendBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.agent_panes == {
        'agent3': '%3',
        'agent4': '%4',
        'agent5': '%5',
        'agent6': '%6',
    }
    assert [call[0] for call in backend.split_calls] == ['%2', '%3', '%4', '%5']
    assert {call[1] for call in backend.split_calls} <= {'right', 'bottom'}
    assert [call[2] for call in backend.split_calls] == [50, 50, 50, 50]
    interim_reflows = [call for call in backend.tmux_calls if call[:2] == ('select-layout', '-E')]
    assert len(interim_reflows) >= 3


def test_apply_remove_agent_kills_only_removed_agent_pane(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-remove-agent', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-remove-agent',
        BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex'),
    )
    layout = PathLayout(_project(tmp_path / 'repo-remove-agent', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.removed_agents == {'agent2': '%2'}
    assert result.removed_panes == ('%2',)
    assert result.reflowed_windows == ('main',)
    assert result.reflow_errors == {}
    assert result.preserved_before == {'agent1': '%1'}
    assert result.preserved_after == {'agent1': '%1'}
    assert ('kill-pane', '-t', '%2') in backend.tmux_calls
    assert ('select-layout', '-E', '-t', f'{layout.ccbd_tmux_session_name}:main') in backend.tmux_calls
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1']
    assert '%2' not in backend.pane_options
    assert backend.pane_options['%1']['@ccb_slot'] == 'agent1'


def test_apply_remove_multiple_agents_kills_removed_panes_and_reflows(tmp_path: Path, monkeypatch) -> None:
    current_text = BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex, agent2:claude, agent3:codex')
    new_text = BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex')
    current = _load_config(tmp_path / 'current-remove-multiple-agents', current_text)
    new = _load_config(tmp_path / 'new-remove-multiple-agents', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-remove-multiple-agents', current_text))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].extend(['%2', '%3'])
    backend.pane_counter = 3
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _seed_agent_pane(backend, '%3', project_id='proj-1', window='main', agent='agent3')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.removed_agents == {'agent2': '%2', 'agent3': '%3'}
    assert result.removed_panes == ('%2', '%3')
    assert result.reflowed_windows == ('main',)
    assert result.reflow_errors == {}
    assert result.preserved_before == {'agent1': '%1'}
    assert result.preserved_after == {'agent1': '%1'}
    assert ('kill-pane', '-t', '%2') in backend.tmux_calls
    assert ('kill-pane', '-t', '%3') in backend.tmux_calls
    assert ('select-layout', '-E', '-t', f'{layout.ccbd_tmux_session_name}:main') in backend.tmux_calls
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1']
    assert '%2' not in backend.pane_options
    assert '%3' not in backend.pane_options
    assert backend.pane_options['%1']['@ccb_slot'] == 'agent1'


def test_apply_remove_agent_reflows_compact_workspace_by_namespace_window_id(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-remove-agent-compact', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-remove-agent-compact',
        BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex'),
    )
    layout = PathLayout(_project(tmp_path / 'repo-remove-agent-compact', BASE_CONFIG))

    class _StrictSelectBackend(_PatchFakeBackend):
        def _tmux_run(self, args: list[str], **kwargs):
            if len(args) >= 4 and args[:3] == ['select-layout', '-E', '-t']:
                session_name, _, window_ref = args[3].partition(':')
                if self._window(session_name, window_ref) is None:
                    return SimpleNamespace(returncode=1, stdout='', stderr=f"can't find window: {window_ref}")
            return super()._tmux_run(args, **kwargs)

    backend = _StrictSelectBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'ccb')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1', workspace_window_name='ccb', workspace_window_id='@1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.removed_agents == {'agent2': '%2'}
    assert result.reflowed_windows == ('main',)
    assert result.reflow_errors == {}
    assert ('select-layout', '-E', '-t', f'{layout.ccbd_tmux_session_name}:@1') in backend.tmux_calls
    assert ('select-layout', '-E', '-t', f'{layout.ccbd_tmux_session_name}:main') not in backend.tmux_calls
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1']


def test_apply_remove_agent_reflows_window_and_restores_sidebar_width(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-remove-agent-sidebar', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-remove-agent-sidebar',
        BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex'),
    )
    layout = PathLayout(_project(tmp_path / 'repo-remove-agent-sidebar', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] = ['%1', '%2', '%3']
    backend.pane_counter = 3
    backend.window_widths['main'] = 120
    backend.pane_widths.update({'%1': 60, '%2': 30, '%3': 30})
    _seed_sidebar_pane(backend, '%1', project_id='proj-1', window='main')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%3', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.removed_agents == {'agent2': '%3'}
    assert result.removed_panes == ('%3',)
    assert result.reflowed_windows == ('main',)
    assert result.reflow_errors == {}
    assert ('select-layout', '-E', '-t', f'{layout.ccbd_tmux_session_name}:main') in backend.tmux_calls
    assert ['resize-pane', '-t', '%1', '-x', '18'] in [list(call) for call in backend.tmux_calls]
    assert backend.pane_widths['%1'] == 18
    assert backend.pane_options['%1']['@ccb_slot'] == 'sidebar:main'
    assert backend.pane_options['%2']['@ccb_slot'] == 'agent1'
    assert '%3' not in backend.pane_options


def test_apply_trailing_add_agent_creates_new_agent_pane(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-add-agent-trailing', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-add-agent-trailing',
        BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex, agent2:claude, agent3:codex'),
    )
    layout = PathLayout(_project(tmp_path / 'repo-add-agent-trailing', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ()
    assert result.created_panes == ('%3',)
    assert result.agent_panes == {'agent3': '%3'}
    assert result.reflowed_windows == ('main',)
    assert result.reflow_errors == {}
    assert backend.split_calls == [('%2', 'bottom', 50)]
    assert ('select-layout', '-E', '-t', f'{layout.ccbd_tmux_session_name}:main') in backend.tmux_calls
    assert backend.pane_options['%3']['@ccb_slot'] == 'agent3'
    assert backend.pane_options['%3']['@ccb_window'] == 'main'


def test_apply_move_agent_reuses_existing_pane_between_existing_windows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"
review = "agent3:codex"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex"
review = "agent3:codex, agent2:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    current = _load_config(tmp_path / 'current-move-agent', current_text)
    new = _load_config(tmp_path / 'new-move-agent', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-move-agent', current_text))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    review_pane = backend.add_window(layout.ccbd_tmux_session_name, 'review')
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _seed_agent_pane(backend, review_pane, project_id='proj-1', window='review', agent='agent3')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ()
    assert result.created_panes == ()
    assert result.agent_panes == {}
    assert result.removed_agents == {}
    assert result.removed_panes == ()
    assert result.moved_agents == {'agent2': '%2'}
    assert result.moved_agent_windows == {'agent2': 'review'}
    assert result.reflowed_windows == ('main', 'review')
    assert result.reflow_errors == {}
    assert result.preserved_before == {'agent1': '%1', 'agent2': '%2', 'agent3': review_pane}
    assert result.preserved_after == {'agent1': '%1', 'agent2': '%2', 'agent3': review_pane}
    assert ('move-pane', '-v', '-s', '%2', '-t', review_pane) in backend.tmux_calls
    assert ('select-layout', '-E', '-t', f'{layout.ccbd_tmux_session_name}:main') in backend.tmux_calls
    assert ('select-layout', '-E', '-t', f'{layout.ccbd_tmux_session_name}:review') in backend.tmux_calls
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1']
    assert backend.sessions[layout.ccbd_tmux_session_name][1]['panes'] == [review_pane, '%2']
    assert backend.pane_options['%2']['@ccb_slot'] == 'agent2'
    assert backend.pane_options['%2']['@ccb_window'] == 'review'
    assert backend.pane_options['%2']['@ccb_namespace_epoch'] == '3'


def test_apply_moves_multiple_agents_from_same_source_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex"
review = "helper1:codex, helper2:claude, helper3:codex"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, helper1:codex, helper2:claude"
review = "helper3:codex"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    current = _load_config(tmp_path / 'current-move-multiple-agents', current_text)
    new = _load_config(tmp_path / 'new-move-multiple-agents', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-move-multiple-agents', current_text))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    review_first_pane = backend.add_window(layout.ccbd_tmux_session_name, 'review')
    backend.sessions[layout.ccbd_tmux_session_name][1]['panes'].extend(['%3', '%4'])
    backend.pane_counter = 4
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, review_first_pane, project_id='proj-1', window='review', agent='helper1')
    _seed_agent_pane(backend, '%3', project_id='proj-1', window='review', agent='helper2')
    _seed_agent_pane(backend, '%4', project_id='proj-1', window='review', agent='helper3')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ()
    assert result.created_panes == ()
    assert result.agent_panes == {}
    assert result.removed_agents == {}
    assert result.removed_windows == ()
    assert result.removed_panes == ()
    assert result.moved_agents == {'helper1': review_first_pane, 'helper2': '%3'}
    assert result.moved_agent_windows == {'helper1': 'main', 'helper2': 'main'}
    assert result.reflowed_windows == ('main', 'review')
    assert result.reflow_errors == {}
    assert result.preserved_before == {
        'agent1': '%1',
        'helper1': review_first_pane,
        'helper2': '%3',
        'helper3': '%4',
    }
    assert result.preserved_after == {
        'agent1': '%1',
        'helper1': review_first_pane,
        'helper2': '%3',
        'helper3': '%4',
    }
    assert ('move-pane', '-v', '-s', review_first_pane, '-t', '%1') in backend.tmux_calls
    assert ('move-pane', '-v', '-s', '%3', '-t', review_first_pane) in backend.tmux_calls
    assert ('kill-window', '-t', f'{layout.ccbd_tmux_session_name}:review') not in backend.tmux_calls
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1', review_first_pane, '%3']
    assert backend.sessions[layout.ccbd_tmux_session_name][1]['panes'] == ['%4']
    assert backend.pane_options[review_first_pane]['@ccb_slot'] == 'helper1'
    assert backend.pane_options[review_first_pane]['@ccb_window'] == 'main'
    assert backend.pane_options[review_first_pane]['@ccb_namespace_epoch'] == '3'
    assert backend.pane_options['%3']['@ccb_slot'] == 'helper2'
    assert backend.pane_options['%3']['@ccb_window'] == 'main'
    assert backend.pane_options['%3']['@ccb_namespace_epoch'] == '3'
    assert backend.pane_options['%4']['@ccb_slot'] == 'helper3'
    assert backend.pane_options['%4']['@ccb_window'] == 'review'


def test_apply_moves_all_source_agents_and_removes_source_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "main:codex"
review = "zeta:codex, alpha:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "main:codex, zeta:codex, alpha:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    current = _load_config(tmp_path / 'current-move-all-source-agents', current_text)
    new = _load_config(tmp_path / 'new-move-all-source-agents', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-move-all-source-agents', current_text))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    review_sidebar = backend.add_window(layout.ccbd_tmux_session_name, 'review')
    backend.sessions[layout.ccbd_tmux_session_name][1]['panes'].extend(['%3', '%4'])
    backend.pane_counter = 4
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='main')
    _seed_sidebar_pane(backend, review_sidebar, project_id='proj-1', window='review')
    _seed_agent_pane(backend, '%3', project_id='proj-1', window='review', agent='zeta')
    _seed_agent_pane(backend, '%4', project_id='proj-1', window='review', agent='alpha')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch, allow_kill_window=True)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ()
    assert result.created_panes == ()
    assert result.agent_panes == {}
    assert result.removed_agents == {}
    assert result.removed_panes == ()
    assert result.removed_windows == ('review',)
    assert result.moved_agents == {'zeta': '%3', 'alpha': '%4'}
    assert result.moved_agent_windows == {'zeta': 'main', 'alpha': 'main'}
    assert result.reflowed_windows == ('main',)
    assert result.reflow_errors == {}
    assert result.preserved_before == {'alpha': '%4', 'main': '%1', 'zeta': '%3'}
    assert result.preserved_after == {'alpha': '%4', 'main': '%1', 'zeta': '%3'}
    assert ('move-pane', '-v', '-s', '%3', '-t', '%1') in backend.tmux_calls
    assert ('move-pane', '-v', '-s', '%4', '-t', '%3') in backend.tmux_calls
    assert ('kill-window', '-t', f'{layout.ccbd_tmux_session_name}:review') in backend.tmux_calls
    assert [record['name'] for record in backend.sessions[layout.ccbd_tmux_session_name]] == ['main']
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1', '%3', '%4']
    assert backend.pane_options['%3']['@ccb_slot'] == 'zeta'
    assert backend.pane_options['%3']['@ccb_window'] == 'main'
    assert backend.pane_options['%4']['@ccb_slot'] == 'alpha'
    assert backend.pane_options['%4']['@ccb_window'] == 'main'
    assert review_sidebar not in backend.pane_options


def test_apply_moves_multiple_agents_to_new_target_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "main:codex"
review = "zeta:codex, alpha:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "main:codex"
archive = "zeta:codex, alpha:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    current = _load_config(tmp_path / 'current-move-new-target-agents', current_text)
    new = _load_config(tmp_path / 'new-move-new-target-agents', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-move-new-target-agents', current_text))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    review_sidebar = backend.add_window(layout.ccbd_tmux_session_name, 'review')
    backend.sessions[layout.ccbd_tmux_session_name][1]['panes'].extend(['%3', '%4'])
    backend.pane_counter = 4
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='main')
    _seed_sidebar_pane(backend, review_sidebar, project_id='proj-1', window='review')
    _seed_agent_pane(backend, '%3', project_id='proj-1', window='review', agent='zeta')
    _seed_agent_pane(backend, '%4', project_id='proj-1', window='review', agent='alpha')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch, allow_kill_window=True)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ('archive',)
    assert result.created_panes == ('%5',)
    assert result.sidebar_panes == {'archive': '%5'}
    assert result.agent_panes == {}
    assert result.removed_agents == {}
    assert result.removed_panes == ()
    assert result.removed_windows == ('review',)
    assert result.moved_agents == {'zeta': '%3', 'alpha': '%4'}
    assert result.moved_agent_windows == {'zeta': 'archive', 'alpha': 'archive'}
    assert result.reflowed_windows == ('archive',)
    assert result.reflow_errors == {}
    assert result.preserved_before == {'alpha': '%4', 'main': '%1', 'zeta': '%3'}
    assert result.preserved_after == {'alpha': '%4', 'main': '%1', 'zeta': '%3'}
    assert ('new-window', '-d', '-t', layout.ccbd_tmux_session_name, '-n', 'archive') in {
        call[:6] for call in backend.tmux_calls
    }
    assert ('move-pane', '-h', '-s', '%3', '-t', '%6') in backend.tmux_calls
    assert ('kill-pane', '-t', '%6') in backend.tmux_calls
    assert ('move-pane', '-v', '-s', '%4', '-t', '%3') in backend.tmux_calls
    assert ('kill-window', '-t', f'{layout.ccbd_tmux_session_name}:review') in backend.tmux_calls
    assert [record['name'] for record in backend.sessions[layout.ccbd_tmux_session_name]] == ['main', 'archive']
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1']
    assert backend.sessions[layout.ccbd_tmux_session_name][1]['panes'] == ['%5', '%3', '%4']
    assert backend.pane_options['%5']['@ccb_role'] == 'sidebar'
    assert backend.pane_options['%5']['@ccb_slot'] == 'sidebar:archive'
    assert '%6' not in backend.pane_options
    assert backend.pane_options['%3']['@ccb_slot'] == 'zeta'
    assert backend.pane_options['%3']['@ccb_window'] == 'archive'
    assert backend.pane_options['%4']['@ccb_slot'] == 'alpha'
    assert backend.pane_options['%4']['@ccb_window'] == 'archive'
    assert review_sidebar not in backend.pane_options


def test_apply_move_and_append_new_agent_to_existing_target_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "main:codex"
review = "zeta:codex"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "main:codex, zeta:codex, beta:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    current = _load_config(tmp_path / 'current-move-append-existing-target', current_text)
    new = _load_config(tmp_path / 'new-move-append-existing-target', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-move-append-existing-target', current_text))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    review_sidebar = backend.add_window(layout.ccbd_tmux_session_name, 'review')
    backend.sessions[layout.ccbd_tmux_session_name][1]['panes'].append('%3')
    backend.pane_counter = 3
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='main')
    _seed_sidebar_pane(backend, review_sidebar, project_id='proj-1', window='review')
    _seed_agent_pane(backend, '%3', project_id='proj-1', window='review', agent='zeta')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch, allow_kill_window=True)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ()
    assert result.created_panes == ('%4',)
    assert result.agent_panes == {'beta': '%4'}
    assert result.removed_windows == ('review',)
    assert result.moved_agents == {'zeta': '%3'}
    assert result.moved_agent_windows == {'zeta': 'main'}
    assert result.reflowed_windows == ('main',)
    assert result.reflow_errors == {}
    assert result.preserved_before == {'main': '%1', 'zeta': '%3'}
    assert result.preserved_after == {'main': '%1', 'zeta': '%3'}
    assert ('move-pane', '-v', '-s', '%3', '-t', '%1') in backend.tmux_calls
    assert backend.split_calls == [('%3', 'bottom', 50)]
    assert [record['name'] for record in backend.sessions[layout.ccbd_tmux_session_name]] == ['main']
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1', '%3', '%4']
    assert backend.pane_options['%3']['@ccb_slot'] == 'zeta'
    assert backend.pane_options['%3']['@ccb_window'] == 'main'
    assert backend.pane_options['%4']['@ccb_slot'] == 'beta'
    assert backend.pane_options['%4']['@ccb_window'] == 'main'
    assert review_sidebar not in backend.pane_options


def test_apply_move_and_append_new_agent_to_new_target_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "main:codex"
review = "zeta:codex, alpha:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "main:codex"
archive = "zeta:codex, alpha:claude, beta:codex"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    current = _load_config(tmp_path / 'current-move-append-new-target', current_text)
    new = _load_config(tmp_path / 'new-move-append-new-target', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-move-append-new-target', current_text))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    review_sidebar = backend.add_window(layout.ccbd_tmux_session_name, 'review')
    backend.sessions[layout.ccbd_tmux_session_name][1]['panes'].extend(['%3', '%4'])
    backend.pane_counter = 4
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='main')
    _seed_sidebar_pane(backend, review_sidebar, project_id='proj-1', window='review')
    _seed_agent_pane(backend, '%3', project_id='proj-1', window='review', agent='zeta')
    _seed_agent_pane(backend, '%4', project_id='proj-1', window='review', agent='alpha')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch, allow_kill_window=True)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ('archive',)
    assert result.created_panes == ('%5', '%7')
    assert result.sidebar_panes == {'archive': '%5'}
    assert result.agent_panes == {'beta': '%7'}
    assert result.removed_windows == ('review',)
    assert result.moved_agents == {'zeta': '%3', 'alpha': '%4'}
    assert result.moved_agent_windows == {'zeta': 'archive', 'alpha': 'archive'}
    assert result.reflowed_windows == ('archive',)
    assert result.reflow_errors == {}
    assert result.preserved_before == {'alpha': '%4', 'main': '%1', 'zeta': '%3'}
    assert result.preserved_after == {'alpha': '%4', 'main': '%1', 'zeta': '%3'}
    assert ('move-pane', '-h', '-s', '%3', '-t', '%6') in backend.tmux_calls
    assert ('kill-pane', '-t', '%6') in backend.tmux_calls
    assert ('move-pane', '-v', '-s', '%4', '-t', '%3') in backend.tmux_calls
    assert backend.split_calls[-1] == ('%4', 'bottom', 50)
    assert [record['name'] for record in backend.sessions[layout.ccbd_tmux_session_name]] == ['main', 'archive']
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1']
    assert backend.sessions[layout.ccbd_tmux_session_name][1]['panes'] == ['%5', '%3', '%4', '%7']
    assert backend.pane_options['%5']['@ccb_role'] == 'sidebar'
    assert backend.pane_options['%5']['@ccb_slot'] == 'sidebar:archive'
    assert '%6' not in backend.pane_options
    assert backend.pane_options['%3']['@ccb_slot'] == 'zeta'
    assert backend.pane_options['%3']['@ccb_window'] == 'archive'
    assert backend.pane_options['%4']['@ccb_slot'] == 'alpha'
    assert backend.pane_options['%4']['@ccb_window'] == 'archive'
    assert backend.pane_options['%7']['@ccb_slot'] == 'beta'
    assert backend.pane_options['%7']['@ccb_window'] == 'archive'
    assert review_sidebar not in backend.pane_options


def test_apply_move_agent_to_new_window_reuses_pane_and_removes_placeholder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = _load_config(tmp_path / 'current-move-agent-new-window', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-move-agent-new-window',
        """version = 2
entry_window = "main"

[windows]
main = "agent1:codex"
review = "agent2:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
""",
    )
    layout = PathLayout(_project(tmp_path / 'repo-move-agent-new-window', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ('review',)
    assert result.created_panes == ('%3',)
    assert result.sidebar_panes == {'review': '%3'}
    assert result.agent_panes == {}
    assert result.removed_agents == {}
    assert result.removed_panes == ()
    assert result.moved_agents == {'agent2': '%2'}
    assert result.moved_agent_windows == {'agent2': 'review'}
    assert result.reflowed_windows == ('main', 'review')
    assert result.reflow_errors == {}
    assert result.preserved_before == {'agent1': '%1', 'agent2': '%2'}
    assert result.preserved_after == {'agent1': '%1', 'agent2': '%2'}
    assert ('new-window', '-d', '-t', layout.ccbd_tmux_session_name, '-n', 'review') in {
        call[:6] for call in backend.tmux_calls
    }
    assert ('move-pane', '-h', '-s', '%2', '-t', '%4') in backend.tmux_calls
    assert ('kill-pane', '-t', '%4') in backend.tmux_calls
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1']
    assert backend.sessions[layout.ccbd_tmux_session_name][1]['panes'] == ['%3', '%2']
    assert backend.pane_options['%3']['@ccb_role'] == 'sidebar'
    assert backend.pane_options['%3']['@ccb_slot'] == 'sidebar:review'
    assert '%4' not in backend.pane_options
    assert backend.pane_options['%2']['@ccb_slot'] == 'agent2'
    assert backend.pane_options['%2']['@ccb_window'] == 'review'
    assert backend.pane_options['%2']['@ccb_namespace_epoch'] == '3'


def test_apply_move_agent_back_removes_empty_source_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex"
review = "agent2:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
"""
    current = _load_config(tmp_path / 'current-move-agent-back', current_text)
    new = _load_config(tmp_path / 'new-move-agent-back', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-move-agent-back', current_text))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    review_sidebar = backend.add_window(layout.ccbd_tmux_session_name, 'review')
    backend.sessions[layout.ccbd_tmux_session_name][1]['panes'].append('%3')
    backend.pane_counter = 3
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, review_sidebar, project_id='proj-1', window='review', agent='sidebar')
    backend.pane_options[review_sidebar]['@ccb_role'] = 'sidebar'
    backend.pane_options[review_sidebar]['@ccb_slot'] = 'sidebar:review'
    backend.pane_options[review_sidebar]['@ccb_sidebar_instance'] = 'review'
    _seed_agent_pane(backend, '%3', project_id='proj-1', window='review', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch, allow_kill_window=True)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ()
    assert result.created_panes == ()
    assert result.agent_panes == {}
    assert result.removed_agents == {}
    assert result.removed_panes == ()
    assert result.removed_windows == ('review',)
    assert result.moved_agents == {'agent2': '%3'}
    assert result.moved_agent_windows == {'agent2': 'main'}
    assert result.reflowed_windows == ('main',)
    assert result.reflow_errors == {}
    assert result.preserved_before == {'agent1': '%1', 'agent2': '%3'}
    assert result.preserved_after == {'agent1': '%1', 'agent2': '%3'}
    assert ('move-pane', '-v', '-s', '%3', '-t', '%1') in backend.tmux_calls
    assert ('kill-window', '-t', f'{layout.ccbd_tmux_session_name}:review') in backend.tmux_calls
    assert [record['name'] for record in backend.sessions[layout.ccbd_tmux_session_name]] == ['main']
    assert backend.sessions[layout.ccbd_tmux_session_name][0]['panes'] == ['%1', '%3']
    assert backend.pane_options['%3']['@ccb_slot'] == 'agent2'
    assert backend.pane_options['%3']['@ccb_window'] == 'main'
    assert review_sidebar not in backend.pane_options


def test_apply_add_tool_window_creates_tool_window_sidebar_and_tool_pane(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv('CCB_TMUX_THEME_PROFILE', 'light')
    current = _load_config(tmp_path / 'current-tool-window', BASE_CONFIG)
    new = _load_config(tmp_path / 'new-tool-window', ADD_TOOL_WINDOW_CONFIG)
    layout = PathLayout(_project(tmp_path / 'repo-tool-window', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.created_windows == ('files',)
    assert result.created_panes == ('%3', '%4')
    assert result.sidebar_panes == {'files': '%3'}
    assert result.tool_panes == {'files': '%4'}
    assert result.agent_panes == {}
    assert backend.respawn_calls[-2][0] == '%3'
    assert backend.respawn_calls[-2][1].startswith('CCB_SIDEBAR_THEME_PROFILE=light ')
    assert '--theme' not in backend.respawn_calls[-2][1]
    assert backend.respawn_calls[-1] == ('%4', 'ccb-workbench files')
    assert backend.pane_options['%3']['@ccb_role'] == 'sidebar'
    assert backend.pane_options['%3']['@ccb_slot'] == 'sidebar:files'
    assert backend.pane_options['%4']['@ccb_role'] == 'tool'
    assert backend.pane_options['%4']['@ccb_slot'] == 'tool:files'
    assert backend.pane_options['%4']['@ccb_window'] == 'files'
    assert result.diagnostics['runtime_authority_written'] is False


def test_apply_remove_tool_window_kills_only_tool_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = _load_config(tmp_path / 'current-tool-remove', ADD_TOOL_WINDOW_CONFIG)
    new = _load_config(tmp_path / 'new-tool-remove', BASE_CONFIG)
    layout = PathLayout(_project(tmp_path / 'repo-tool-remove', ADD_TOOL_WINDOW_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    tool_root = backend.add_window(layout.ccbd_tmux_session_name, 'files')
    backend.pane_options[tool_root] = {
        '@ccb_project_id': 'proj-1',
        '@ccb_role': 'tool',
        '@ccb_slot': 'tool:files',
        '@ccb_window': 'files',
        '@ccb_managed_by': 'ccbd',
    }
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch, allow_kill_window=True)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.removed_windows == ('files',)
    assert [
        call
        for call in backend.tmux_calls
        if call == ('kill-window', '-t', f'{layout.ccbd_tmux_session_name}:files')
    ] == [('kill-window', '-t', f'{layout.ccbd_tmux_session_name}:files')]
    assert [record['name'] for record in backend.sessions[layout.ccbd_tmux_session_name]] == ['main']
    assert tool_root not in backend.pane_options
    assert backend.pane_options['%1']['@ccb_slot'] == 'agent1'
    assert backend.pane_options['%2']['@ccb_slot'] == 'agent2'


def test_apply_remove_tool_window_is_idempotent_when_window_already_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = _load_config(tmp_path / 'current-tool-remove-missing', ADD_TOOL_WINDOW_CONFIG)
    new = _load_config(tmp_path / 'new-tool-remove-missing', BASE_CONFIG)
    layout = PathLayout(_project(tmp_path / 'repo-tool-remove-missing', ADD_TOOL_WINDOW_CONFIG))

    class _MissingWindowBackend(_PatchFakeBackend):
        def _tmux_run(self, args: list[str], *, check=False, capture=False, input_bytes=None, timeout=None):
            if len(args) >= 3 and args[:2] == ['kill-window', '-t']:
                self.tmux_calls.append(tuple(args))
                return SimpleNamespace(returncode=1, stdout='', stderr="can't find window: files")
            return super()._tmux_run(
                args,
                check=check,
                capture=capture,
                input_bytes=input_bytes,
                timeout=timeout,
            )

    backend = _MissingWindowBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch, allow_kill_window=True)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.removed_windows == ('files',)
    assert result.preserved_before == {'agent1': '%1', 'agent2': '%2'}
    assert result.preserved_after == {'agent1': '%1', 'agent2': '%2'}
    assert backend.pane_options['%1']['@ccb_slot'] == 'agent1'
    assert backend.pane_options['%2']['@ccb_slot'] == 'agent2'


def test_apply_remove_agent_window_tolerates_last_pane_closing_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex"
review = "agent2:claude"
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "agent1:codex"
"""
    current = _load_config(tmp_path / 'current-remove-window-single-pane', current_text)
    new = _load_config(tmp_path / 'new-remove-window-single-pane', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-remove-window-single-pane', current_text))

    class _LastPaneClosesWindowBackend(_PatchFakeBackend):
        def kill_pane(self, pane_id: str) -> None:
            super().kill_pane(pane_id)
            for session_name, windows in list(self.sessions.items()):
                self.sessions[session_name] = [record for record in windows if record['panes']]

    backend = _LastPaneClosesWindowBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    review_pane = backend.add_window(layout.ccbd_tmux_session_name, 'review')
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, review_pane, project_id='proj-1', window='review', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    assert result.removed_agents == {'agent2': review_pane}
    assert result.removed_panes == (review_pane,)
    assert result.removed_windows == ('review',)
    assert ('kill-pane', '-t', review_pane) in backend.tmux_calls
    assert ('kill-window', '-t', f'{layout.ccbd_tmux_session_name}:review') not in backend.tmux_calls
    assert [record['name'] for record in backend.sessions[layout.ccbd_tmux_session_name]] == ['main']
    assert review_pane not in backend.pane_options


def test_apply_remove_agent_window_selects_workspace_before_killing_dynamic_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current_text = """version = 2
entry_window = "main"

[windows]
main = "frontdesk:codex"
ccb-exec = "loop-coder:codex, loop-reviewer:codex"
"""
    new_text = """version = 2
entry_window = "main"

[windows]
main = "frontdesk:codex"
"""
    current = _load_config(tmp_path / 'current-remove-dynamic-window', current_text)
    new = _load_config(tmp_path / 'new-remove-dynamic-window', new_text)
    layout = PathLayout(_project(tmp_path / 'repo-remove-dynamic-window', current_text))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    main_pane = backend.add_window(layout.ccbd_tmux_session_name, 'main')
    exec_pane = backend.add_window(layout.ccbd_tmux_session_name, 'ccb-exec')
    backend.sessions[layout.ccbd_tmux_session_name][1]['panes'].append('%3')
    backend.pane_counter = 3
    _seed_agent_pane(backend, main_pane, project_id='proj-1', window='main', agent='frontdesk')
    _seed_agent_pane(backend, exec_pane, project_id='proj-1', window='ccb-exec', agent='loop-coder')
    _seed_agent_pane(backend, '%3', project_id='proj-1', window='ccb-exec', agent='loop-reviewer')
    _store_namespace(layout, project_id='proj-1', workspace_window_name='main', workspace_window_id='@1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch, allow_kill_window=True)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_reload_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    select_call = ('select-window', '-t', f'{layout.ccbd_tmux_session_name}:@1')
    kill_call = ('kill-window', '-t', f'{layout.ccbd_tmux_session_name}:ccb-exec')
    assert result.status == 'applied'
    assert result.removed_windows == ('ccb-exec',)
    assert select_call in backend.tmux_calls
    assert kill_call in backend.tmux_calls
    assert backend.tmux_calls.index(select_call) < backend.tmux_calls.index(kill_call)
    assert [record['name'] for record in backend.sessions[layout.ccbd_tmux_session_name]] == ['main']


def test_apply_append_add_agent_failure_does_not_publish_or_write_authority(tmp_path: Path, monkeypatch) -> None:
    current = _load_config(tmp_path / 'current-add-agent-fail', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-add-agent-fail',
        BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex, (agent2:claude; agent3:codex)'),
    )
    layout = PathLayout(_project(tmp_path / 'repo-add-agent-fail', BASE_CONFIG))

    class _FailingBackend(_PatchFakeBackend):
        def split_pane(self, parent_pane_id: str, direction: str, percent: int, cmd=None, cwd=None) -> str:
            raise RuntimeError('append split failed')

    backend = _FailingBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'failed'
    assert result.partial is False
    assert result.diagnostics['reason'] == 'namespace_patch_failed'
    assert result.diagnostics['graph_published'] is False
    assert result.diagnostics['runtime_authority_written'] is False
    assert result.diagnostics['lease_or_lifecycle_written'] is False


@pytest.mark.parametrize(
    ('new_config', 'expected_reason'),
    [
        (
            BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex, agent3:codex, agent2:claude'),
            'patch_plan_not_planned',
        ),
        (
            BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent1:codex; agent2:claude, agent3:codex'),
            'patch_plan_not_planned',
        ),
        (
            BASE_CONFIG.replace('agent1:codex, agent2:claude', 'agent2:claude, agent1:codex, agent3:codex'),
            'patch_plan_not_planned',
        ),
        (
            """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent3:codex"
review = "agent2:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
""",
            'patch_plan_not_planned',
        ),
    ],
)
def test_apply_add_agent_blocks_insert_reorder_move_and_non_last_layouts(
    tmp_path: Path,
    new_config: str,
    expected_reason: str,
) -> None:
    current = _load_config(tmp_path / 'current-non-append', BASE_CONFIG)
    new = _load_config(tmp_path / 'new-non-append', new_config)
    layout = PathLayout(_project(tmp_path / 'repo-non-append', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'blocked'
    assert result.diagnostics['reason'] == expected_reason
    assert backend.split_calls == []


def test_apply_additive_patch_requires_step_identity_proofs(tmp_path: Path) -> None:
    current = _load_config(tmp_path / 'current-proof', BASE_CONFIG)
    new = _load_config(tmp_path / 'new-proof', ADD_WINDOW_CONFIG)
    layout = PathLayout(_project(tmp_path / 'repo-proof', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())
    patch_plan = dict(plan['namespace_patch_plan'])
    patch_plan['steps'] = [
        {key: value for key, value in step.items() if key != 'managed_by'}
        for step in patch_plan['steps']
    ]

    result = controller.apply_additive_patch(
        patch_plan=patch_plan,
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'blocked'
    assert result.diagnostics['reason'] == 'scope_proof_missing'
    assert backend.split_calls == []


def test_apply_additive_patch_rejects_patch_plan_topology_mismatch(tmp_path: Path) -> None:
    current = _load_config(tmp_path / 'current-mismatch', BASE_CONFIG)
    new = _load_config(
        tmp_path / 'new-mismatch',
        """version = 2
entry_window = "main"

[windows]
main = "agent1:codex, agent2:claude"
review = "agent3:codex"
qa = "agent4:claude"

[ui.sidebar]
mode = "every_window"
width = "15%"
bottom_height = 20
""",
    )
    layout = PathLayout(_project(tmp_path / 'repo-mismatch', BASE_CONFIG))
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(layout, 'proj-1', backend_factory=lambda socket_path=None: backend)
    plan = build_reload_dry_run_plan(current, new, project_id='proj-1', current_namespace=controller.load())
    patch_plan = dict(plan['namespace_patch_plan'])
    patch_plan['steps'] = [
        step for step in patch_plan['steps']
        if not (isinstance(step, dict) and step.get('window') == 'qa')
    ]

    result = controller.apply_additive_patch(
        patch_plan=patch_plan,
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'blocked'
    assert result.diagnostics['reason'] == 'patch_plan_mismatch'
    assert backend.split_calls == []


def test_project_reload_non_dry_run_no_change_noops_after_patch_api(tmp_path: Path) -> None:
    project_root = _project(tmp_path / 'repo-block-no-change', BASE_CONFIG)
    app = CcbdApp(project_root, clock=lambda: '2026-05-29T00:00:00Z', pid=4242)
    old_graph = app.service_graph

    payload = app.socket_server._handlers['project_reload_config']({'dry_run': False})

    assert payload['status'] == 'noop'
    assert payload['stage'] == 'no_op'
    assert payload['plan_class'] == 'no_change'
    assert payload['diagnostics']['graph_published'] is False
    assert app.service_graph is old_graph
    assert app.control_plane_metrics.last_reload_duration_s is not None
    assert app.control_plane_metrics.last_reload_error is None


def _forbid_recreate_paths(monkeypatch, *, allow_kill_window: bool = False) -> None:
    monkeypatch.setattr(
        'ccbd.services.project_namespace_runtime.ensure.ensure_project_namespace',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('must not call full ensure')),
        raising=False,
    )
    forbidden_backend_mutations = ('kill_server',) if allow_kill_window else ('kill_server', 'kill_window')
    for name in forbidden_backend_mutations:
        monkeypatch.setattr(
            f'ccbd.services.project_namespace_runtime.backend.{name}',
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError(f'must not call {name}')),
            raising=False,
        )
    monkeypatch.setattr(
        'ccbd.services.project_namespace_runtime.ensure_state.force_recreate_namespace',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('must not force recreate namespace')),
        raising=False,
    )
    monkeypatch.setattr(
        'ccbd.services.project_namespace_runtime.reflow.reflow_project_workspace',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('must not reflow workspace')),
        raising=False,
    )


def _seed_agent_pane(backend: _PatchFakeBackend, pane_id: str, *, project_id: str, window: str, agent: str) -> None:
    backend.pane_options[pane_id] = {
        '@ccb_project_id': project_id,
        '@ccb_role': 'agent',
        '@ccb_slot': agent,
        '@ccb_window': window,
        '@ccb_managed_by': 'ccbd',
        '@ccb_namespace_epoch': '3',
    }


def _seed_sidebar_pane(backend: _PatchFakeBackend, pane_id: str, *, project_id: str, window: str) -> None:
    backend.pane_options[pane_id] = {
        '@ccb_project_id': project_id,
        '@ccb_role': 'sidebar',
        '@ccb_slot': f'sidebar:{window}',
        '@ccb_sidebar_instance': window,
        '@ccb_window': window,
        '@ccb_managed_by': 'ccbd',
        '@ccb_namespace_epoch': '3',
    }


def _store_namespace(
    layout: PathLayout,
    *,
    project_id: str,
    workspace_window_name: str = 'main',
    workspace_window_id: str = '@main',
) -> None:
    ProjectNamespaceStateStore(layout).save(
        ProjectNamespaceState(
            project_id=project_id,
            namespace_epoch=3,
            tmux_socket_path=str(layout.ccbd_tmux_socket_path),
            tmux_session_name=layout.ccbd_tmux_session_name,
            layout_version=3,
            layout_signature=None,
            control_window_name=layout.ccbd_tmux_control_window_name,
            control_window_id='@control',
            workspace_window_name=workspace_window_name,
            workspace_window_id=workspace_window_id,
            workspace_epoch=1,
            ui_attachable=True,
            last_started_at='2026-05-29T00:00:00Z',
        )
    )


def _herdr_namespace_state(*, project_id: str, session_name: str = 'ccb-herdr') -> ProjectNamespaceState:
    return ProjectNamespaceState(
        project_id=project_id,
        namespace_epoch=3,
        tmux_socket_path='',
        tmux_session_name=session_name,
        layout_version=3,
        layout_signature=None,
        control_window_name='ccb-control',
        control_window_id='control',
        workspace_window_name='main',
        workspace_window_id='main',
        workspace_epoch=1,
        ui_attachable=True,
        last_started_at='2026-05-29T00:00:00Z',
        namespace_backend_family='herdr-native',
        backend_impl='herdr',
        namespace_id='herdr-namespace-1',
        namespace_session_name=session_name,
        namespace_ipc_kind='herdr_socket',
        namespace_ipc_ref='herdr://namespace-1',
        namespace_restore_token='restore-secret',
    )


def _project(project_root: Path, config_text: str) -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = project_root / '.ccb' / 'ccb.config'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_text, encoding='utf-8')
    return project_root


def _load_config(project_root: Path, config_text: str):
    return load_project_config(_project(project_root, config_text)).config


def test_apply_add_window_normalizes_mixed_case_agent_names(tmp_path: Path, monkeypatch) -> None:
    """物化时 agent_panes key / pane token 用 normalize_agent_name 统一。

    回归背景（2026-08-06 采集暴露）：config 布局含大写 agent 名（Main_Code）时，
    物化用原始名写 key/token，消费端用 normalized 名匹配 → main_code 拿不到 pane →
    provider_runtime_deferred_on_herdr。
    """
    monkeypatch.delenv('CCB_TMUX_THEME_PROFILE', raising=False)
    config_text = ADD_WINDOW_CONFIG.replace('agent3:codex', 'Main_Code:codex')
    current = _load_config(tmp_path / 'current', BASE_CONFIG)
    new = _load_config(tmp_path / 'new', config_text)
    project_root = _project(tmp_path / 'repo', BASE_CONFIG)
    layout = PathLayout(project_root)
    backend = _PatchFakeBackend(socket_path=str(layout.ccbd_tmux_socket_path))
    backend.add_window(layout.ccbd_tmux_session_name, 'main')
    backend.sessions[layout.ccbd_tmux_session_name][0]['panes'].append('%2')
    backend.pane_counter = 2
    _seed_agent_pane(backend, '%1', project_id='proj-1', window='main', agent='agent1')
    _seed_agent_pane(backend, '%2', project_id='proj-1', window='main', agent='agent2')
    _store_namespace(layout, project_id='proj-1')
    controller = ProjectNamespaceController(
        layout,
        'proj-1',
        clock=lambda: '2026-05-29T00:00:00Z',
        backend_factory=lambda socket_path=None: backend,
    )
    _forbid_recreate_paths(monkeypatch)
    plan = build_reload_dry_run_plan(
        current,
        new,
        project_id='proj-1',
        current_namespace=controller.load(),
    )

    result = controller.apply_additive_patch(
        patch_plan=plan['namespace_patch_plan'],
        old_topology=build_namespace_topology_plan(current),
        new_topology=build_namespace_topology_plan(new),
        timeout_s=0.0,
    )

    assert result.status == 'applied'
    # 大写 agent 名物化后 key 归一化为小写；原始大小写 key 不应出现
    assert 'main_code' in result.agent_panes
    assert 'Main_Code' not in result.agent_panes
    assert result.agent_panes['main_code'] == '%4'
    # pane token 也应归一化（ccb_slot / ccb_agent 用 main_code）
    assert backend.pane_options['%4'].get('@ccb_slot') == 'main_code'
    assert backend.pane_options['%4'].get('@ccb_agent') == 'main_code'
