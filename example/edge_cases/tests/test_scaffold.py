from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from django_copyist import ConfigIssueLevel, check_config, run_copy
from django_copyist.scaffold import scaffold_config
from example.demo import models as demo
from example.edge_cases.models import Item, Project, Restaurant, Tag, Ticket, TicketWatcher


def load(source: str, name: str):
    namespace: dict = {}
    exec(compile(source, "<scaffold>", "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize(
    "model",
    [demo.Company, demo.Task, Project, Ticket],
)
@pytest.mark.parametrize("depth", [0, 1, 3])
def test_scaffold_output_passes_check_config(model, depth):
    source = scaffold_config(model, depth=depth, name="CONFIG")
    config = load(source, "CONFIG")
    errors = [i for i in check_config(config) if i.level == ConfigIssueLevel.ERROR]
    assert errors == []


@pytest.mark.django_db
def test_scaffolded_config_copies_a_tree():
    company = demo.Company.objects.create(name="C", address="A")
    project = demo.Project.objects.create(name="P", company=company)
    employee = demo.Employee.objects.create(name="E", company=company)
    counterpart = demo.Counterpart.objects.create(name="CP", external_id=1, project=project)
    task = demo.Task.objects.create(name="T", description="D", assignee=employee, project=project)
    task.counterparts.add(counterpart)

    config = load(scaffold_config(demo.Company, depth=2), "COMPANY_COPY_CONFIG")
    result = run_copy(config, input_data={"company_pk": company.pk})

    assert result.is_copy_successful
    new_company = demo.Company.objects.get(pk=result.copies_of(demo.Company)[str(company.pk)])
    assert new_company.name == "C"
    new_project = new_company.projects.get()
    assert new_project.counterparts.count() == 1
    new_task = new_project.tasks.get()
    assert new_task.name == "T"
    # The scaffold keeps references to rows that are copied in another branch.
    assert new_task.assignee_id == employee.pk
    assert list(new_task.counterparts.all()) == [counterpart]
    assert new_company.employees.count() == 1


@pytest.mark.django_db
def test_scaffolded_config_with_unique_field_and_through_model():
    project = Project.objects.create(name="P")
    tag = Tag.objects.create(name="t")
    ticket = Ticket.objects.create(project=project, title="T", slug="t-1")
    TicketWatcher.objects.create(ticket=ticket, tag=tag, role="owner")

    config = load(scaffold_config(Project, depth=2), "PROJECT_COPY_CONFIG")
    result = run_copy(config, input_data={"project_pk": project.pk, "ticket_slug": "t-2"})

    assert result.is_copy_successful
    new_ticket = Ticket.objects.get(slug="t-2")
    assert new_ticket.project_id != project.pk
    watcher = TicketWatcher.objects.get(ticket=new_ticket)
    assert (watcher.tag_id, watcher.role) == (tag.pk, "owner")


def test_scaffold_names_and_todos():
    source = scaffold_config(Project, depth=0, name="MY_CONFIG", input_key="origin")
    assert source.startswith('"""')
    assert "MY_CONFIG = ModelCopyConfig(" in source
    assert '{"pk": "origin"}' in source
    assert "raise --depth" in source

    item_source = scaffold_config(Item, depth=0)
    assert "ITEM_COPY_CONFIG" in item_source
    assert '"tags": TAKE_FROM_ORIGIN' in item_source

    restaurant = scaffold_config(Restaurant)
    assert "multi-table inheritance" in restaurant


def test_scaffold_marks_self_reference_and_manual_primary_key():
    from example.edge_cases.models import Category, Country

    category = scaffold_config(Category, depth=0)
    assert "points to Category itself" in category
    country = scaffold_config(Country, depth=0, name="C")
    assert '"code": TakeFromInput("country_code")' in country
    errors = [i for i in check_config(load(country, "C")) if i.level == ConfigIssueLevel.ERROR]
    assert errors == []


@pytest.mark.parametrize("kwargs", [{"depth": -1}, {"name": "not valid"}, {"name": "class"}])
def test_scaffold_rejects_bad_arguments(kwargs):
    with pytest.raises(ValueError):
        scaffold_config(Project, **kwargs)


def test_command_prints_config_and_check_summary():
    out, err = StringIO(), StringIO()
    call_command("copyist_scaffold", "demo.Company", "--depth", "2", stdout=out, stderr=err)
    assert "COMPANY_COPY_CONFIG = ModelCopyConfig(" in out.getvalue()
    assert "check_config: 0 error(s)" in err.getvalue()


def test_command_reports_errors_of_generated_config():
    out, err = StringIO(), StringIO()
    call_command("copyist_scaffold", "edge_cases.Restaurant", stdout=out, stderr=err)
    assert "copyist.E007" in err.getvalue()


def test_command_no_check():
    out, err = StringIO(), StringIO()
    call_command("copyist_scaffold", "demo.Company", "--no-check", stdout=out, stderr=err)
    assert err.getvalue() == ""


@pytest.mark.parametrize("label", ["demo.Nope", "nope", "nope.Company"])
def test_command_unknown_model(label):
    with pytest.raises(CommandError, match="Unknown model"):
        call_command("copyist_scaffold", label)


def test_command_bad_depth():
    with pytest.raises(CommandError, match="depth"):
        call_command("copyist_scaffold", "demo.Company", "--depth", "-1")
