"""Checks for files that external services read from the repository."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_context7_config_fits_context7_limits():
    """
    Context7 skips a rule longer than 255 characters and logs only a warning, so the
    rule silently disappears from the docs that agents get.
    """
    config = json.loads((REPO_ROOT / "context7.json").read_text())

    assert config["projectTitle"] == "django-copyist"
    assert config["rules"]
    for index, rule in enumerate(config["rules"]):
        assert isinstance(rule, str)
        assert len(rule) <= 255, f"rules[{index}] has {len(rule)} characters: {rule[:60]}..."
