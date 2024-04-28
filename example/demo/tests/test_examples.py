from typing import Any, List

import pytest
from django.db.models import Model, Q

from django_copyist.config import (
    TAKE_FROM_ORIGIN,
    CopyActions,
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
    UpdateToCopied,
)
from django_copyist.copy_request import AbortReason, CopyRequest
from django_copyist.copyist import (
    CopyIntent,
    Copyist,
    CopyistConfig,
    FieldSetToFilterMap,
    IgnoredMap,
    OutputMap,
    SetToFilterMap,
)
from example.demo.models import Company, Counterpart, Employee, Project, Task


@pytest.mark.django_db
def test_copy_diamond_hierarchy():
    company = Company.objects.create(name="Company", address="Address")
    project = Project.objects.create(name="Project", company=company)
    counterpart = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project
    )
    counterpart2 = Counterpart.objects.create(
        name="Counterpart2", external_id=2, project=project
    )

    employee = Employee.objects.create(name="Employee", company=company)
    task = Task.objects.create(
        name="Task",
        description="Description",
        assignee=employee,
        project=project,
    )
    task.counterparts.add(counterpart, counterpart2)

    config = ModelCopyConfig(
        model=Company,
        filter_field_to_input_key={"id": "company_id"},
        field_copy_actions={
            "name": FieldCopyConfig(
                action=CopyActions.TAKE_FROM_INPUT,
                input_key="new_company_name",
            ),
            "address": FieldCopyConfig(
                action=CopyActions.TAKE_FROM_INPUT,
                input_key="new_company_address",
            ),
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
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                    },
                )
            ),
        },
        compound_copy_actions=[
            ModelCopyConfig(
                model=Task,
                field_copy_actions={
                    "name": TAKE_FROM_ORIGIN,
                    "description": TAKE_FROM_ORIGIN,
                    "counterparts": UpdateToCopied(Counterpart),
                    "project": UpdateToCopied(Project),
                    "assignee": UpdateToCopied(Employee),
                },
            )
        ],
    )

    new_company_name = "New Company"
    new_company_address = "New Address"
    copy_request = CopyRequest(
        config=CopyistConfig([config]),
        input_data={
            "company_id": company.id,
            "new_company_name": new_company_name,
            "new_company_address": new_company_address,
        },
        confirm_write=False,
    )
    result = Copyist(copy_request).execute_copy_request()

    assert result.is_copy_successful
    assert len(result.output_map["Company"]) == 1

    company_copy_id = result.output_map["Company"][str(company.id)]
    new_company = Company.objects.get(id=company_copy_id)
    assert new_company.name == new_company_name
    assert new_company.address == new_company_address
    assert new_company.id != company.id

    assert len(result.output_map["Project"]) == 1
    project_copy_id = result.output_map["Project"][str(project.id)]
    new_project = Project.objects.get(id=project_copy_id)
    assert new_project.name == project.name
    assert new_project.company_id == new_company.id
    assert new_project.id != project.id

    assert len(result.output_map["Counterpart"]) == 2
    new_counterparts = Counterpart.objects.filter(project_id=new_project.id)
    assert len(new_counterparts) == 2

    assert not (
        {counterpart.id, counterpart2.id}
        & {new_counterpart.id for new_counterpart in new_counterparts}
    )

    assert len(result.output_map["Employee"]) == 1
    employee_copy_id = result.output_map["Employee"][str(employee.id)]
    new_employee = Employee.objects.get(id=employee_copy_id)
    assert new_employee.name == employee.name
    assert new_employee.company_id == new_company.id
    assert new_employee.id != employee.id

    assert len(result.output_map["Task"]) == 1
    task_copy_id = result.output_map["Task"][str(task.id)]
    new_task = Task.objects.get(id=task_copy_id)
    assert new_task.name == task.name
    assert new_task.description == task.description

    assert new_task.assignee_id == new_employee.id
    assert new_task.project_id == new_project.id
    assert new_task.id != task.id

    assert new_task.counterparts.count() == 2
    assert set(new_task.counterparts.values_list("id", flat=True)) == {
        new_counterpart.id for new_counterpart in new_counterparts
    }


@pytest.mark.django_db
def test_take_from_origin():
    company = Company.objects.create(name="Company", address="Address")

    config = ModelCopyConfig(
        model=Company,
        filter_field_to_input_key={"id": "company_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "address": TAKE_FROM_ORIGIN,
        },
    )
    copy_request = CopyRequest(
        config=CopyistConfig([config]),
        input_data={"company_id": company.id},
        confirm_write=False,
    )
    result = Copyist(copy_request).execute_copy_request()
    assert result.is_copy_successful
    assert len(result.output_map["Company"]) == 1
    new_company_id = result.output_map["Company"][str(company.id)]
    new_company = Company.objects.get(id=new_company_id)
    assert new_company.name == company.name


@pytest.mark.django_db
def test_take_from_input():
    company = Company.objects.create(name="Company", address="Address")

    config = ModelCopyConfig(
        model=Company,
        filter_field_to_input_key={"id": "company_id"},
        field_copy_actions={
            "name": FieldCopyConfig(
                action=CopyActions.TAKE_FROM_INPUT, input_key="new_name"
            ),
            "address": TAKE_FROM_ORIGIN,
        },
    )
    copy_request = CopyRequest(
        config=CopyistConfig([config]),
        input_data={"company_id": company.id, "new_name": "New Company"},
        confirm_write=False,
    )
    result = Copyist(copy_request).execute_copy_request()
    assert result.is_copy_successful
    assert len(result.output_map["Company"]) == 1
    new_company_id = result.output_map["Company"][str(company.id)]
    new_company = Company.objects.get(id=new_company_id)
    assert new_company.name == "New Company"


@pytest.mark.django_db
def test_set_to_filter():
    company = Company.objects.create(name="Company", address="Address")
    project1 = Project.objects.create(name="Project1", company=company)
    project2 = Project.objects.create(name="Project2", company=company)
    counterpart1 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project1
    )
    counterpart2 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project2
    )
    employee = Employee.objects.create(name="Employee", company=company)
    task = Task.objects.create(
        name="Task",
        description="Description",
        assignee=employee,
        project=project1,
    )
    task.counterparts.add(counterpart1)

    config = ModelCopyConfig(
        model=Employee,
        filter_field_to_input_key={"id": "employee_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "company": TAKE_FROM_ORIGIN,
            "tasks": MakeCopy(
                ModelCopyConfig(
                    model=Task,
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "description": TAKE_FROM_ORIGIN,
                        "project_id": FieldCopyConfig(
                            action=CopyActions.TAKE_FROM_INPUT,
                            input_key="new_project_id",
                        ),
                        "counterparts": FieldCopyConfig(
                            action=CopyActions.SET_TO_FILTER,
                            reference_to=Counterpart,
                            filter_config=FilterConfig(
                                filters={
                                    "project_id": FieldFilterConfig(
                                        source=FilterSource.FROM_INPUT,
                                        key="new_project_id",
                                    ),
                                    "external_id": FieldFilterConfig(
                                        source=FilterSource.FROM_ORIGIN
                                    ),
                                }
                            ),
                        ),
                    },
                )
            ),
        },
    )

    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "employee_id": employee.id,
                "new_project_id": project2.id,
            },
            confirm_write=False,
        )
    ).execute_copy_request()

    assert result.is_copy_successful
    assert len(result.output_map["Employee"]) == 1
    assert len(result.output_map["Task"]) == 1

    new_task_id = result.output_map["Task"][str(task.id)]
    new_task = Task.objects.get(id=new_task_id)
    assert new_task.project_id == project2.id
    assert new_task.counterparts.count() == 1
    new_counterpart = new_task.counterparts.first()
    assert new_counterpart.project_id == project2.id
    assert new_counterpart.external_id == counterpart2.external_id
    assert new_counterpart.id != counterpart1.id
    assert new_counterpart.id == counterpart2.id


@pytest.mark.django_db
def test_set_to_filter_not_found():
    company = Company.objects.create(name="Company", address="Address")
    project1 = Project.objects.create(name="Project1", company=company)
    project2 = Project.objects.create(name="Project2", company=company)
    counterpart1 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project1
    )
    counterpart2 = Counterpart.objects.create(
        name="Counterpart 2", external_id=2, project=project1
    )
    counterpart3 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project2
    )
    employee = Employee.objects.create(name="Employee", company=company)
    task = Task.objects.create(
        name="Task",
        description="Description",
        assignee=employee,
        project=project1,
    )
    task.counterparts.add(counterpart1, counterpart2)

    config = ModelCopyConfig(
        model=Employee,
        filter_field_to_input_key={"id": "employee_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "company": TAKE_FROM_ORIGIN,
            "tasks": MakeCopy(
                ModelCopyConfig(
                    model=Task,
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "description": TAKE_FROM_ORIGIN,
                        "project_id": FieldCopyConfig(
                            action=CopyActions.TAKE_FROM_INPUT,
                            input_key="new_project_id",
                        ),
                        "counterparts": FieldCopyConfig(
                            action=CopyActions.SET_TO_FILTER,
                            reference_to=Counterpart,
                            filter_config=FilterConfig(
                                filters={
                                    "project_id": FieldFilterConfig(
                                        source=FilterSource.FROM_INPUT,
                                        key="new_project_id",
                                    ),
                                    "external_id": FieldFilterConfig(
                                        source=FilterSource.FROM_ORIGIN
                                    ),
                                }
                            ),
                        ),
                    },
                )
            ),
        },
    )

    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "employee_id": employee.id,
                "new_project_id": project2.id,
            },
            confirm_write=False,
        )
    ).execute_copy_request()

    assert not result.is_copy_successful
    assert result.reason == AbortReason.NOT_MATCHED
    assert result.set_to_filter_map[Task.__name__]["counterparts"] == {
        str(counterpart1.id): str(counterpart3.id),
        str(counterpart2.id): None,
    }

    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "employee_id": employee.id,
                "new_project_id": project2.id,
            },
            confirm_write=True,
            set_to_filter_map=result.set_to_filter_map,
            ignored_map=result.ignored_map,
        )
    ).execute_copy_request()

    assert result.is_copy_successful

    new_task_id = result.output_map["Task"][str(task.id)]
    new_task = Task.objects.get(id=new_task_id)
    assert new_task.counterparts.count() == 1


@pytest.mark.django_db
def test_set_to_filter_by_func():
    company = Company.objects.create(name="Company", address="Address")
    project1 = Project.objects.create(name="Project1", company=company)
    project2 = Project.objects.create(name="Project2", company=company)
    counterpart1 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project1
    )
    counterpart2 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project2
    )
    employee = Employee.objects.create(name="Employee", company=company)
    task = Task.objects.create(
        name="Task",
        description="Description",
        assignee=employee,
        project=project1,
    )
    task.counterparts.add(counterpart1)

    def match_counterparts(
        model_config: "ModelCopyConfig",
        input_data: dict[str, Any],
        field_name: str,
        field_copy_config: "FieldCopyConfig",
        set_to_filter_map: "SetToFilterMap",
        instance_list: list[Model],
        referenced_instance_list: list[Model],
    ) -> "FieldSetToFilterMap":
        original_counterparts = Counterpart.objects.filter(
            tasks__id__in=[task.id for task in instance_list],
        )
        new_counterparts = Counterpart.objects.filter(
            project_id=input_data["new_project_id"],
            external_id__in=[cp.external_id for cp in original_counterparts],
        )
        external_id_to_new_counterpart = {cp.external_id: cp for cp in new_counterparts}
        return {
            str(cp.id): (
                str(external_id_to_new_counterpart[cp.external_id].id)
                if cp.external_id in external_id_to_new_counterpart
                else None
            )
            for cp in original_counterparts
        }

    config = ModelCopyConfig(
        model=Employee,
        filter_field_to_input_key={"id": "employee_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "company": TAKE_FROM_ORIGIN,
            "tasks": MakeCopy(
                ModelCopyConfig(
                    model=Task,
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "description": TAKE_FROM_ORIGIN,
                        "project_id": FieldCopyConfig(
                            action=CopyActions.TAKE_FROM_INPUT,
                            input_key="new_project_id",
                        ),
                        "counterparts": FieldCopyConfig(
                            action=CopyActions.SET_TO_FILTER,
                            reference_to=Counterpart,
                            filter_config=FilterConfig(
                                filter_func=match_counterparts,
                            ),
                        ),
                    },
                )
            ),
        },
    )

    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "employee_id": employee.id,
                "new_project_id": project2.id,
            },
            confirm_write=False,
        )
    ).execute_copy_request()

    assert result.is_copy_successful
    assert len(result.output_map["Employee"]) == 1
    assert len(result.output_map["Task"]) == 1

    new_task_id = result.output_map["Task"][str(task.id)]
    new_task = Task.objects.get(id=new_task_id)
    assert new_task.project_id == project2.id
    assert new_task.counterparts.count() == 1
    new_counterpart = new_task.counterparts.first()
    assert new_counterpart.project_id == project2.id
    assert new_counterpart.external_id == counterpart2.external_id
    assert new_counterpart.id != counterpart1.id
    assert new_counterpart.id == counterpart2.id


@pytest.mark.django_db
def test_ignore_condition():
    company = Company.objects.create(name="Company", address="Address")
    project1 = Project.objects.create(name="Project1", company=company)
    project2 = Project.objects.create(name="Project2", company=company)
    counterpart1 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project1
    )
    counterpart2 = Counterpart.objects.create(
        name="Counterpart 2", external_id=2, project=project1
    )
    counterpart3 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project2
    )
    employee = Employee.objects.create(name="Employee", company=company)
    task1 = Task.objects.create(
        name="Task",
        description="Description",
        assignee=employee,
        project=project1,
    )
    task1.counterparts.add(counterpart1, counterpart2)
    task2 = Task.objects.create(
        name="Task 2",
        description="Description",
        assignee=employee,
        project=project1,
    )
    task2.counterparts.add(counterpart1)

    config = ModelCopyConfig(
        model=Employee,
        filter_field_to_input_key={"id": "employee_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "company": TAKE_FROM_ORIGIN,
            "tasks": MakeCopy(
                ModelCopyConfig(
                    model=Task,
                    ignore_condition=IgnoreCondition(
                        filter_conditions=[
                            IgnoreFilter(
                                filter_name="counterparts__id__in",
                                set_to_filter_field_name="counterparts",
                                set_to_filter_origin_model=Task,
                            )
                        ]
                    ),
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "description": TAKE_FROM_ORIGIN,
                        "project_id": FieldCopyConfig(
                            action=CopyActions.TAKE_FROM_INPUT,
                            input_key="new_project_id",
                        ),
                        "counterparts": FieldCopyConfig(
                            action=CopyActions.SET_TO_FILTER,
                            reference_to=Counterpart,
                            filter_config=FilterConfig(
                                filters={
                                    "project_id": FieldFilterConfig(
                                        source=FilterSource.FROM_INPUT,
                                        key="new_project_id",
                                    ),
                                    "external_id": FieldFilterConfig(
                                        source=FilterSource.FROM_ORIGIN
                                    ),
                                }
                            ),
                        ),
                    },
                )
            ),
        },
    )

    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "employee_id": employee.id,
                "new_project_id": project2.id,
            },
            confirm_write=False,
        )
    ).execute_copy_request()

    assert not result.is_copy_successful
    assert result.reason == AbortReason.IGNORED

    assert result.ignored_map[Task.__name__] == [task1.id]

    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "employee_id": employee.id,
                "new_project_id": project2.id,
            },
            confirm_write=True,
            set_to_filter_map=result.set_to_filter_map,
            ignored_map=result.ignored_map,
        )
    ).execute_copy_request()

    assert result.is_copy_successful

    new_tasks = Task.objects.filter(project=project2)
    assert len(new_tasks) == 1
    assert new_tasks[0].name == task2.name


@pytest.mark.django_db
def test_ignore_condition_nested():
    company = Company.objects.create(name="Company", address="Address")
    project1 = Project.objects.create(name="Project1", company=company)
    project2 = Project.objects.create(name="Project2", company=company)
    counterpart1 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project1
    )
    counterpart2 = Counterpart.objects.create(
        name="Counterpart 2", external_id=2, project=project1
    )
    counterpart3 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project2
    )
    employee = Employee.objects.create(name="Employee", company=company)
    task1 = Task.objects.create(
        name="Task",
        description="Description",
        assignee=employee,
        project=project1,
    )
    task1.counterparts.add(counterpart1, counterpart2)
    task2 = Task.objects.create(
        name="Task 2",
        description="Description",
        assignee=employee,
        project=project1,
    )
    task2.counterparts.add(counterpart1)

    config = ModelCopyConfig(
        model=Employee,
        filter_field_to_input_key={"id": "employee_id"},
        ignore_condition=IgnoreCondition(
            filter_conditions=[
                IgnoreFilter(
                    filter_name="tasks__counterparts__id__in",
                    set_to_filter_field_name="counterparts",
                    set_to_filter_origin_model=Task,
                )
            ]
        ),
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "company": TAKE_FROM_ORIGIN,
            "tasks": MakeCopy(
                ModelCopyConfig(
                    model=Task,
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "description": TAKE_FROM_ORIGIN,
                        "project_id": FieldCopyConfig(
                            action=CopyActions.TAKE_FROM_INPUT,
                            input_key="new_project_id",
                        ),
                        "counterparts": FieldCopyConfig(
                            action=CopyActions.SET_TO_FILTER,
                            reference_to=Counterpart,
                            filter_config=FilterConfig(
                                filters={
                                    "project_id": FieldFilterConfig(
                                        source=FilterSource.FROM_INPUT,
                                        key="new_project_id",
                                    ),
                                    "external_id": FieldFilterConfig(
                                        source=FilterSource.FROM_ORIGIN
                                    ),
                                }
                            ),
                        ),
                    },
                )
            ),
        },
    )

    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "employee_id": employee.id,
                "new_project_id": project2.id,
            },
            confirm_write=False,
        )
    ).execute_copy_request()

    assert not result.is_copy_successful
    assert result.reason == AbortReason.IGNORED

    assert result.ignored_map[Employee.__name__] == [employee.id]


@pytest.mark.django_db
def test_ignore_condition_with_func():
    company = Company.objects.create(name="Company", address="Address")
    project1 = Project.objects.create(name="Project1", company=company)
    project2 = Project.objects.create(name="Project2", company=company)
    counterpart1 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project1
    )
    counterpart2 = Counterpart.objects.create(
        name="Counterpart 2", external_id=2, project=project1
    )
    counterpart3 = Counterpart.objects.create(
        name="Counterpart", external_id=1, project=project2
    )
    employee = Employee.objects.create(name="Employee", company=company)
    task1 = Task.objects.create(
        name="Task",
        description="Description",
        assignee=employee,
        project=project1,
    )
    task1.counterparts.add(counterpart1, counterpart2)
    task2 = Task.objects.create(
        name="Task 2",
        description="Description",
        assignee=employee,
        project=project1,
    )
    task2.counterparts.add(counterpart1)

    def ignore_tasks(
        model_config: "ModelCopyConfig",
        set_to_filter_map: "SetToFilterMap",
        model_extra_filter: Q | None,
        ignored_map: "IgnoredMap",
        input_data: dict[str, Any],
    ) -> list[Model]:
        not_matched_counterparts = {
            key
            for key, value in set_to_filter_map[Task.__name__]["counterparts"].items()
            if value is None
        }
        query = Task.objects.filter(counterparts__id__in=not_matched_counterparts)
        if model_extra_filter:
            query = query.filter(model_extra_filter)
        return list(query)

    config = ModelCopyConfig(
        model=Employee,
        filter_field_to_input_key={"id": "employee_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "company": TAKE_FROM_ORIGIN,
            "tasks": MakeCopy(
                ModelCopyConfig(
                    model=Task,
                    ignore_condition=IgnoreCondition(
                        ignore_func=ignore_tasks,
                    ),
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                        "description": TAKE_FROM_ORIGIN,
                        "project_id": FieldCopyConfig(
                            action=CopyActions.TAKE_FROM_INPUT,
                            input_key="new_project_id",
                        ),
                        "counterparts": FieldCopyConfig(
                            action=CopyActions.SET_TO_FILTER,
                            reference_to=Counterpart,
                            filter_config=FilterConfig(
                                filters={
                                    "project_id": FieldFilterConfig(
                                        source=FilterSource.FROM_INPUT,
                                        key="new_project_id",
                                    ),
                                    "external_id": FieldFilterConfig(
                                        source=FilterSource.FROM_ORIGIN
                                    ),
                                }
                            ),
                        ),
                    },
                )
            ),
        },
    )

    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "employee_id": employee.id,
                "new_project_id": project2.id,
            },
            confirm_write=False,
        )
    ).execute_copy_request()

    assert not result.is_copy_successful
    assert result.reason == AbortReason.IGNORED

    assert result.ignored_map[Task.__name__] == [task1.id]

    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "employee_id": employee.id,
                "new_project_id": project2.id,
            },
            confirm_write=True,
            set_to_filter_map=result.set_to_filter_map,
            ignored_map=result.ignored_map,
        )
    ).execute_copy_request()

    assert result.is_copy_successful

    new_tasks = Task.objects.filter(project=project2)
    assert len(new_tasks) == 1
    assert new_tasks[0].name == task2.name


@pytest.mark.django_db
def test_static_filters():
    company = Company.objects.create(name="Company", address="Address")
    employee = Employee.objects.create(name="Employee", company=company)
    employee2 = Employee.objects.create(name="Employee 2 [FIRED]", company=company)

    config = ModelCopyConfig(
        model=Company,
        filter_field_to_input_key={"id": "company_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "address": TAKE_FROM_ORIGIN,
            "employees": MakeCopy(
                ModelCopyConfig(
                    model=Employee,
                    static_filters=~Q(name__icontains="[FIRED]"),
                    field_copy_actions={
                        "name": TAKE_FROM_ORIGIN,
                    },
                )
            ),
        },
    )
    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={"company_id": company.id},
            confirm_write=False,
        )
    ).execute_copy_request()

    assert result.is_copy_successful
    assert len(result.output_map["Company"]) == 1
    assert len(result.output_map["Employee"]) == 1

    new_company_id = result.output_map["Company"][str(company.id)]
    new_employees = Employee.objects.filter(company_id=new_company_id)
    assert len(new_employees) == 1
    new_employee = new_employees[0]
    assert new_employee.name == employee.name


@pytest.mark.django_db
def test_data_preparation_steps():
    company = Company.objects.create(name="Company", address="Address")
    project1 = Project.objects.create(name="Project1", company=company)
    project2 = Project.objects.create(name="Project2", company=company)
    counterpart11 = Counterpart.objects.create(
        name="11", external_id=1, project=project1
    )
    counterpart12 = Counterpart.objects.create(
        name="12", external_id=2, project=project1
    )
    counterpart21 = Counterpart.objects.create(
        name="21", external_id=1, project=project2
    )
    counterpart23 = Counterpart.objects.create(
        name="23", external_id=3, project=project2
    )

    config = ModelCopyConfig(
        model=Counterpart,
        filter_field_to_input_key={"project_id": "source_project_id"},
        data_preparation_steps=[
            DataPreparationStep(
                action=DataModificationActions.DELETE_BY_FILTER,
                filter_field_to_input_key={"project_id": "new_project_id"},
            )
        ],
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "external_id": TAKE_FROM_ORIGIN,
            "project_id": FieldCopyConfig(
                action=CopyActions.TAKE_FROM_INPUT,
                input_key="new_project_id",
            ),
        },
    )
    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "source_project_id": project1.id,
                "new_project_id": project2.id,
            },
            confirm_write=False,
        )
    ).execute_copy_request()

    assert result.is_copy_successful

    new_counterparts = list(
        Counterpart.objects.filter(project_id=project2.id).values_list(
            "name", flat=True
        )
    )
    assert set(new_counterparts) == {"11", "12"}


@pytest.mark.django_db
def test_data_preparation_steps_func():
    company = Company.objects.create(name="Company", address="Address")
    project1 = Project.objects.create(name="Project1", company=company)
    project2 = Project.objects.create(name="Project2", company=company)
    counterpart11 = Counterpart.objects.create(
        name="11", external_id=1, project=project1
    )
    counterpart12 = Counterpart.objects.create(
        name="12", external_id=2, project=project1
    )
    counterpart21 = Counterpart.objects.create(
        name="21", external_id=1, project=project2
    )
    counterpart23 = Counterpart.objects.create(
        name="23", external_id=3, project=project2
    )

    def prepare_destination_project(
        model_config: "ModelCopyConfig",
        input_data: dict[str, Any],
        set_to_filter_map: "SetToFilterMap",
        output_map: "OutputMap",
    ) -> None:
        original_external_ids = Counterpart.objects.filter(
            project_id=input_data["source_project_id"]
        ).values_list("external_id", flat=True)

        Counterpart.objects.filter(
            project_id=input_data["new_project_id"],
            external_id__in=original_external_ids,
        ).delete()

    config = ModelCopyConfig(
        model=Counterpart,
        filter_field_to_input_key={"project_id": "source_project_id"},
        data_preparation_steps=[
            DataPreparationStep(
                action=DataModificationActions.EXECUTE_FUNC,
                func=prepare_destination_project,
            )
        ],
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "external_id": TAKE_FROM_ORIGIN,
            "project_id": FieldCopyConfig(
                action=CopyActions.TAKE_FROM_INPUT,
                input_key="new_project_id",
            ),
        },
    )
    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "source_project_id": project1.id,
                "new_project_id": project2.id,
            },
            confirm_write=False,
        )
    ).execute_copy_request()

    assert result.is_copy_successful

    new_counterparts = list(
        Counterpart.objects.filter(project_id=project2.id).values_list(
            "name", flat=True
        )
    )
    assert set(new_counterparts) == {"11", "12", "23"}


@pytest.mark.django_db
def test_post_copy_func():
    company = Company.objects.create(name="Company", address="Address")
    project1 = Project.objects.create(name="Project1", company=company)
    project2 = Project.objects.create(name="Project2", company=company)
    counterpart11 = Counterpart.objects.create(
        name="11", external_id=1, project=project1
    )
    counterpart12 = Counterpart.objects.create(
        name="12", external_id=2, project=project1
    )

    def delete_copied_data_in_source(
        model_config: "ModelCopyConfig",
        input_data: dict[str, Any],
        set_to_filter_map: "SetToFilterMap",
        output_map: "OutputMap",
        copy_intent_list: "List[CopyIntent]",
    ) -> None:
        copied_id_list = [intent.origin.id for intent in copy_intent_list]
        Counterpart.objects.filter(id__in=copied_id_list).delete()

    config = ModelCopyConfig(
        model=Counterpart,
        filter_field_to_input_key={"project_id": "source_project_id"},
        postcopy_steps=[
            PostcopyStep(
                action=DataModificationActions.EXECUTE_FUNC,
                func=delete_copied_data_in_source,
            )
        ],
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "external_id": TAKE_FROM_ORIGIN,
            "project_id": FieldCopyConfig(
                action=CopyActions.TAKE_FROM_INPUT,
                input_key="new_project_id",
            ),
        },
    )
    result = Copyist(
        CopyRequest(
            config=CopyistConfig([config]),
            input_data={
                "source_project_id": project1.id,
                "new_project_id": project2.id,
            },
            confirm_write=False,
        )
    ).execute_copy_request()

    assert result.is_copy_successful

    new_counterparts = list(
        Counterpart.objects.filter(project_id=project2.id).values_list(
            "name", flat=True
        )
    )
    assert set(new_counterparts) == {"11", "12"}
    assert Counterpart.objects.filter(project_id=project1.id).count() == 0
