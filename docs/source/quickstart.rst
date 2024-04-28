Quickstart
==========

This pages aims to get you going with django-copyist as quickly as possible.

Installation
------------

To install with pip:

.. code-block:: console

   pip install django-copyist

To install with poetry:

.. code-block:: console

   poetry add django-copyist


Basic usage
-----------

Assuming you have following models in your Django app:

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


And you want to create full copy of company with all nested data, but also want it to be created with different name and address.
In this case you should write following :py:class:`~.django_copyist.config.ModelCopyConfig`

.. code-block:: python

    from django_copyist.config import (
        ModelCopyConfig,
        TAKE_FROM_ORIGIN,
        MakeCopy,
        UpdateToCopied,
        FieldCopyConfig,
        CopyActions,
    )
    from example.demo.models import (
        Project,
        Counterpart,
        Task,
        Company,
        Employee,
    )


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

And then you can execute copy action like this:

.. code-block:: python

    from django_copyist.copy_request import CopyRequest
    from django_copyist.copyist import CopyistConfig, Copyist

    copy_request = CopyRequest(
        config=CopyistConfig([config]),
        input_data={
            "company_id": company_id,
            "new_company_name": new_company_name,
            "new_company_address": new_company_address,
        },
        confirm_write=False,
    )
    result = Copyist(copy_request).execute_copy_request()

With this, all company data should be copied.
That seems like a lot to take in, so let's break it down to what exactly happens here:

1. We define a :py:class:`~.django_copyist.config.ModelCopyConfig` for the `Company` model.

.. code-block:: python

    config = ModelCopyConfig(
        model=Company,
        filter_field_to_input_key={"id": "company_id"},
    ...

:py:class:`~.django_copyist.config.ModelCopyConfig` is a class that defines how to copy a model. It takes the model class as the first argument and a dictionary that maps the filter field to the input key. This is used to find the object to copy.

2. Next we define :py:attr:`.ModelCopyConfig.field_copy_actions` for the `Company` model.

.. code-block:: python

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
    ...

:py:attr:`.ModelCopyConfig.field_copy_actions` is a dictionary that maps the field name to a :py:class:`~.FieldCopyConfig` object.

The :py:class:`~.FieldCopyConfig` object defines how to copy the field. In this case, we take the `name` and `address` fields from the input data.

:py:attr:`~django_copyist.config.TAKE_FROM_ORIGIN` is a shortcut for creating :py:class:`~.FieldCopyConfig` with :py:attr:`~.CopyActions.TAKE_FROM_ORIGIN` action, which takes value for new object from original object.

We also define how to copy the `projects` and `employees` fields.

We use the :py:attr:`~.MakeCopy` action to copy the related objects.
:py:attr:`~.MakeCopy` is a shortcut for creating :py:class:`~.FieldCopyConfig` with :py:attr:`CopyActions.MAKE_COPY` action and reference to given model.
Nested :py:attr:`~.MakeCopy` automatically propagate parent id to child object.

3. We define :py:attr:`~.ModelCopyConfig.compound_copy_actions` for the `Company` model.

.. code-block:: python

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
    ...

:py:attr:`~.ModelCopyConfig.compound_copy_actions` is a list of :py:class:`~.ModelCopyConfig` objects that define how
to copy related objects that are not directly related to the model, or related through multiple relations that need to be created beforehand.

:py:attr:`~.ModelCopyConfig.compound_copy_actions` are executed after all fields are copied.

In this case, we define how to copy the `Task` model. We take the `name` and `description` fields from the original object. We also define how to copy the `counterparts`, `project`, and `assignee` fields.

:py:func:`~.UpdateToCopied` is a shortcut for creating :py:class:`~.FieldCopyConfig` with :py:attr:`CopyActions.UPDATE_TO_COPIED` action and reference to given model.
It will search mapping of previously copied objects and update reference to copied object.

4. We create a :py:class:`~.CopyRequest` object with the :py:class:`~.CopyistConfig` and input data.

.. code-block:: python

    copy_request = CopyRequest(
        config=CopyistConfig([config]),
        input_data={
            "company_id": company_id,
            "new_company_name": new_company_name,
            "new_company_address": new_company_address,
        },
        confirm_write=False,
    )
    ...

:py:class:`~.CopyRequest` is a class that defines the copy request. It takes the `CopyistConfig` object, input data, and a boolean flag that indicates whether to confirm the write operation.

:py:class:`~.CopyistConfig` is a class that defines the configuration for the copy operation. It takes a list of :py:class:`~.ModelCopyConfig` objects.

:py:attr:`.CopyResult.input_data` is a dictionary that contains the input data for the copy operation. It is later used in filtering or :py:attr:`~.TAKE_FROM_INPUT` actions.

:py:attr:`.CopyResult.confirm_write` is a boolean flag that indicates whether to confirm the write operation,
even if there are issues with matching objects in origin location with objects in target destination.
It is not used in this example, but you can read more about it in overview section of this documentation.

5. We execute the copy request.

.. code-block:: python

    result = Copyist(copy_request).execute_copy_request()

:py:class:`~django_copyist.copyist.Copyist` is a class that executes the copy request. It takes the :py:class:`~.CopyRequest` object as an argument.

:py:attr:`.CopyResult.execute_copy_request` method returns :py:class:`~.CopyResult` object that contains information about the copy operation. Read more about it in overview section.

And like this you have copied the company with all related data and can see and edit configuration in one place.

Next steps
----------

This is just a basic example of how to use django-copyist.
It can do much more granular control on how it should execute copy, and you can read more about it in the documentation.
