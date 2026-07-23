from __future__ import annotations

from provider_core.caller_env import provider_user_session_env
from runtime_env.user_session import user_session_transport_env


def test_user_session_transport_env_selects_only_transport_keys() -> None:
    env = user_session_transport_env(
        {
            'HTTPS_PROXY': 'http://127.0.0.1:7890',
            'http_proxy': 'http://127.0.0.1:7891',
            'NO_PROXY': 'localhost,127.0.0.1',
            'CODEX_CA_CERTIFICATE': '/tmp/codex-ca.pem',
            'NODE_EXTRA_CA_CERTS': '/tmp/node-ca.pem',
            'WSL_INTEROP': '/run/WSL/1234_interop',
            'BROWSER': 'wslview',
            'CODEX_HOME': '/tmp/global-codex-home',
            'GEMINI_ROOT': '/tmp/global-gemini-root',
            'CLAUDE_PROJECTS_ROOT': '/tmp/global-claude-projects',
            'EMPTY_PROXY': '',
            'SSL_CERT_FILE': '',
        }
    )

    assert env == {
        'HTTPS_PROXY': 'http://127.0.0.1:7890',
        'http_proxy': 'http://127.0.0.1:7891',
        'NO_PROXY': 'localhost,127.0.0.1',
        'CODEX_CA_CERTIFICATE': '/tmp/codex-ca.pem',
        'NODE_EXTRA_CA_CERTS': '/tmp/node-ca.pem',
        'WSL_INTEROP': '/run/WSL/1234_interop',
        'BROWSER': 'wslview',
    }


def test_managed_provider_process_env_disables_generic_node_update_notifier(
    monkeypatch,
) -> None:
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:7890')
    monkeypatch.setenv('AGY_CLI_DISABLE_AUTO_UPDATE', '0')
    monkeypatch.setenv('FACTORYD_DISABLE_AUTO_UPDATE', '0')
    monkeypatch.setenv('GROK_DISABLE_AUTOUPDATER', '0')
    monkeypatch.setenv('NO_UPDATE_NOTIFIER', '0')

    env = provider_user_session_env()

    assert env['HTTPS_PROXY'] == 'http://127.0.0.1:7890'
    assert env['AGY_CLI_DISABLE_AUTO_UPDATE'] == '1'
    assert env['FACTORYD_DISABLE_AUTO_UPDATE'] == '1'
    assert env['GROK_DISABLE_AUTOUPDATER'] == '1'
    assert env['NO_UPDATE_NOTIFIER'] == '1'
