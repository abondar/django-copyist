import pytest

from django_copyist import ConfigIssueLevel, Copyist, check_config


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "invalid_config: the test runs a config that check_config() rejects on purpose",
    )


@pytest.fixture(autouse=True)
def every_config_passes_check_config(request, monkeypatch):
    """
    Run check_config() on every config that any test hands to Copyist.

    A config that copies successfully must not produce ERROR issues. This keeps the
    checker honest against every scenario in the suite.
    """
    if request.node.get_closest_marker("invalid_config"):
        yield
        return

    original_init = Copyist.__init__

    def checked_init(self, copy_request):
        errors = [
            issue
            for issue in check_config(copy_request.config)
            if issue.level == ConfigIssueLevel.ERROR
        ]
        assert not errors, "\n".join(str(e) for e in errors)
        original_init(self, copy_request)

    monkeypatch.setattr(Copyist, "__init__", checked_init)
    yield
