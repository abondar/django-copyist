"""
Regression tests for bugs fixed in 0.2.0.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from django_copyist import (
    TAKE_FROM_ORIGIN,
    CopyActions,
    CopyistConfig,
    CopyRequest,
    FieldCopyConfig,
    FieldFilterConfig,
    FilterConfig,
    FilterSource,
    IgnoreCondition,
    DataModificationActions,
    MakeCopy,
    MapKeys,
    ModelCopyConfig,
    PostcopyStep,
    TakeFromInput,
    UpdateToCopied,
    check_config,
    run_copy,
)
from example.demo import models as demo
from example.edge_cases.models import (
    Card,
    Document,
    Folder,
    Item,
    Label,
    Note,
    Page,
    Project,
    Stage,
    Tag,
    Workspace,
)


def _item_config(tags_action: FieldCopyConfig) -> ModelCopyConfig:
    return ModelCopyConfig(
        model=Item,
        filter_field_to_input_key={"project_id": "project_id"},
        field_copy_actions={
            "project": FieldCopyConfig(
                action=CopyActions.TAKE_FROM_INPUT, input_key="new_project_id"
            ),
            "name": TAKE_FROM_ORIGIN,
            "tags": tags_action,
        },
    )


@pytest.mark.django_db
@pytest.mark.parametrize("item_count", [1, 2, 5])
def test_m2m_take_from_origin_with_many_instances(item_count):
    project = Project.objects.create(name="P")
    new_project = Project.objects.create(name="P2")
    tags = [Tag.objects.create(name=f"t{i}") for i in range(3)]
    for i in range(item_count):
        Item.objects.create(project=project, name=f"i{i}").tags.set(tags)

    result = run_copy(
        _item_config(TAKE_FROM_ORIGIN),
        input_data={"project_id": project.id, "new_project_id": new_project.id},
    )

    assert result.is_copy_successful
    copied = Item.objects.filter(project=new_project)
    assert copied.count() == item_count
    for item in copied:
        assert set(item.tags.all()) == set(tags)


@pytest.mark.django_db
@pytest.mark.parametrize("item_count", [1, 2, 5])
def test_m2m_set_to_filter_with_many_instances(item_count):
    origin = demo.Company.objects.create(name="Origin", address="A")
    target = demo.Company.objects.create(name="Target", address="B")
    origin_project = demo.Project.objects.create(name="P", company=origin)
    target_project = demo.Project.objects.create(name="P", company=target)
    employee = demo.Employee.objects.create(name="E", company=origin)
    origin_counterparts = [
        demo.Counterpart.objects.create(name=str(i), external_id=i, project=origin_project)
        for i in range(3)
    ]
    target_counterparts = [
        demo.Counterpart.objects.create(name=str(i), external_id=i, project=target_project)
        for i in range(3)
    ]
    for i in range(item_count):
        task = demo.Task.objects.create(
            name=f"T{i}", description="", assignee=employee, project=origin_project
        )
        task.counterparts.set(origin_counterparts)

    config = ModelCopyConfig(
        model=demo.Task,
        filter_field_to_input_key={"project_id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "description": TAKE_FROM_ORIGIN,
            "assignee": TAKE_FROM_ORIGIN,
            "project": FieldCopyConfig(
                action=CopyActions.TAKE_FROM_INPUT, input_key="new_project_id"
            ),
            "counterparts": FieldCopyConfig(
                action=CopyActions.SET_TO_FILTER,
                reference_to=demo.Counterpart,
                filter_config=FilterConfig(
                    filters={
                        "external_id": FieldFilterConfig(source=FilterSource.FROM_ORIGIN),
                        "project_id": FieldFilterConfig(
                            source=FilterSource.FROM_INPUT, key="new_project_id"
                        ),
                    }
                ),
            ),
        },
    )
    result = run_copy(
        config,
        input_data={"project_id": origin_project.id, "new_project_id": target_project.id},
    )

    assert result.is_copy_successful
    copied = demo.Task.objects.filter(project=target_project)
    assert copied.count() == item_count
    for task in copied:
        assert set(task.counterparts.all()) == set(target_counterparts)


@pytest.mark.django_db
def test_compound_copy_with_only_nullable_references():
    """
    Card points to Stage and Label through nullable FKs. Stage and Label ids do not
    overlap, so a filter built from the wrong model's ids drops the card.
    """
    project = Project.objects.create(name="P")
    # Shift Label ids away from Stage ids.
    other = Project.objects.create(name="other")
    for i in range(5):
        Label.objects.create(project=other, name=f"pad{i}")

    stage = Stage.objects.create(project=project, name="S")
    label = Label.objects.create(project=project, name="L")
    assert stage.id != label.id
    both = Card.objects.create(name="both", stage=stage, label=label)
    only_stage = Card.objects.create(name="only stage", stage=stage)
    only_label = Card.objects.create(name="only label", label=label)
    Card.objects.create(name="orphan")

    config = ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "stages": MakeCopy(ModelCopyConfig(model=Stage, field_copy_actions={"name": TAKE_FROM_ORIGIN})),
            "labels": MakeCopy(ModelCopyConfig(model=Label, field_copy_actions={"name": TAKE_FROM_ORIGIN})),
        },
        compound_copy_actions=[
            ModelCopyConfig(
                model=Card,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "stage": UpdateToCopied(Stage),
                    "label": UpdateToCopied(Label),
                },
            )
        ],
    )
    result = run_copy(config, input_data={"project_id": project.id})

    assert result.is_copy_successful
    copied_card_origins = set(result.copies_of(Card))
    assert copied_card_origins == {str(both.id), str(only_stage.id), str(only_label.id)}
    new_both = Card.objects.get(pk=result.copies_of(Card)[str(both.id)])
    assert str(new_both.stage_id) == result.copies_of(Stage)[str(stage.id)]
    assert str(new_both.label_id) == result.copies_of(Label)[str(label.id)]


@pytest.mark.django_db
def test_custom_primary_key_name():
    tag = Tag.objects.create(name="t")
    folder = Folder.objects.create(name="F")
    for i in range(3):
        Document.objects.create(folder=folder, name=f"d{i}").tags.add(tag)
    skipped = Document.objects.create(folder=folder, name="skip")

    config = ModelCopyConfig(
        model=Folder,
        filter_field_to_input_key={"pk": "folder_code"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "documents": MakeCopy(
                ModelCopyConfig(
                    model=Document,
                    field_copy_actions={"name": TAKE_FROM_ORIGIN, "tags": TAKE_FROM_ORIGIN},
                    ignore_condition=IgnoreCondition(
                        ignore_func=lambda model_extra_filter, **kwargs: list(
                            Document.objects.filter(model_extra_filter, name="skip")
                        )
                    ),
                )
            ),
        },
    )
    result = run_copy(config, input_data={"folder_code": folder.pk}, confirm_write=True)

    assert result.is_copy_successful
    assert result.ignored_map == {"Document": [skipped.pk]}
    new_folder = Folder.objects.get(pk=result.copies_of(Folder)[str(folder.pk)])
    assert new_folder.documents.count() == 3
    assert all(list(d.tags.all()) == [tag] for d in new_folder.documents.all())


@pytest.mark.django_db
def test_set_to_filter_on_model_with_custom_primary_key():
    origin = Folder.objects.create(name="shared")
    target = Folder.objects.create(name="shared")
    Document.objects.create(folder=origin, name="d")

    config = ModelCopyConfig(
        model=Document,
        filter_field_to_input_key={"folder_id": "folder_code"},
        static_filters=Q(name="d"),
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "folder": FieldCopyConfig(
                action=CopyActions.SET_TO_FILTER,
                reference_to=Folder,
                filter_config=FilterConfig(
                    filter_func=lambda referenced_instance_list, **kwargs: {
                        str(f.pk): str(target.pk) for f in referenced_instance_list
                    }
                ),
            ),
        },
    )
    result = run_copy(config, input_data={"folder_code": origin.pk})

    assert result.is_copy_successful
    assert target.documents.count() == 1


@pytest.mark.django_db
def test_uuid_primary_keys():
    tag = Tag.objects.create(name="t")
    workspace = Workspace.objects.create(name="W")
    for i in range(3):
        Page.objects.create(workspace=workspace, title=f"p{i}").tags.add(tag)

    config = ModelCopyConfig(
        model=Workspace,
        filter_field_to_input_key={"id": "workspace_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "pages": MakeCopy(
                ModelCopyConfig(
                    model=Page,
                    field_copy_actions={"title": TAKE_FROM_ORIGIN, "tags": TAKE_FROM_ORIGIN},
                )
            ),
        },
    )
    result = run_copy(config, input_data={"workspace_id": workspace.id})

    assert result.is_copy_successful
    new_workspace = Workspace.objects.get(pk=result.copies_of(Workspace)[str(workspace.id)])
    assert new_workspace.pages.count() == 3
    assert all(list(p.tags.all()) == [tag] for p in new_workspace.pages.all())


@pytest.mark.django_db
def test_falsy_input_value_is_a_valid_filter():
    project = Project.objects.create(name="P")
    Item.objects.create(project=project, name="first", position=0)
    Item.objects.create(project=project, name="second", position=1)

    config = ModelCopyConfig(
        model=Item,
        filter_field_to_input_key={"project_id": "project_id", "position": "position"},
        field_copy_actions={
            "project": TAKE_FROM_ORIGIN,
            "name": TAKE_FROM_ORIGIN,
            "position": TAKE_FROM_ORIGIN,
            "is_active": FieldCopyConfig(action=CopyActions.TAKE_FROM_INPUT, input_key="active"),
        },
    )
    result = run_copy(config, input_data={"project_id": project.id, "position": 0, "active": False})

    assert result.is_copy_successful
    assert len(result.copies_of(Item)) == 1
    copy_ = Item.objects.get(pk=next(iter(result.copies_of(Item).values())))
    assert copy_.name == "first"
    assert copy_.is_active is False


def two_projects_config(**kwargs) -> CopyistConfig:
    return CopyistConfig(
        model_configs=[
            ModelCopyConfig(
                model=demo.Project,
                filter_field_to_input_key={"id": "demo_project_id"},
                field_copy_actions={"name": TAKE_FROM_ORIGIN, "company": TAKE_FROM_ORIGIN},
            ),
            ModelCopyConfig(
                model=Project,
                filter_field_to_input_key={"id": "edge_project_id"},
                field_copy_actions={"name": TAKE_FROM_ORIGIN},
            ),
        ],
        **kwargs,
    )


@pytest.mark.django_db
@pytest.mark.invalid_config
def test_same_class_name_in_different_apps_fails_with_default_keys():
    demo_company = demo.Company.objects.create(name="C", address="A")
    demo_project = demo.Project.objects.create(name="demo", company=demo_company)
    edge_project = Project.objects.create(name="edge")

    with pytest.raises(ImproperlyConfigured, match="Project: demo.Project, edge_cases.Project"):
        run_copy(
            two_projects_config(),
            input_data={"demo_project_id": demo_project.id, "edge_project_id": edge_project.id},
        )
    assert demo.Project.objects.count() == 1
    assert Project.objects.count() == 1
    assert "copyist.E012" in {i.code for i in check_config(two_projects_config())}


@pytest.mark.django_db
@pytest.mark.parametrize("via", ["config", "run_copy"])
def test_same_class_name_in_different_apps_with_label_keys(via):
    demo_company = demo.Company.objects.create(name="C", address="A")
    demo_project = demo.Project.objects.create(name="demo", company=demo_company)
    edge_project = Project.objects.create(name="edge")

    input_data = {"demo_project_id": demo_project.id, "edge_project_id": edge_project.id}
    if via == "config":
        config = two_projects_config(map_keys=MapKeys.LABEL)
        assert check_config(config) == []
        result = run_copy(config, input_data=input_data)
    else:
        result = run_copy(two_projects_config(), input_data=input_data, map_keys=MapKeys.LABEL)

    assert result.is_copy_successful
    assert result.map_keys == MapKeys.LABEL
    assert set(result.output_map) == {"demo.Project", "edge_cases.Project"}
    new_demo = demo.Project.objects.get(pk=result.copies_of(demo.Project)[str(demo_project.pk)])
    new_edge = Project.objects.get(pk=result.copies_of(Project)[str(edge_project.pk)])
    assert (new_demo.name, new_edge.name) == ("demo", "edge")


@pytest.mark.django_db
def test_copies_of_ignores_a_same_named_model_that_was_not_copied():
    edge_project = Project.objects.create(name="edge")
    config = ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN},
    )
    result = run_copy(config, input_data={"project_id": edge_project.id})

    assert set(result.output_map) == {"Project"}
    assert result.model_labels == {"Project": "edge_cases.Project"}
    assert len(result.copies_of(Project)) == 1
    assert result.copies_of(demo.Project) == {}


def test_map_key_conflicts_cover_references_and_ignore_filters():
    from django_copyist import IgnoreFilter
    from django_copyist.config import find_map_key_conflicts, map_key_labels

    # UpdateToCopied(demo.Project) is looked up by key, so it conflicts with edge Project.
    by_reference = ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN},
        compound_copy_actions=[
            ModelCopyConfig(
                model=demo.Task,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "project": UpdateToCopied(demo.Project),
                },
            )
        ],
    )
    assert find_map_key_conflicts([by_reference]) == {
        "Project": ["demo.Project", "edge_cases.Project"]
    }

    by_ignore_filter = ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN},
        ignore_condition=IgnoreCondition(
            filter_conditions=[IgnoreFilter("x__in", demo.Project, "company")]
        ),
    )
    assert "Project" in find_map_key_conflicts([by_ignore_filter])

    # SET_TO_FILTER targets never become map keys.
    by_set_to_filter = ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "stages": MakeCopy(
                ModelCopyConfig(
                    model=Stage,
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "project": FieldCopyConfig(
                            action=CopyActions.SET_TO_FILTER,
                            reference_to=demo.Project,
                            filter_config=FilterConfig(filter_func=lambda **kwargs: {}),
                        ),
                    },
                )
            ),
        },
    )
    assert find_map_key_conflicts([by_set_to_filter]) == {}
    assert map_key_labels([by_set_to_filter], MapKeys.LABEL) == {
        "edge_cases.Project": "edge_cases.Project",
        "edge_cases.Stage": "edge_cases.Stage",
    }


@pytest.mark.django_db
def test_callbacks_receive_maps_in_the_configured_key_mode():
    project = Project.objects.create(name="P")
    Stage.objects.create(project=project, name="S")
    seen = []

    def postcopy(output_map, **kwargs):
        seen.append(set(output_map))

    def config():
        return ModelCopyConfig(
            model=Project,
            filter_field_to_input_key={"id": "project_id"},
            field_copy_actions={
                "name": TAKE_FROM_ORIGIN,
                "stages": MakeCopy(
                    ModelCopyConfig(
                        model=Stage,
                        field_copy_actions={"name": TAKE_FROM_ORIGIN},
                        postcopy_steps=[
                            PostcopyStep(
                                action=DataModificationActions.EXECUTE_FUNC, func=postcopy
                            )
                        ],
                    )
                ),
            },
        )

    run_copy(config(), input_data={"project_id": project.id})
    run_copy(config(), input_data={"project_id": project.id}, map_keys=MapKeys.LABEL)
    assert seen == [{"Project", "Stage"}, {"edge_cases.Project", "edge_cases.Stage"}]


@pytest.mark.django_db
def test_model_without_objects_manager():
    project = Project.objects.create(name="P")
    Note.records.create(project=project, text="hello")

    config = ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "notes": MakeCopy(ModelCopyConfig(model=Note, field_copy_actions={"text": TAKE_FROM_ORIGIN})),
        },
    )
    result = run_copy(config, input_data={"project_id": project.id})

    assert result.is_copy_successful
    assert Note.records.filter(text="hello").count() == 2


@pytest.mark.django_db
def test_request_object_still_works_directly():
    """The 0.1 entry point keeps working."""
    from django_copyist import Copyist

    project = Project.objects.create(name="P")
    request = CopyRequest(
        config=CopyistConfig(
            [
                ModelCopyConfig(
                    model=Project,
                    filter_field_to_input_key={"id": "project_id"},
                    field_copy_actions={"name": TAKE_FROM_ORIGIN},
                )
            ]
        ),
        input_data={"project_id": project.id},
    )
    result = Copyist(request).execute_copy_request()
    assert result.is_copy_successful
    assert Project.objects.count() == 2


@pytest.mark.django_db
@pytest.mark.invalid_config
def test_self_referencing_fk_with_update_to_copied_fails_clearly():
    from example.edge_cases.models import Category

    project = Project.objects.create(name="P")
    root = Category.objects.create(project=project, name="root")
    Category.objects.create(project=project, name="child", parent=root)
    config = ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "categories": MakeCopy(
                ModelCopyConfig(
                    model=Category,
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "parent": UpdateToCopied(Category),
                    },
                )
            ),
        },
    )
    issues = {i.code for i in check_config(config)}
    assert "copyist.E011" in issues
    with pytest.raises(ValueError, match="was not found in output map"):
        run_copy(config, input_data={"project_id": project.id})


@pytest.mark.django_db
def test_self_referencing_fk_from_origin_keeps_origin_parent():
    from example.edge_cases.models import Category

    project = Project.objects.create(name="P")
    root = Category.objects.create(project=project, name="root")
    Category.objects.create(project=project, name="child", parent=root)
    config = ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "categories": MakeCopy(
                ModelCopyConfig(
                    model=Category,
                    field_copy_actions={"name": TAKE_FROM_ORIGIN, "parent": TAKE_FROM_ORIGIN},
                )
            ),
        },
    )
    assert {(i.code, i.field) for i in check_config(config)} == {("copyist.W005", "parent")}
    result = run_copy(config, input_data={"project_id": project.id})
    new_project = Project.objects.get(pk=result.copies_of(Project)[str(project.pk)])
    new_child = new_project.categories.get(name="child")
    assert new_child.parent_id == root.pk


@pytest.mark.django_db
def test_manual_primary_key():
    from example.edge_cases.models import Country

    Country.objects.create(code="de", name="Germany")
    from_origin = ModelCopyConfig(
        model=Country,
        filter_field_to_input_key={"pk": "code"},
        field_copy_actions={"code": TAKE_FROM_ORIGIN, "name": TAKE_FROM_ORIGIN},
    )
    assert ("copyist.E005", "code") in {(i.code, i.field) for i in check_config(from_origin)}
    missing = ModelCopyConfig(
        model=Country,
        filter_field_to_input_key={"pk": "code"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN},
    )
    assert ("copyist.E004", "code") in {(i.code, i.field) for i in check_config(missing)}

    config = ModelCopyConfig(
        model=Country,
        filter_field_to_input_key={"pk": "code"},
        field_copy_actions={"code": TakeFromInput("new_code"), "name": TAKE_FROM_ORIGIN},
    )
    assert check_config(config) == []
    result = run_copy(config, input_data={"code": "de", "new_code": "at"})
    assert result.copies_of(Country) == {"de": "at"}
    assert Country.objects.get(pk="at").name == "Germany"
