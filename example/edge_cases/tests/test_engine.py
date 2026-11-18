"""
Engine behaviour: options, query counts, abort flows, validation and errors.
"""

import pytest
from django.db import NotSupportedError, connection, connections
from django.test.utils import CaptureQueriesContext

import django_copyist
from django_copyist import (
    TAKE_FROM_ORIGIN,
    AbortReason,
    CopyActions,
    CopyistConfig,
    DataModificationActions,
    DataPreparationStep,
    FieldCopyConfig,
    FieldFilterConfig,
    FilterConfig,
    FilterSource,
    IgnoreCondition,
    IgnoreFilter,
    MakeCopy,
    ModelCopyConfig,
    PostcopyStep,
    TakeFromInput,
    UpdateToCopied,
    run_copy,
)
from example.demo import models as demo
from example.edge_cases.models import (
    Card,
    Item,
    Label,
    Page,
    Project,
    Stage,
    Tag,
    Workspace,
)


def make_project(item_count: int, tag_count: int = 2, using: str = "default") -> Project:
    project = Project.objects.using(using).create(name="P")
    tags = [Tag.objects.using(using).create(name=f"t{i}") for i in range(tag_count)]
    stage = Stage.objects.using(using).create(project=project, name="S")
    label = Label.objects.using(using).create(project=project, name="L")
    for i in range(item_count):
        item = Item.objects.using(using).create(project=project, name=f"i{i}", position=i)
        item.tags.set(tags)
        Card.objects.using(using).create(name=f"c{i}", stage=stage, label=label)
    return project


def project_config() -> ModelCopyConfig:
    return ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "items": MakeCopy(
                ModelCopyConfig(
                    model=Item,
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "position": TAKE_FROM_ORIGIN,
                        "is_active": TAKE_FROM_ORIGIN,
                        "tags": TAKE_FROM_ORIGIN,
                    },
                )
            ),
            "labels": MakeCopy(
                ModelCopyConfig(model=Label, field_copy_actions={"name": TAKE_FROM_ORIGIN})
            ),
            "stages": MakeCopy(
                ModelCopyConfig(
                    model=Stage,
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "cards": MakeCopy(
                            ModelCopyConfig(
                                model=Card,
                                field_copy_actions={
                                    "name": TAKE_FROM_ORIGIN,
                                    # FK copied from the origin: must not query per row.
                                    "label": TAKE_FROM_ORIGIN,
                                },
                            )
                        ),
                    },
                )
            ),
        },
    )


# --- Public API -----------------------------------------------------------------


def test_public_api_exports():
    for name in django_copyist.__all__:
        assert hasattr(django_copyist, name), name
    assert isinstance(django_copyist.__version__, str)


@pytest.mark.django_db
def test_run_copy_accepts_copyist_config():
    project = make_project(1)
    result = run_copy(CopyistConfig([project_config()]), input_data={"project_id": project.id})
    assert result.is_copy_successful
    assert result.reason is None


@pytest.mark.django_db
def test_copies_of_on_aborted_result_is_empty():
    result = django_copyist.CopyResult(
        is_copy_successful=False, output_map=None, ignored_map={}, set_to_filter_map={}
    )
    assert result.copies_of(Project) == {}


@pytest.mark.django_db
def test_nothing_to_copy():
    result = run_copy(project_config(), input_data={"project_id": 10**9})
    assert result.is_copy_successful
    assert result.output_map == {}


# --- Query counts -------------------------------------------------------------


def count_queries(item_count: int) -> int:
    project = make_project(item_count)
    with CaptureQueriesContext(connection) as ctx:
        result = run_copy(project_config(), input_data={"project_id": project.id})
    assert result.is_copy_successful
    assert len(result.copies_of(Item)) == item_count
    return len(ctx.captured_queries)


@pytest.mark.django_db
def test_query_count_does_not_grow_with_row_count():
    assert count_queries(2) == count_queries(40)


@pytest.mark.django_db
def test_batch_size_splits_inserts():
    project = make_project(5)
    with CaptureQueriesContext(connection) as ctx:
        result = run_copy(project_config(), input_data={"project_id": project.id}, batch_size=2)
    assert result.is_copy_successful
    item_inserts = [
        q
        for q in ctx.captured_queries
        if q["sql"].startswith("INSERT") and '"edge_cases_item"' in q["sql"]
    ]
    assert len(item_inserts) == 3
    tag_link_inserts = [
        q
        for q in ctx.captured_queries
        if q["sql"].startswith("INSERT") and '"edge_cases_item_tags"' in q["sql"]
    ]
    # 5 items x 2 tags = 10 rows in batches of 2.
    assert len(tag_link_inserts) == 5


# --- Database alias -----------------------------------------------------------


@pytest.mark.django_db(databases=["default", "other"])
def test_using_reads_and_writes_one_alias():
    project = make_project(3, using="other")

    with CaptureQueriesContext(connections["default"]) as default_queries:
        result = run_copy(project_config(), input_data={"project_id": project.id}, using="other")

    assert result.is_copy_successful
    assert default_queries.captured_queries == []
    assert Project.objects.using("other").count() == 2
    assert Item.objects.using("other").count() == 6
    assert Card.objects.using("other").count() == 6
    assert Project.objects.using("default").count() == 0
    new_project = Project.objects.using("other").get(pk=result.copies_of(Project)[str(project.pk)])
    assert all(i.tags.count() == 2 for i in Item.objects.using("other").filter(project=new_project))


@pytest.mark.django_db(databases=["default", "other"])
def test_using_with_steps_and_set_to_filter():
    project = Project.objects.using("other").create(name="P")
    target = Project.objects.using("other").create(name="T")
    Stage.objects.using("other").create(project=project, name="S")
    Stage.objects.using("other").create(project=target, name="old")

    config = ModelCopyConfig(
        model=Stage,
        filter_field_to_input_key={"project_id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "project": FieldCopyConfig(
                action=CopyActions.SET_TO_FILTER,
                reference_to=Project,
                filter_config=FilterConfig(
                    filters={"id": FieldFilterConfig(source=FilterSource.FROM_INPUT, key="target")}
                ),
            ),
        },
        data_preparation_steps=[
            DataPreparationStep(
                action=DataModificationActions.DELETE_BY_FILTER,
                filter_field_to_input_key={"project_id": "target"},
            )
        ],
    )
    result = run_copy(
        config, input_data={"project_id": project.id, "target": target.id}, using="other"
    )
    assert result.is_copy_successful
    assert list(Stage.objects.using("other").filter(project=target).values_list("name", flat=True)) == ["S"]


# --- Backends that cannot return primary keys ----------------------------------


@pytest.mark.django_db
def test_clear_error_when_backend_returns_no_primary_keys(monkeypatch):
    project = make_project(2)
    monkeypatch.setattr(
        type(connection.features), "can_return_rows_from_bulk_insert", property(lambda s: False)
    )
    with pytest.raises(NotSupportedError, match="did not return primary keys"):
        run_copy(project_config(), input_data={"project_id": project.id})
    # The transaction rolled back.
    assert Project.objects.count() == 1


@pytest.mark.django_db
def test_python_side_primary_keys_work_without_returning(monkeypatch):
    workspace = Workspace.objects.create(name="W")
    Page.objects.create(workspace=workspace, title="p")
    monkeypatch.setattr(
        type(connection.features), "can_return_rows_from_bulk_insert", property(lambda s: False)
    )
    config = ModelCopyConfig(
        model=Workspace,
        filter_field_to_input_key={"id": "workspace_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "pages": MakeCopy(ModelCopyConfig(model=Page, field_copy_actions={"title": TAKE_FROM_ORIGIN})),
        },
    )
    result = run_copy(config, input_data={"workspace_id": workspace.id})
    assert result.is_copy_successful
    assert Page.objects.count() == 2


# --- Field actions ------------------------------------------------------------


@pytest.mark.django_db
def test_take_from_input_accepts_instance_and_pk():
    project = make_project(1)
    target = Project.objects.create(name="target")
    for value in (target, target.pk):
        config = ModelCopyConfig(
            model=Item,
            filter_field_to_input_key={"project_id": "project_id"},
            field_copy_actions={"name": TAKE_FROM_ORIGIN, "project": TakeFromInput("target")},
        )
        result = run_copy(config, input_data={"project_id": project.id, "target": value})
        assert result.is_copy_successful
    assert Item.objects.filter(project=target).count() == 2


@pytest.mark.django_db
def test_reverse_m2m_take_from_origin():
    project = make_project(3, tag_count=1)
    tag = Tag.objects.get()
    config = ModelCopyConfig(
        model=Tag,
        filter_field_to_input_key={"id": "tag_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN, "items": TAKE_FROM_ORIGIN},
    )
    result = run_copy(config, input_data={"tag_id": tag.id})
    new_tag = Tag.objects.get(pk=result.copies_of(Tag)[str(tag.pk)])
    assert set(new_tag.items.all()) == set(Item.objects.filter(project=project))


@pytest.mark.django_db
@pytest.mark.parametrize("task_count", [1, 4])
def test_m2m_update_to_copied_with_many_instances(task_count):
    company = demo.Company.objects.create(name="C", address="A")
    project = demo.Project.objects.create(name="P", company=company)
    employee = demo.Employee.objects.create(name="E", company=company)
    counterparts = [
        demo.Counterpart.objects.create(name=str(i), external_id=i, project=project)
        for i in range(3)
    ]
    for i in range(task_count):
        demo.Task.objects.create(
            name=str(i), description="", assignee=employee, project=project
        ).counterparts.set(counterparts)

    config = ModelCopyConfig(
        model=demo.Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "company": TAKE_FROM_ORIGIN,
            "counterparts": MakeCopy(
                ModelCopyConfig(
                    model=demo.Counterpart,
                    field_copy_actions={"name": TAKE_FROM_ORIGIN, "external_id": TAKE_FROM_ORIGIN},
                )
            ),
        },
        compound_copy_actions=[
            ModelCopyConfig(
                model=demo.Task,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "description": TAKE_FROM_ORIGIN,
                    "assignee": TAKE_FROM_ORIGIN,
                    "project": UpdateToCopied(demo.Project),
                    "counterparts": UpdateToCopied(demo.Counterpart),
                },
            )
        ],
    )
    result = run_copy(config, input_data={"project_id": project.id})
    assert result.is_copy_successful
    new_project = demo.Project.objects.get(pk=result.copies_of(demo.Project)[str(project.pk)])
    new_counterparts = set(new_project.counterparts.all())
    assert len(new_counterparts) == 3
    for task in new_project.tasks.all():
        assert set(task.counterparts.all()) == new_counterparts


# --- Abort and confirm flows -----------------------------------------------------


def set_to_filter_setup():
    company = demo.Company.objects.create(name="C", address="A")
    origin = demo.Project.objects.create(name="origin", company=company)
    target = demo.Project.objects.create(name="target", company=company)
    employee = demo.Employee.objects.create(name="E", company=company)
    matched = demo.Counterpart.objects.create(name="m", external_id=1, project=origin)
    unmatched = demo.Counterpart.objects.create(name="u", external_id=2, project=origin)
    target_matched = demo.Counterpart.objects.create(name="m", external_id=1, project=target)
    task = demo.Task.objects.create(name="T", description="", assignee=employee, project=origin)
    task.counterparts.set([matched, unmatched])
    skipped = demo.Task.objects.create(name="skip", description="", assignee=employee, project=origin)

    config = ModelCopyConfig(
        model=demo.Task,
        filter_field_to_input_key={"project_id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "description": TAKE_FROM_ORIGIN,
            "assignee": TAKE_FROM_ORIGIN,
            "project": TakeFromInput("target_id"),
            "counterparts": FieldCopyConfig(
                action=CopyActions.SET_TO_FILTER,
                reference_to=demo.Counterpart,
                filter_config=FilterConfig(
                    filters={
                        "external_id": FieldFilterConfig(source=FilterSource.FROM_ORIGIN),
                        "project_id": FieldFilterConfig(
                            source=FilterSource.FROM_INPUT, key="target_id"
                        ),
                    }
                ),
            ),
        },
        ignore_condition=IgnoreCondition(
            ignore_func=lambda model_extra_filter, **kwargs: list(
                demo.Task.objects.filter(name="skip")
            )
        ),
    )
    input_data = {"project_id": origin.id, "target_id": target.id}
    return config, input_data, target, target_matched, unmatched, skipped


@pytest.mark.django_db
def test_abort_then_confirm_with_same_maps():
    config, input_data, target, target_matched, unmatched, skipped = set_to_filter_setup()

    first = run_copy(config, input_data)
    assert not first.is_copy_successful
    assert first.reason == AbortReason.IGNORED
    assert first.output_map is None
    assert first.set_to_filter_map["Task"]["counterparts"][str(unmatched.pk)] is None
    assert first.ignored_map == {"Task": [skipped.pk]}
    assert demo.Task.objects.filter(project=target).count() == 0

    second = run_copy(
        config,
        input_data,
        confirm_write=True,
        set_to_filter_map=first.set_to_filter_map,
        ignored_map=first.ignored_map,
    )
    assert second.is_copy_successful
    copied = demo.Task.objects.get(project=target)
    assert copied.name == "T"
    assert list(copied.counterparts.all()) == [target_matched]


@pytest.mark.django_db
def test_confirm_with_stale_set_to_filter_map():
    config, input_data, *_ = set_to_filter_setup()
    first = run_copy(config, input_data)
    stale = {"Task": {"counterparts": {}}}
    result = run_copy(
        config,
        input_data,
        confirm_write=True,
        set_to_filter_map=stale,
        ignored_map=first.ignored_map,
    )
    assert result.reason == AbortReason.DATA_CHANGED_STF


@pytest.mark.django_db
def test_confirm_with_stale_ignored_map():
    config, input_data, *_ = set_to_filter_setup()
    first = run_copy(config, input_data)
    result = run_copy(
        config,
        input_data,
        confirm_write=True,
        set_to_filter_map=first.set_to_filter_map,
        ignored_map={"Task": []},
    )
    assert result.reason == AbortReason.DATA_CHANGED_IGNORED


@pytest.mark.django_db
def test_not_matched_without_ignore():
    config, input_data, *_ = set_to_filter_setup()
    config.ignore_condition = None
    result = run_copy(config, input_data)
    assert result.reason == AbortReason.NOT_MATCHED


@pytest.mark.django_db
def test_ignore_filter_condition_with_custom_lookup():
    config, input_data, target, _, unmatched, _ = set_to_filter_setup()
    config.ignore_condition = IgnoreCondition(
        filter_conditions=[
            IgnoreFilter(
                filter_name="counterparts__in",
                set_to_filter_origin_model=demo.Task,
                set_to_filter_field_name="counterparts",
            )
        ]
    )
    first = run_copy(config, input_data)
    assert first.reason == AbortReason.IGNORED
    second = run_copy(config, input_data, confirm_write=True)
    assert second.is_copy_successful
    # The task with the unmatched counterpart is ignored, "skip" is copied.
    assert list(demo.Task.objects.filter(project=target).values_list("name", flat=True)) == [
        "skip"
    ]


# --- Steps --------------------------------------------------------------------


@pytest.mark.django_db
def test_postcopy_delete_by_filter_and_func():
    project = make_project(2)
    calls = []

    def postcopy(model_config, input_data, set_to_filter_map, output_map, copy_intent_list):
        calls.append((model_config.model, len(copy_intent_list), dict(output_map)))

    config = project_config()
    item_config = config.field_copy_actions["items"].copy_with_config
    item_config.postcopy_steps = [
        PostcopyStep(
            action=DataModificationActions.DELETE_BY_FILTER,
            filter_field_to_input_key={"project_id": "project_id"},
        ),
        PostcopyStep(action=DataModificationActions.EXECUTE_FUNC, func=postcopy),
    ]
    result = run_copy(config, input_data={"project_id": project.id})
    assert result.is_copy_successful
    # Origin items were deleted after the copy, copies remain.
    assert Item.objects.filter(project=project).count() == 0
    assert Item.objects.count() == 2
    assert calls[0][0] is Item and calls[0][1] == 2
    assert "Project" in calls[0][2]


# --- Validation and errors ------------------------------------------------------


@pytest.mark.parametrize(
    "factory, message",
    [
        (lambda: IgnoreCondition(), "Only one of"),
        (
            lambda: IgnoreCondition(
                filter_conditions=[IgnoreFilter("x", Project, "y")], ignore_func=lambda **k: []
            ),
            "Only one of",
        ),
        (lambda: FieldFilterConfig(source=FilterSource.FROM_INPUT), "should define key"),
        (lambda: FieldFilterConfig(source=FilterSource.FROM_ORIGIN, key="k"), "should not"),
        (lambda: FilterConfig(), "should define one of"),
        (lambda: FieldCopyConfig(action=CopyActions.MAKE_COPY), "copy_with_config"),
        (lambda: FieldCopyConfig(action=CopyActions.UPDATE_TO_COPIED), "reference_to"),
        (
            lambda: FieldCopyConfig(action=CopyActions.SET_TO_FILTER, reference_to=Project),
            "filter_config",
        ),
        (
            lambda: FieldCopyConfig(
                action=CopyActions.SET_TO_FILTER,
                filter_config=FilterConfig(filter_func=lambda **k: {}),
            ),
            "reference_to",
        ),
        (lambda: FieldCopyConfig(action=CopyActions.TAKE_FROM_INPUT), "input_key"),
        (
            lambda: DataPreparationStep(action=DataModificationActions.DELETE_BY_FILTER),
            "Only one of",
        ),
    ],
)
def test_config_validation(factory, message):
    with pytest.raises(ValueError, match=message):
        factory()


@pytest.mark.django_db
@pytest.mark.invalid_config
@pytest.mark.parametrize(
    "config, input_data, message",
    [
        (
            ModelCopyConfig(model=Project, field_copy_actions={"name": TAKE_FROM_ORIGIN}),
            {},
            "Root config must describe",
        ),
        (
            ModelCopyConfig(
                model=Project,
                filter_field_to_input_key={"id": "project_id"},
                field_copy_actions={"name": TAKE_FROM_ORIGIN},
            ),
            {},
            "key project_id was not found",
        ),
        (
            ModelCopyConfig(
                model=Project,
                filter_field_to_input_key={"id": "project_id"},
                field_copy_actions={"name": TakeFromInput("new_name")},
            ),
            {"project_id": 1},
            "No new_name in input_data",
        ),
        (
            ModelCopyConfig(
                model=Project,
                filter_field_to_input_key={"id": "project_id"},
                field_copy_actions={"name": TAKE_FROM_ORIGIN},
                data_preparation_steps=[
                    DataPreparationStep(
                        action=DataModificationActions.DELETE_BY_FILTER,
                        filter_field_to_input_key={"name": "missing"},
                    )
                ],
            ),
            {"project_id": 1},
            "needs missing in input_data",
        ),
        (
            ModelCopyConfig(
                model=Item,
                filter_field_to_input_key={"project_id": "project_id"},
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "project": FieldCopyConfig(
                        action=CopyActions.SET_TO_FILTER,
                        reference_to=Project,
                        filter_config=FilterConfig(
                            filters={
                                "id": FieldFilterConfig(source=FilterSource.FROM_INPUT, key="t")
                            }
                        ),
                    ),
                },
            ),
            {"project_id": 1},
            "value for t not found",
        ),
    ],
)
def test_runtime_errors(config, input_data, message):
    project = make_project(1)
    input_data = {k: (project.pk if v == 1 else v) for k, v in input_data.items()}
    with pytest.raises(ValueError, match=message):
        run_copy(config, input_data)


@pytest.mark.django_db
@pytest.mark.invalid_config
def test_model_configured_twice_fails_at_runtime():
    project = make_project(1)
    stage = ModelCopyConfig(model=Stage, field_copy_actions={"name": TAKE_FROM_ORIGIN})
    config = ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN, "stages": MakeCopy(stage)},
        compound_copy_actions=[
            ModelCopyConfig(
                model=Stage,
                field_copy_actions={"name": TAKE_FROM_ORIGIN, "project": UpdateToCopied(Project)},
            )
        ],
    )
    with pytest.raises(ValueError, match="configured for copy several times"):
        run_copy(config, {"project_id": project.pk})


# --- Large id lists -------------------------------------------------------------


@pytest.mark.django_db
def test_long_id_lists_are_chunked(monkeypatch):
    """With a tiny parameter limit, every IN lookup must be split into chunks."""
    project = make_project(250, tag_count=3)
    # A data descriptor on the class wins over Django's property or cached value.
    monkeypatch.setattr(type(connection.features), "max_query_params", property(lambda s: 150))

    with CaptureQueriesContext(connection) as ctx:
        result = run_copy(project_config(), input_data={"project_id": project.id})

    assert result.is_copy_successful
    new_project = Project.objects.get(pk=result.copies_of(Project)[str(project.pk)])
    assert new_project.items.count() == 250
    assert Item.tags.through.objects.filter(item__project=new_project).count() == 750
    assert Card.objects.filter(stage__project=new_project).count() == 250
    # Fetching through rows for 250 items took 3 queries of at most 100 ids.
    through_selects = [
        q["sql"]
        for q in ctx.captured_queries
        if q["sql"].startswith("SELECT") and '"edge_cases_item_tags"' in q["sql"]
    ]
    assert len(through_selects) == 3


# --- Children of rows that are not copied ------------------------------------------


@pytest.mark.django_db
def test_children_of_skipped_rows_are_not_copied():
    matched_project = Project.objects.create(name="same")
    unmatched_project = Project.objects.create(name="same")
    target = Project.objects.create(name="target")
    kept = Stage.objects.create(project=matched_project, name="kept")
    dropped = Stage.objects.create(project=unmatched_project, name="dropped")
    Card.objects.create(name="kept card", stage=kept)
    Card.objects.create(name="dropped card", stage=dropped)

    config = ModelCopyConfig(
        model=Stage,
        filter_field_to_input_key={"project__name": "project_name"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "project": FieldCopyConfig(
                action=CopyActions.SET_TO_FILTER,
                reference_to=Project,
                filter_config=FilterConfig(
                    filter_func=lambda referenced_instance_list, **kwargs: {
                        str(p.pk): (str(target.pk) if p.pk == matched_project.pk else None)
                        for p in referenced_instance_list
                    }
                ),
            ),
            "cards": MakeCopy(
                ModelCopyConfig(model=Card, field_copy_actions={"name": TAKE_FROM_ORIGIN})
            ),
        },
    )
    first = run_copy(config, {"project_name": "same"})
    assert first.reason == AbortReason.NOT_MATCHED

    result = run_copy(
        config,
        {"project_name": "same"},
        confirm_write=True,
        set_to_filter_map=first.set_to_filter_map,
    )
    assert result.is_copy_successful
    assert list(target.stages.values_list("name", flat=True)) == ["kept"]
    assert set(Card.objects.values_list("name", flat=True)) == {
        "kept card",
        "dropped card",
    }
    assert Card.objects.filter(stage__project=target).count() == 1
