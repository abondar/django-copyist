"""
User code that must type-check against the public API (``make typecheck``).

mypy checks this module in strict mode. It is never imported at runtime. Lines that
must be rejected carry ``# type: ignore[...]``: with ``warn_unused_ignores`` mypy fails
if such a line stops being an error.
"""

from typing import Any

from django.db.models import Model, Q

from django_copyist import (
    TAKE_FROM_ORIGIN,
    ConfigIssue,
    ConfigIssueLevel,
    CopyActions,
    CopyIntent,
    CopyistConfig,
    CopyResult,
    DataModificationActions,
    FieldCopyConfig,
    FieldFilterConfig,
    FieldSetToFilterMap,
    FilterConfig,
    FilterSource,
    IgnoreCondition,
    IgnoredMap,
    MakeCopy,
    MapKeys,
    ModelCopyConfig,
    OutputMap,
    PostcopyStep,
    SetToFilterMap,
    TakeFromInput,
    UpdateToCopied,
    check_config,
    run_copy,
)
from example.demo.models import Company, Counterpart, Employee, Project, Task


# Callbacks with the full signature.
def ignore_tasks(
    *,
    model_config: ModelCopyConfig,
    set_to_filter_map: SetToFilterMap,
    model_extra_filter: Q | None,
    ignored_map: IgnoredMap,
    input_data: dict[str, Any],
) -> list[Model]:
    return list(Task.objects.filter(model_extra_filter or Q(), name="skip"))


def match_counterparts(
    *,
    model_config: ModelCopyConfig,
    input_data: dict[str, Any],
    field_name: str,
    field_copy_config: FieldCopyConfig,
    set_to_filter_map: SetToFilterMap,
    instance_list: list[Model],
    referenced_instance_list: list[Model],
) -> FieldSetToFilterMap:
    return {str(i.pk): None for i in referenced_instance_list}


def log_copies(
    *,
    model_config: ModelCopyConfig,
    input_data: dict[str, Any],
    set_to_filter_map: SetToFilterMap,
    output_map: OutputMap,
    copy_intent_list: list[CopyIntent],
) -> None:
    for intent in copy_intent_list:
        print(intent.origin.pk, intent.copied.pk if intent.copied else None)


# Callbacks that take only the arguments they need.
def ignore_nothing(**kwargs: Any) -> list[Model]:
    return []


COMPANY_COPY_CONFIG = ModelCopyConfig(
    model=Company,
    filter_field_to_input_key={"id": "company_id"},
    field_copy_actions={
        "name": TakeFromInput("new_name"),
        "address": TAKE_FROM_ORIGIN,
        "projects": MakeCopy(
            ModelCopyConfig(
                model=Project,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "counterparts": MakeCopy(
                        ModelCopyConfig(
                            model=Counterpart,
                            field_copy_actions={
                                "name": TAKE_FROM_ORIGIN,
                                "external_id": TAKE_FROM_ORIGIN,
                            },
                        )
                    ),
                },
            )
        ),
        "employees": MakeCopy(
            ModelCopyConfig(
                model=Employee,
                field_copy_actions={"name": TAKE_FROM_ORIGIN},
                ignore_condition=IgnoreCondition(ignore_func=ignore_nothing),
            )
        ),
    },
    compound_copy_actions=[
        ModelCopyConfig(
            model=Task,
            field_copy_actions={
                "name": TAKE_FROM_ORIGIN,
                "description": TAKE_FROM_ORIGIN,
                "project": UpdateToCopied(Project),
                "assignee": UpdateToCopied(Employee),
                "counterparts": FieldCopyConfig(
                    action=CopyActions.SET_TO_FILTER,
                    reference_to=Counterpart,
                    filter_config=FilterConfig(filter_func=match_counterparts),
                ),
            },
            ignore_condition=IgnoreCondition(ignore_func=ignore_tasks),
            postcopy_steps=[
                PostcopyStep(action=DataModificationActions.EXECUTE_FUNC, func=log_copies)
            ],
        )
    ],
)

FILTER = FieldFilterConfig(source=FilterSource.FROM_INPUT, key="target_project_id")


def copy_company(company: Company) -> Company | None:
    issues: list[ConfigIssue] = check_config(COMPANY_COPY_CONFIG)
    if any(issue.level == ConfigIssueLevel.ERROR for issue in issues):
        return None

    result: CopyResult = run_copy(
        COMPANY_COPY_CONFIG,
        input_data={"company_id": company.pk, "new_name": f"{company.name} (copy)"},
        using="default",
        batch_size=500,
    )
    if not result.is_copy_successful:
        return None
    copies: dict[str, str] = result.copies_of(Company)
    return Company.objects.get(pk=copies[str(company.pk)])


def copy_with_labels(config: ModelCopyConfig) -> OutputMap | None:
    result = run_copy(
        CopyistConfig([config], map_keys=MapKeys.LABEL),
        input_data={},
        confirm_write=True,
    )
    return result.output_map


# Mistakes that the types must reject.
run_copy(COMPANY_COPY_CONFIG, input_data=[("company_id", 1)])  # type: ignore[arg-type]
run_copy(COMPANY_COPY_CONFIG, {}, batch_size="500")  # type: ignore[arg-type]
CopyistConfig([COMPANY_COPY_CONFIG], map_keys="label")  # type: ignore[arg-type]
IgnoreCondition(ignore_func=lambda: [])  # type: ignore[arg-type]
