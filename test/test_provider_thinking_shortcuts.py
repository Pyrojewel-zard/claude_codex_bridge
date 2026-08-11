from __future__ import annotations

from provider_thinking_shortcuts import (
    provider_thinking_levels,
    provider_thinking_startup_args,
    startup_args_contain_thinking_flag,
    strip_provider_thinking_startup_args,
)


def test_claude_effort_compiles_to_current_cli_contract() -> None:
    assert provider_thinking_levels('claude') == (
        'low',
        'medium',
        'high',
        'xhigh',
        'max',
    )
    assert provider_thinking_startup_args('claude', thinking='xhigh') == (
        '--effort',
        'xhigh',
    )
    assert startup_args_contain_thinking_flag('claude', ['--effort', 'high'])
    assert startup_args_contain_thinking_flag('claude', ['--effort=max'])
    assert strip_provider_thinking_startup_args(
        'claude',
        ['--effort', 'xhigh', '--permission-mode', 'manual'],
        thinking='xhigh',
    ) == ('--permission-mode', 'manual')
