from postify.web.views import checks_summary


def test_checks_summary_separates_blocking_failures_and_warnings() -> None:
    report = {
        "passed": False,
        "layers": [
            {
                "layer": "rules",
                "items": [
                    {"passed": False, "severity": "warn"},
                    {"passed": False, "severity": "block"},
                ],
            },
            {
                "layer": "grounding",
                "items": [{"verdict": "unsupported"}],
            },
        ],
    }

    assert checks_summary(report) == {
        "passed": False,
        "blocking": 2,
        "warnings": 1,
    }
