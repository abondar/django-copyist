Overview
========

This section aim to provide a detailed explanation of possible usecases.

All examples provided here have a corresponding testcase in the `example/demo/tests` repo directory, where you can tinker with them.

Following examples will work with following models:

.. code-block:: python

    from django.db import models


    class Company(models.Model):
        name = models.CharField(max_length=100)
        address = models.CharField(max_length=100)


    class Project(models.Model):
        name = models.CharField(max_length=100)
        company = models.ForeignKey(
            Company, related_name="projects", on_delete=models.CASCADE
        )


    class Employee(models.Model):
        name = models.CharField(max_length=100)
        company = models.ForeignKey(
            Company, related_name="employees", on_delete=models.CASCADE
        )


    class Counterpart(models.Model):
        name = models.CharField(max_length=100)
        external_id = models.IntegerField()
        project = models.ForeignKey(
            Project, related_name="counterparts", on_delete=models.CASCADE
        )


    class Task(models.Model):
        name = models.CharField(max_length=100)
        description = models.TextField()

        assignee = models.ForeignKey(
            Employee, related_name="tasks", on_delete=models.CASCADE
        )
        project = models.ForeignKey(Project, related_name="tasks", on_delete=models.CASCADE)
        counterparts = models.ManyToManyField(Counterpart, related_name="tasks")


Copy with taking data from original model
-----------------------------------------

This is the most common usecase. You have a model and you want to copy it to another model. You can do this by using the :py:attr:`~django_copyist.config.TAKE_FROM_ORIGIN` shortcut.

.. code-block:: python

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


With this configuration, the `name` and `address` fields of the new company will be copied from the original company.

.. note::

    The :py:attr:`~django_copyist.config.TAKE_FROM_ORIGIN` is a shortcut for the :py:class:`~.django_copyist.config.FieldCopyConfig` class. You can also use the :py:class:`.FieldCopyConfig` class directly.

Copy with taking data from external source
------------------------------------------

Sometimes you want to copy a model but you want to set value from some other source. You can do this by using the :py:attr:`.TAKE_FROM_INPUT` action.

.. code-block:: python

    company = Company.objects.create(name="Company", address="Address")

    config = ModelCopyConfig(
        model=Company,
        filter_field_to_input_key={"id": "company_id"},
        field_copy_actions={
            "name": FieldCopyConfig(action=CopyActions.TAKE_FROM_INPUT, input_key="new_name"),
            "address": TAKE_FROM_ORIGIN,
        },
    )
    copy_request = CopyRequest(
        config=CopyistConfig([config]),
        input_data={"company_id": company.id, "new_name": "New Company"},
        confirm_write=False,
    )
    result = Copyist(copy_request).execute_copy_request()
    new_company_id = result.output_map["Company"][str(company.id)]
    new_company = Company.objects.get(id=new_company_id)
    assert new_company.name == "New Company"

That can be useful if you want to copy model, but it has some unique restrictions, so you use it to override unique fields.


Handling denormalized data
--------------------------

Sometimes life (or business) forces you to have your data denormalized.
And with that it can be tricky to copy hierarchical data, as top level model references could be reused in some of lower level models.

Using copyist and :py:func:`~.UpdateToCopied` action you can handle this case.

.. code-block:: python

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

Here we use :py:func:`.UpdateToCopied` action to update the reference to the previously copied models.
The way it works is that :py:class:`~django_copyist.copyist.Copyist`, as it copies data, stores the mapping of the original model id to the new model id.
Then, when it encounters the :py:func:`.UpdateToCopied` action, it uses this mapping to update the reference to the copied model.

.. note::

    The :py:attr:`~django_copyist.config.UpdateToCopied` is a shortcut for the :py:class:`~.django_copyist.config.FieldCopyConfig` class. You can also use the :py:class:`.FieldCopyConfig` class directly.

    It is not limited to use in compound actions, you can use it in :py:attr:`.ModelCopyConfig.field_copy_actions` as well.


Copying data with multiple parent models
----------------------------------------

If we take a closer look at previous example, we will see that :py:attr:`.ModelCopyConfig.compound_copy_actions` is used.

This attribute stores list of :py:class:`.ModelCopyConfig` objects, which will be executed after all :py:attr:`.ModelCopyConfig.field_copy_actions` are executed.

This way you can first copy all parent models, and then use compound actions to create model, that relies on multiple parent models.



Closer look at CopyRequest and CopyResult
-----------------------------------------

You probably noticed the :py:attr:`.CopyRequest` and :py:attr:`.CopyResult` classes that are used in the examples above. Let's take a closer look at them.

.. code-block:: python

    copy_request = CopyRequest(
        config=CopyistConfig([config]),
        input_data={"company_id": company.id, "new_name": "New Company"},
        confirm_write=False,
    )

In this example, we create a :py:attr:`.CopyRequest` object.

:py:attr:`.CopyistConfig` is a class that holds the configuration for the copy process. It takes a list of :py:attr:`.ModelCopyConfig` objects.
It is root config and can have multiple :py:attr:`.ModelCopyConfig` objects if you need to copy several root level models in one request.

:py:attr:`.input_data` is a dictionary that holds the input data for the copy process. It is used to pass data to the copy process. It can be used to pass data that is not present in the original model.

:py:attr:`.confirm_write` is a more confusing one. It is a boolean that tells the copy process if it should write the data even if unmatched or ignored values were discovered during the copy process.

What are unmatched or ignored values? Let's take a look at the :py:attr:`.CopyResult` object.

:py:attr:`.CopyResult` is an object that holds the result of the copy process.

Primarily you should look at attribute :py:attr:`.is_copy_successful`. It is a boolean that tells you if the copy process was successful. If it is `False` you should look at the :py:attr:`.reason` attribute. It is a enum that tells you why the copy process failed.

:py:attr:`.output_map` is a dictionary that holds the mapping of the original model id to the new model id. It can be stored for historical purposes or to be used for UI rendering. This field is populated only on successful copy.

If you copy is unsuccessful, you can look at the :py:attr:`.django_copyist.config.CopyResult.set_to_filter_map` and
:py:attr:`.django_copyist.config.CopyResult.ignored_map` attributes.
They are dictionaries that hold the mapping of the original model id
to matched ids on :py:attr:`.django_copyist.config.CopyResult.set_to_filter_map`
and ignored fields on :py:attr:`.SET_TO_FILTER` action or :py:attr:`.django_copyist.config.ModelCopyConfig.ignore_condition` respectively.

Why would you use this attributes? Let's see following examples

Setting attribute to filtered value
------------------------------------

Sometimes, when you need to copy model that is not just top level model,
but exist in some kind of existing hierarchy, you need to set some attribute to the value of the parent model that is already
exists in target context. You can do this by using the :py:attr:`.SET_TO_FILTER` action.

.. code-block:: python

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


In this example, we copy an employee with all his tasks from one project to another.
Here - `Counterparts` models is linked to `Project` and when we copy `Task` model we want to match tasks
with the similar `Counterparts` as in the original task but in the new project. In this case
similarity is defined by `external_id` field. So we use `SET_TO_FILTER` action to set new `Counterparts` to the
copied `Task` model.


Set to filter matching gone wrong
---------------------------------

Above example is great and works well, but what if destination project doesn't have corresponding `Counterpart`?

.. code-block:: python

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

Here we are working with the same config as in the previous example, but now we have `Counterpart` with `external_id` 2 only in the `Project1` and not in the `Project2`.
And it's here where :py:class:`.CopyResult` comes into play. We can see that the copy process failed because the counterpart with `external_id` 2 was not found in the destination project.

By observing the :py:attr:`.django_copyist.config.CopyResult.set_to_filter_map` attribute, we can see that the counterpart with `external_id` 2 was not
matched.

If it is happening in interactive context, you can prompt user to resolve this issue or accept the fact that some data won't be copied.

If we want to confirm that the copy process should continue regardless, we can set the :py:attr:`.confirm_write` attribute to `True` and pass the :py:attr:`.django_copyist.config.CopyResult.set_to_filter_map` attribute to the :py:attr:`.CopyRequest` object.

.. note::

    The :py:attr:`django_copyist.config.CopyRequest.set_to_filter_map` is passed, so that :py:class:`.Copyist` can verify that list of unmatched
    values remained the same between copy calls. If it changed, unsuccessful result with reason :py:attr:`.django_copyist.config.AbortReason.DATA_CHANGED_STF` will be returned.

Set to filter using custom function
------------------------------------

Sometimes you need to set value to the filtered value, but you need to do some custom logic to find the matching value and just few filters aren't gonna cut it.

In this cases `filter_func` of :py:class:`~.django_copyist.config.FilterConfig` comes in handy. Let's see the example:

.. code-block:: python

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
        input_data: Dict[str, Any],
        field_name: str,
        field_copy_config: "FieldCopyConfig",
        set_to_filter_map: "SetToFilterMap",
        instance_list: List[Model],
        referenced_instance_list: List[Model],
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


You can see that we defined function `match_counterparts` and use it for filtering.
Although signature of the function is quite complex, it provides basically all available context,
allowing you to write all logic you need to match the values.
You can read more on signature at :protocol:`~.django_copyist.config.SetToFilterFunc`


Ignoring models during copy with SET_TO_FILTER
------------------------------------------------

You probably noticed the :py:attr:`.django_copyist.copy_request.CopyResult.ignored_map` attribute in the previous examples.
So how exactly it is used?

For example, lets assume you want to have same config as in `SET_TO_FILTER` example, but you want to ignore `Task` model if it can't match all counterparts:

.. code-block:: python

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

In this example, we have two tasks, but one of them doesn't have all matching counterparts in the new project.
Default behaviour in such case, that just not all counterparts will be matched and the copy process will continue.

But if you don't want to copy model at all in such case - you can use :py:class:`~.IgnoreCondition` with
py:class:`~.IgnoreFilter` to ignore model if it doesn't match the condition.


Ignoring based on nested data mismatches
----------------------------------------

We can take the previous example further, and ignore the whole `Employee` model if any of the `Task` models counterparts
is not matched.

.. code-block:: python

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

Notice how :py:class:`~.IgnoreCondition` is used on the `Employee` model, where it defines exclude filter
and information where to search for mismatches.

Custom ignore function
-----------------------

But sometimes ignoring just based on `SET_TO_FILTER` is not enough and you want to
bring in custom logic.

In this case you can use `ignore_func` of :py:class:`~.django_copyist.config.IgnoreCondition` to define custom ignore logic.

.. code-block:: python

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
        model_extra_filter: Optional[Q],
        ignored_map: "IgnoredMap",
        input_data: Dict[str, Any],
    ) -> List[Model]:
        not_matched_counterparts = {
            key for key, value in set_to_filter_map[Task.__name__]["counterparts"].items() if value is None
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

Here we defined function `ignore_tasks` and use it for ignoring `Task` models, based on same logic, as in previous
examples.

You can read more on signature at :protocol:`~.django_copyist.config.IgnoreFunc`

Controlling querysets with static filters
-----------------------------------------

Sometimes - there is data that you want to ignore, but it's not based on input or the data itself,
but on some static condition. For example if you want to all entities with certain status or something like that.

Copyist allows you to do it, using `static_filter` of :py:class:`~.django_copyist.config.ModelCopyConfig`.

.. code-block:: python

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


`static_filters` is a `Q` object that will be used to filter the queryset of the model.


Data preparation by deletion
----------------------------

There are cases, usually when you copy from one existing context to another, where you
need to clean up obsolete data at destination context, before moving fresh copies there.

In this case you can use `data_preparation_steps` of :py:class:`~.django_copyist.config.ModelCopyConfig`.

.. code-block:: python

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

Here we have used preparation step to delete all `Counterpart` models that are linked to the destination project,
so that we can copy fresh data there.

Data preparation with custom function
-------------------------------------

But just deleting data could be not what you want to prepare you data.

In this case you can use `func` of :py:class:`~.django_copyist.config.DataPreparationStep`, which allows better control
over what is going on

.. code-block:: python

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
        input_data: Dict[str, Any],
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

Here we not just deleted all `Counterpart` models in destination project,
but only those that have overlapping `external_id` with source project counterparts.

You can see signature of the function at :protocol:`~.django_copyist.config.DataPreparationFunc`

Post-copy actions
------------------

Similar to data preparation steps, you can define post-copy actions, that will be executed after all data is copied.

.. code-block:: python

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
        input_data: Dict[str, Any],
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

Here we used it to delete data in source project after it was copied to destination project.

It also could be used to recalculate some computed values based on new context,
or to send some notifications, or whatever you need.

You can see more on signature at :protocol:`~.django_copyist.config.PostcopyFunc`

Also :py:class:`~.PostcopyStep` supports `filter_field_to_input_key` with :py:attr:`~.DELETE_BY_FILTER` as well.


Note on ordering of operations
------------------------------

Now that we are familiar with different steps that :py:class:`~.Copyist` can go through in process,
let's talk about the order of operations.

The order of operations is as follows:

#. Validation of whole configuration, it can raise exceptions if same model is defined several times, or in case of other configuration errors
#. Forming `set_to_filter_map` across included all models
#. Resolving `ignore_condition` for all models
#. If `confirm_write` is `False`

#. If `ignored_map` is not empty - abort with `IGNORED` reason

    #. If `set_to_filter_map` is not empty - abort with `NOT_MATCHED` reason
    #. If `data_preparation_steps` are defined - execute them

#. Go through field copy actions

    #. If there are nested model configs for fields resolving - they execute starting from step 5

#. If `compound_copy_actions` are defined - execute them from step 5
#. If `postcopy_steps` are defined - execute them


Note on performance
-------------------

Even though `django-copyist` was built with performance in mind, it's still a tool that has to do
a lot of work, especially when we are talking about dozens of thousands of records to copy.

So, if you are copying a lot of data, you should consider doing these copies as background tasks,
probably using some kind of task queue like `Celery`.

Format of :py:class:`~.CopyRequest` and :py:class:`~.CopyResult` are designed to be easily serializable,
so that you can reflect process of copying in your database.