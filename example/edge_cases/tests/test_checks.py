import pytest
from django.core.exceptions import ImproperlyConfigured

from django_copyist import (
    TAKE_FROM_ORIGIN,
    ConfigIssueLevel,
    CopyActions,
    CopyistConfig,
    FieldCopyConfig,
    FieldFilterConfig,
    FilterConfig,
    FilterSource,
    MakeCopy,
    ModelCopyConfig,
    TakeFromInput,
    UpdateToCopied,
    check_config,
)
from example.demo import models as demo
from example.edge_cases.models import (
    Card,
    Item,
    Label,
    Place,
    Project,
    Restaurant,
    Stage,
    Tag,
    Ticket,
    TicketWatcher,
)


def codes(config, level=None):
    return {
        (i.code, i.model, i.field)
        for i in check_config(config)
        if level is None or i.level == level
    }


def project_root(**field_copy_actions):
    return ModelCopyConfig(
        model=Project,
        filter_field_to_input_key={"id": "project_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN, **field_copy_actions},
    )


def test_valid_config_has_no_issues():
    config = project_root(
        items=MakeCopy(
            ModelCopyConfig(
                model=Item,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "position": TAKE_FROM_ORIGIN,
                    "is_active": TAKE_FROM_ORIGIN,
                    "tags": TAKE_FROM_ORIGIN,
                },
            )
        )
    )
    assert check_config(config) == []
    assert check_config(CopyistConfig([config])) == []


def test_unknown_field():
    assert ("copyist.E001", "edge_cases.Project", "nmae") in codes(
        project_root(nmae=TAKE_FROM_ORIGIN)
    )


@pytest.mark.parametrize(
    "field_name, action",
    [
        ("items", TAKE_FROM_ORIGIN),
        ("items", TakeFromInput("x")),
        ("name", MakeCopy(ModelCopyConfig(model=Item, field_copy_actions={}))),
        ("name", UpdateToCopied(Project)),
    ],
)
def test_action_does_not_fit_field_kind(field_name, action):
    assert ("copyist.E002", "edge_cases.Project", field_name) in codes(
        project_root(**{field_name: action})
    )


def test_make_copy_on_forward_fk_is_rejected():
    config = ModelCopyConfig(
        model=Item,
        filter_field_to_input_key={"id": "item_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "project": MakeCopy(
                ModelCopyConfig(model=Project, field_copy_actions={"name": TAKE_FROM_ORIGIN})
            ),
        },
    )
    issues = codes(config, ConfigIssueLevel.ERROR)
    assert ("copyist.E002", "edge_cases.Item", "project") in issues


def test_reference_mismatch():
    config = project_root(
        stages=MakeCopy(ModelCopyConfig(model=Stage, field_copy_actions={"name": TAKE_FROM_ORIGIN})),
        labels=MakeCopy(ModelCopyConfig(model=Card, field_copy_actions={"name": TAKE_FROM_ORIGIN})),
    )
    assert ("copyist.E003", "edge_cases.Project", "labels") in codes(config)

    config = project_root(
        stages=MakeCopy(
            ModelCopyConfig(
                model=Stage,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "cards": MakeCopy(
                        ModelCopyConfig(
                            model=Card,
                            field_copy_actions={
                                "name": TAKE_FROM_ORIGIN,
                                "label": UpdateToCopied(Stage),
                            },
                        )
                    ),
                },
            )
        )
    )
    assert ("copyist.E003", "edge_cases.Card", "label") in codes(config)


def test_set_to_filter_reference_mismatch():
    config = ModelCopyConfig(
        model=Item,
        filter_field_to_input_key={"id": "item_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "project": FieldCopyConfig(
                action=CopyActions.SET_TO_FILTER,
                reference_to=Tag,
                filter_config=FilterConfig(
                    filters={"name": FieldFilterConfig(source=FilterSource.FROM_ORIGIN)}
                ),
            ),
        },
    )
    assert ("copyist.E003", "edge_cases.Item", "project") in codes(config)


def test_required_field_without_default():
    config = ModelCopyConfig(
        model=Item,
        filter_field_to_input_key={"id": "item_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN},
    )
    errors = codes(config, ConfigIssueLevel.ERROR)
    assert ("copyist.E004", "edge_cases.Item", "project") in errors


def test_fk_can_be_covered_by_attname():
    config = ModelCopyConfig(
        model=Item,
        filter_field_to_input_key={"id": "item_id"},
        field_copy_actions={
            "project_id": TakeFromInput("new_project_id"),
            "name": TAKE_FROM_ORIGIN,
            "position": TAKE_FROM_ORIGIN,
            "is_active": TAKE_FROM_ORIGIN,
            "tags": TAKE_FROM_ORIGIN,
        },
    )
    assert check_config(config) == []


def test_parent_fk_of_nested_config_counts_as_covered():
    config = project_root(
        stages=MakeCopy(ModelCopyConfig(model=Stage, field_copy_actions={"name": TAKE_FROM_ORIGIN}))
    )
    assert codes(config, ConfigIssueLevel.ERROR) == set()


def test_unique_field_from_origin():
    config = project_root(
        tickets=MakeCopy(
            ModelCopyConfig(
                model=Ticket,
                field_copy_actions={"title": TAKE_FROM_ORIGIN, "slug": TAKE_FROM_ORIGIN},
            )
        )
    )
    assert ("copyist.E005", "edge_cases.Ticket", "slug") in codes(config)


def test_through_model_with_required_column():
    config = project_root(
        tickets=MakeCopy(
            ModelCopyConfig(
                model=Ticket,
                field_copy_actions={
                    "title": TAKE_FROM_ORIGIN,
                    "slug": TakeFromInput("slug"),
                    "watchers": TAKE_FROM_ORIGIN,
                },
            )
        )
    )
    assert ("copyist.E006", "edge_cases.Ticket", "watchers") in codes(config)


def test_through_model_copied_as_child_is_fine():
    config = project_root(
        tickets=MakeCopy(
            ModelCopyConfig(
                model=Ticket,
                field_copy_actions={
                    "title": TAKE_FROM_ORIGIN,
                    "slug": TakeFromInput("slug"),
                    "priority": TAKE_FROM_ORIGIN,
                    "ticketwatcher_set": MakeCopy(
                        ModelCopyConfig(
                            model=TicketWatcher,
                            field_copy_actions={"tag": TAKE_FROM_ORIGIN, "role": TAKE_FROM_ORIGIN},
                        )
                    ),
                },
            )
        )
    )
    assert check_config(config) == []


def test_multi_table_inheritance():
    config = ModelCopyConfig(
        model=Restaurant,
        filter_field_to_input_key={"id": "id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN, "serves_pizza": TAKE_FROM_ORIGIN},
    )
    assert codes(config, ConfigIssueLevel.ERROR) == {
        ("copyist.E007", "edge_cases.Restaurant", None)
    }


def test_root_without_filter():
    config = ModelCopyConfig(model=Place, field_copy_actions={"name": TAKE_FROM_ORIGIN})
    assert codes(config) == {("copyist.E008", "edge_cases.Place", None)}


def test_model_configured_twice():
    stage = ModelCopyConfig(model=Stage, field_copy_actions={"name": TAKE_FROM_ORIGIN})
    config = CopyistConfig(
        [
            project_root(stages=MakeCopy(stage)),
            ModelCopyConfig(
                model=Stage,
                filter_field_to_input_key={"id": "stage_id"},
                field_copy_actions={"name": TAKE_FROM_ORIGIN, "project": TAKE_FROM_ORIGIN},
            ),
        ]
    )
    errors = [i for i in check_config(config) if i.code == "copyist.E009"]
    assert len(errors) == 1


def test_update_to_copied_needs_copied_model():
    config = ModelCopyConfig(
        model=Card,
        filter_field_to_input_key={"id": "card_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN, "stage": UpdateToCopied(Stage)},
    )
    assert ("copyist.E010", "edge_cases.Card", "stage") in codes(config)


def test_warnings_for_fields_left_out():
    config = ModelCopyConfig(
        model=Item,
        filter_field_to_input_key={"id": "item_id"},
        field_copy_actions={"project": TAKE_FROM_ORIGIN},
    )
    warnings = codes(config, ConfigIssueLevel.WARNING)
    assert warnings == {
        ("copyist.W001", "edge_cases.Item", "name"),
        ("copyist.W001", "edge_cases.Item", "position"),
        ("copyist.W001", "edge_cases.Item", "is_active"),
        ("copyist.W003", "edge_cases.Item", "tags"),
    }


def test_unique_set_copied_from_origin():
    root = ModelCopyConfig(
        model=Label,
        filter_field_to_input_key={"id": "label_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN, "project": TAKE_FROM_ORIGIN},
    )
    assert codes(root) == {("copyist.W002", "edge_cases.Label", None)}

    # Nested under the copied project, the parent FK changes, so the set stays unique.
    nested = project_root(
        labels=MakeCopy(ModelCopyConfig(model=Label, field_copy_actions={"name": TAKE_FROM_ORIGIN}))
    )
    assert check_config(nested) == []


def test_company_has_no_issues():
    config = ModelCopyConfig(
        model=demo.Company,
        filter_field_to_input_key={"id": "company_id"},
        field_copy_actions={"name": TAKE_FROM_ORIGIN, "address": TAKE_FROM_ORIGIN},
    )
    assert check_config(config) == []


def test_raise_on_error():
    config = project_root(nmae=TAKE_FROM_ORIGIN)
    with pytest.raises(ImproperlyConfigured, match="copyist.E001"):
        check_config(config, raise_on_error=True)
    # Warnings do not raise.
    warning_only = ModelCopyConfig(
        model=Item,
        filter_field_to_input_key={"id": "item_id"},
        field_copy_actions={"project": TAKE_FROM_ORIGIN},
    )
    assert check_config(warning_only, raise_on_error=True)


def test_issue_str_and_order():
    config = ModelCopyConfig(
        model=Item,
        filter_field_to_input_key={"id": "item_id"},
        field_copy_actions={"nmae": TAKE_FROM_ORIGIN},
    )
    issues = check_config(config)
    assert issues[0].level == ConfigIssueLevel.ERROR
    assert issues[-1].level == ConfigIssueLevel.WARNING
    assert str(issues[0]).startswith("copyist.E")
    assert "edge_cases.Item" in str(issues[0])


def test_labels_reference_unknown_model_kind():
    config = project_root(
        labels=MakeCopy(ModelCopyConfig(model=Label, field_copy_actions={"name": TAKE_FROM_ORIGIN}))
    )
    assert check_config(config) == []
