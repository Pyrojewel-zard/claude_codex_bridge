from __future__ import annotations

from ccbd.handlers.trace import build_trace_handler


class _Dispatcher:
    def trace(self, target: str) -> dict[str, object]:
        assert target == 'job_orphaned'
        return {
            'target': target,
            'resolved_kind': 'job',
            'job_id': 'job_orphaned',
            'jobs': [{'job_id': 'job_orphaned', 'status': 'running'}],
        }


class _ProjectViewService:
    def build_response(self, *, schema_version: int = 1) -> dict[str, object]:
        assert schema_version == 1
        return {
            'view': {
                'comms': [
                    {
                        'id': 'job_orphaned',
                        'active_inbound_diagnostic': {
                            'condition_kind': 'orphaned_active_inbound',
                            'reason': 'provider_idle_without_terminal',
                            'job_id': 'job_orphaned',
                            'attempt_id': 'att_orphaned',
                            'inbound_event_id': 'iev_orphaned',
                            'lease_state': 'acquired',
                            'observed_for_s': 30.0,
                            'required_observation_s': 30.0,
                            'recommended_action': 'explicit_comms_recover',
                            'automatic_action': 'none',
                        },
                    },
                    {
                        'id': 'job_other',
                        'active_inbound_diagnostic': {
                            'condition_kind': 'orphaned_active_inbound',
                            'job_id': 'job_other',
                        },
                    },
                ]
            }
        }


def test_trace_handler_merges_only_matching_active_inbound_diagnostic() -> None:
    handler = build_trace_handler(
        _Dispatcher(),
        project_view_service=_ProjectViewService(),
    )

    payload = handler({'target': 'job_orphaned'})

    assert payload['active_inbound_diagnostics'] == [
        {
            'condition_kind': 'orphaned_active_inbound',
            'reason': 'provider_idle_without_terminal',
            'job_id': 'job_orphaned',
            'attempt_id': 'att_orphaned',
            'inbound_event_id': 'iev_orphaned',
            'lease_state': 'acquired',
            'observed_for_s': 30.0,
            'required_observation_s': 30.0,
            'recommended_action': 'explicit_comms_recover',
            'automatic_action': 'none',
        }
    ]
