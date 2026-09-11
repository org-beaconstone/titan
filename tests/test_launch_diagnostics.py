from services.api.launch_diagnostics import DiagnosticSignal, has_blocking_signal, summarize_launch_signals


def test_summarize_launch_signals_counts_statuses():
    summary = summarize_launch_signals([
        DiagnosticSignal("retry-budget", "ready", "platform"),
        DiagnosticSignal("datadog-export", "watch", "sre"),
        DiagnosticSignal("release-notes", "ready", "support"),
    ])

    assert summary == {"ready": 2, "watch": 1}


def test_has_blocking_signal_detects_blocker():
    assert has_blocking_signal([
        DiagnosticSignal("worker-replay", "blocked", "platform"),
    ]) is True
