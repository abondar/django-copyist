Quickstart
==========

This page gets you from installation to a working copy.

Installation
------------

To install with pip:

.. code-block:: console

   pip install django-copyist

To install with uv:

.. code-block:: console

   uv add django-copyist

django-copyist needs no settings. Add ``"django_copyist"`` to ``INSTALLED_APPS`` only if
you want the ``copyist_scaffold`` management command (see :doc:`configs`).


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

    from django_copyist import (
        TAKE_FROM_ORIGIN,
        MakeCopy,
        ModelCopyConfig,
        TakeFromInput,
        UpdateToCopied,
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
            "name": TakeFromInput("new_company_name"),
            "address": TakeFromInput("new_company_address"),
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

Check the config before you run it. :py:func:`~django_copyist.check_config` compares it
with the model metadata and runs no queries:

.. code-block:: python

    from django_copyist import check_config

    check_config(config, raise_on_error=True)

Then run the copy:

.. code-block:: python

    from django_copyist import run_copy

    result = run_copy(
        config,
        input_data={
            "company_id": company_id,
            "new_company_name": new_company_name,
            "new_company_address": new_company_address,
        },
    )
    assert result.is_copy_successful
    new_company_id = result.copies_of(Company)[str(company_id)]

With this, all company data is copied.
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
        "name": TakeFromInput("new_company_name"),
        "address": TakeFromInput("new_company_address"),
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
:py:func:`~.TakeFromInput` is a shortcut for a :py:class:`~.FieldCopyConfig` with the :py:attr:`~.CopyActions.TAKE_FROM_INPUT` action.

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

4. We run the copy with :py:func:`~django_copyist.run_copy`.

.. code-block:: python

    result = run_copy(
        config,
        input_data={
            "company_id": company_id,
            "new_company_name": new_company_name,
            "new_company_address": new_company_address,
        },
    )

``input_data`` holds the values that root filters and ``TAKE_FROM_INPUT`` actions read
by key.

:py:func:`~django_copyist.run_copy` also accepts:

- ``confirm_write``: copy even when some references have no match or some rows are
  ignored. See :ref:`copy-request-and-result` in the overview.
- ``using``: the database alias for all reads and writes.
- ``batch_size``: the ``batch_size`` of every ``bulk_create`` call.

5. We read the result.

:py:class:`~.CopyResult` tells whether the copy ran (``is_copy_successful``) and maps
every origin primary key to the primary key of its copy:

.. code-block:: python

    result.copies_of(Company)  # {"1": "2"}
    result.output_map  # {"Company": {"1": "2"}, "Project": {...}, ...}

Keys of ``output_map``, ``ignored_map`` and ``set_to_filter_map`` are model class names.
Primary keys are strings.

If two models in one config share a class name, for example ``shop.Order`` and
``billing.Order``, the copy raises ``ImproperlyConfigured`` before it runs any query.
Key the maps by model label instead:

.. code-block:: python

    from django_copyist import MapKeys

    result = run_copy(config, input_data={...}, map_keys=MapKeys.LABEL)
    result.output_map  # {"shop.Order": {...}, "billing.Order": {...}}

``map_keys`` can also be set on :py:class:`~django_copyist.copyist.CopyistConfig`.
Callbacks receive maps with the same keys. ``result.copies_of(Model)`` works in both
modes.

:py:func:`~django_copyist.run_copy` builds a :py:class:`~.CopyRequest` and calls
:py:meth:`.Copyist.execute_copy_request`. You can do the same yourself.

And like this you have copied the company with all related data and can see and edit configuration in one place.

Next steps
----------

- :doc:`overview` shows every copy action on a working example.
- :doc:`configs` shows how to generate a config with ``copyist_scaffold`` and check it
  with ``check_config``.
- :doc:`limitations` lists what django-copyist does not do.
