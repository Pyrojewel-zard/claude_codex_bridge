from __future__ import annotations

from types import SimpleNamespace

import cli.services.doctor as doctor_service


def _diagnostic(job_id: str) -> dict[str, object]:
    return {
        'condition_kind': 'orphaned_active_inbound',
        'reason': 'provider_idle_without_terminal',
        'job_id': job_id,
        'inbound_event_id': 'iev_orphaned',
        'lease_state': 'acquired',
        'observed_for_s': 30.0,
        'required_observation_s': 30.0,
        'recommended_action': 'explicit_comms_recover',
        'automatic_action': 'none',
    }


def test_doctor_loads_only_exact_project_view_active_inbound_diagnostics(monkeypatch) -> None:
    class _Client:
        def __init__(self, socket_path, *, timeout_s):
            assert str(socket_path).endswith('ccbd.sock')
            assert timeout_s > 0

        def project_view(self, *, schema_version: int):
            assert schema_version == 1
            return {
                'view': {
                    'comms': [
                        {'id': 'job_orphaned', 'active_inbound_diagnostic': _diagnostic('job_orphaned')},
                        {'id': 'job_other', 'active_inbound_diagnostic': _diagnostic('job_wrong')},
                    ]
                }
            }

    monkeypatch.setattr(doctor_service, 'CcbdClient', _Client)
    context = SimpleNamespace(paths=SimpleNamespace(ccbd_socket_path='/tmp/ccbd.sock'))
    local = SimpleNamespace(mount_state='mounted', socket_connectable=True)

    diagnostics, error = doctor_service._load_remote_project_view_diagnostics(context, local=local)

    assert error is None
    assert diagnostics == [_diagnostic('job_orphaned')]
