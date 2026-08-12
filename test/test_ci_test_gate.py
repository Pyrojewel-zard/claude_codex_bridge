from __future__ import annotations

from pathlib import Path


TESTS_WORKFLOW = Path('.github/workflows/test.yml')
REAL_PLATFORM_WORKFLOW = Path('.github/workflows/ccbd-real-platform.yml')
CROSS_PLATFORM_WORKFLOW = Path('.github/workflows/cross-platform-test.yml')


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_required_unit_gate_uses_orthogonal_os_python_matrix() -> None:
    text = TESTS_WORKFLOW.read_text(encoding='utf-8')
    unit_job = _between(text, '  test:\n', '  lifecycle-smoke:\n')

    assert unit_job.count('- os: ubuntu-latest') == 3
    assert unit_job.count('- os: macos-latest') == 1
    assert unit_job.count('python-version: "3.10"') == 1
    assert unit_job.count('python-version: "3.11"') == 2
    assert unit_job.count('python-version: "3.12"') == 1
    assert 'os: [ubuntu-latest, macos-latest]' not in unit_job


def test_lifecycle_smokes_run_once_outside_the_unit_matrix() -> None:
    text = TESTS_WORKFLOW.read_text(encoding='utf-8')
    unit_step = _between(
        text,
        '      - name: Run tests\n',
        '      - name: Guard dynamic layout provider matrix smoke\n',
    )
    lifecycle_job = _between(
        text,
        '  lifecycle-smoke:\n',
        '  provider-blackbox:\n',
    )

    assert 'not provider_blackbox and not ccb_lifecycle_smoke' in unit_step
    assert '-m "ccb_lifecycle_smoke and not provider_blackbox"' in lifecycle_job
    assert 'python-version: "3.11"' in lifecycle_job
    assert 'timeout-minutes: 30' in lifecycle_job


def test_wsl_full_suite_is_not_duplicated_across_workflows() -> None:
    tests = TESTS_WORKFLOW.read_text(encoding='utf-8')
    real = REAL_PLATFORM_WORKFLOW.read_text(encoding='utf-8')
    cross = CROSS_PLATFORM_WORKFLOW.read_text(encoding='utf-8')
    cross_triggers = _between(cross, 'on:\n', '\njobs:\n')

    assert 'test-wsl:' not in tests
    assert 'Vampire/setup-wsl' not in tests
    assert 'Smoke ccb startup from /mnt/c in WSL' in real
    assert 'WSL path and relocation tests' in real
    assert 'pull_request:' not in cross_triggers


def test_required_test_gate_aggregates_every_specialist_lane() -> None:
    text = TESTS_WORKFLOW.read_text(encoding='utf-8')
    gate = text.split('  required-test-gate:\n', 1)[1]

    assert 'name: Required test gate' in gate
    for dependency in (
        'test',
        'lifecycle-smoke',
        'provider-blackbox',
        'rust-helpers',
        'macos-install-smoke',
    ):
        assert f'      - {dependency}\n' in gate
    assert 'if: ${{ always() }}' in gate


def test_tests_workflow_cancels_superseded_branch_runs() -> None:
    tests = TESTS_WORKFLOW.read_text(encoding='utf-8')
    real = REAL_PLATFORM_WORKFLOW.read_text(encoding='utf-8')
    cross = CROSS_PLATFORM_WORKFLOW.read_text(encoding='utf-8')

    assert 'group: ccb-tests-${{ github.event.pull_request.number || github.ref }}' in tests
    assert 'group: ccb-real-platform-${{ github.event.pull_request.number || github.ref }}' in real
    assert 'group: ccb-cross-platform-${{ github.ref }}' in cross
    assert all(
        'cancel-in-progress: true' in text
        for text in (tests, real, cross)
    )


def test_pull_request_workflows_do_not_duplicate_feature_branch_pushes() -> None:
    tests = TESTS_WORKFLOW.read_text(encoding='utf-8')
    real = REAL_PLATFORM_WORKFLOW.read_text(encoding='utf-8')

    for text in (tests, real):
        end = '\npermissions:\n' if 'permissions:' in text else '\nconcurrency:\n'
        triggers = _between(text, 'on:\n', end)
        assert 'workflow_dispatch:' in triggers
        assert 'pull_request:' in triggers
        assert '      - main\n' in triggers
        assert '      - dev\n' in triggers
        assert '      - "**"\n' not in triggers


def test_specialist_jobs_have_bounded_timeouts() -> None:
    text = TESTS_WORKFLOW.read_text(encoding='utf-8')

    expected = {
        '  lifecycle-smoke:\n': 'timeout-minutes: 30',
        '  provider-blackbox:\n': 'timeout-minutes: 15',
        '  rust-helpers:\n': 'timeout-minutes: 20',
        '  macos-install-smoke:\n': 'timeout-minutes: 30',
    }
    boundaries = list(expected) + ['  required-test-gate:\n']
    for index, (job, timeout) in enumerate(expected.items()):
        section = _between(text, job, boundaries[index + 1])
        assert timeout in section
