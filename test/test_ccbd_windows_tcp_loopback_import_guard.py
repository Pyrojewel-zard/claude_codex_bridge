from __future__ import annotations

from pathlib import Path


def test_windows_tcp_transport_does_not_add_named_pipe_or_af_unix_branches() -> None:
    root = Path('lib/ccbd/control_plane_transport')
    offenders: list[str] = []
    for path in root.glob('*.py'):
        text = path.read_text(encoding='utf-8').lower()
        if 'named_pipe' in text or 'named pipe' in text:
            offenders.append(f'{path}: named-pipe branch')
        if path.name != 'unix.py' and 'af_unix' in text:
            offenders.append(f'{path}: AF_UNIX outside Unix adapter')

    assert offenders == []


def test_token_secret_is_not_written_to_endpoint_or_diagnostics(tmp_path: Path) -> None:
    from ccbd.control_plane_transport.endpoint import endpoint_to_record, tcp_endpoint
    from ccbd.control_plane_transport.token_auth import TokenFile, redacted_token_diagnostics

    token = 'plain-secret-token'
    token_file = TokenFile(
        token_ref=str(tmp_path / 'token.json'),
        token=token,
        generation='gen',
        acl_status='windows-icacls-user-read',
    )
    endpoint = tcp_endpoint(
        host='127.0.0.1',
        port=45678,
        token_ref=token_file.token_ref,
        generation=token_file.generation,
        acl_status=token_file.acl_status,
    )

    endpoint_record = endpoint_to_record(endpoint)
    diagnostics = redacted_token_diagnostics(token_file)

    assert token not in repr(endpoint_record)
    assert token not in repr(diagnostics)
    assert endpoint_record['token_ref'] == token_file.token_ref
    assert diagnostics['token_ref'] == token_file.token_ref
