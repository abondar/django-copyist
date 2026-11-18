"""The README example must run as written."""

import re
from pathlib import Path

import pytest

from example.demo.models import Company, Employee, Project

README = Path(__file__).resolve().parents[3] / "README.rst"


def python_blocks(text: str) -> list[str]:
    blocks = []
    for match in re.finditer(r"\.\. code-block:: python\n\n((?:    .*\n|\n)+)", text):
        lines = [line[4:] for line in match.group(1).splitlines()]
        blocks.append("\n".join(lines))
    return blocks


@pytest.mark.django_db
def test_readme_example_runs():
    example = next(b for b in python_blocks(README.read_text()) if "run_copy(" in b)
    company = Company.objects.create(name="Acme", address="Main st.")
    Project.objects.create(name="P1", company=company)
    Employee.objects.create(name="E1", company=company)

    namespace = {"company": company}
    exec(example.replace("myapp.models", "example.demo.models"), namespace)

    new_company = namespace["new_company"]
    assert new_company.name == "Acme (copy)"
    assert new_company.address == "Main st."
    assert list(new_company.projects.values_list("name", flat=True)) == ["P1"]
    assert list(new_company.employees.values_list("name", flat=True)) == ["E1"]


def test_readme_check_config_example_passes():
    block = next(b for b in python_blocks(README.read_text()) if "check_config(" in b)
    example = next(b for b in python_blocks(README.read_text()) if "run_copy(" in b)
    config_source = example.split("result = run_copy(")[0]
    namespace: dict = {}
    exec(config_source.replace("myapp.models", "example.demo.models"), namespace)
    exec(block, namespace)
    namespace["test_company_copy_config"]()
