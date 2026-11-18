API
===

Import everything from the package root. Names listed here are public API and follow
semantic versioning. Other names in the submodules may change in a minor release.

.. code-block:: python

    from django_copyist import ModelCopyConfig, MakeCopy, TAKE_FROM_ORIGIN, run_copy

Running a copy
--------------

.. autofunction:: django_copyist.run_copy

.. autoclass:: django_copyist.copy_request.CopyRequest
    :members:

.. autoclass:: django_copyist.copy_request.CopyResult
    :members:

.. autoclass:: django_copyist.copy_request.AbortReason
    :members:
    :undoc-members:

.. autoclass:: django_copyist.copyist.Copyist
    :members: execute_copy_request, validate_config, execute_copy

.. autoclass:: django_copyist.copyist.CopyistConfig

.. autoclass:: django_copyist.copyist.CopyIntent

Configuration
-------------

.. automodule:: django_copyist.config
    :members:
    :exclude-members: get_queryset_for_model_config, DataModificationStep,
        find_map_key_conflicts, map_key_labels

Checking configs
----------------

.. autofunction:: django_copyist.checks.check_config

.. autoclass:: django_copyist.checks.ConfigIssue

.. autoclass:: django_copyist.checks.ConfigIssueLevel
    :members:
    :undoc-members:

Generating configs
------------------

.. autofunction:: django_copyist.scaffold.scaffold_config
