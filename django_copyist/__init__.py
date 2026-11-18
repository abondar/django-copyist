"""
django-copyist: declarative, bulk copying of Django model trees.

Typical use::

    from django_copyist import MakeCopy, ModelCopyConfig, TAKE_FROM_ORIGIN, run_copy

    config = ModelCopyConfig(
        model=Company,
        filter_field_to_input_key={"id": "company_id"},
        field_copy_actions={
            "name": TAKE_FROM_ORIGIN,
            "projects": MakeCopy(
                ModelCopyConfig(model=Project, field_copy_actions={"name": TAKE_FROM_ORIGIN})
            ),
        },
    )
    result = run_copy(config, input_data={"company_id": company.pk})
    new_company_pk = result.copies_of(Company)[str(company.pk)]

Everything listed in ``__all__`` is public API. Other names may change between
minor versions.
"""

import dataclasses
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version
from typing import Any

from django_copyist.checks import ConfigIssue, ConfigIssueLevel, check_config
from django_copyist.config import (
    TAKE_FROM_ORIGIN,
    CopyActions,
    DataModificationActions,
    DataPreparationFunc,
    DataPreparationStep,
    FieldCopyConfig,
    FieldFilterConfig,
    FilterConfig,
    FilterSource,
    IgnoreCondition,
    IgnoreFilter,
    IgnoreFilterSource,
    IgnoreFunc,
    MakeCopy,
    MapKeys,
    ModelCopyConfig,
    PostcopyFunc,
    PostcopyStep,
    SetToFilterFunc,
    TakeFromInput,
    UpdateToCopied,
)
from django_copyist.copy_request import AbortReason, CopyRequest, CopyResult
from django_copyist.copyist import (
    CopyIntent,
    Copyist,
    CopyistConfig,
    FieldSetToFilterMap,
    IgnoredMap,
    OutputMap,
    SetToFilterMap,
)

try:
    __version__ = _version("django-copyist")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"


def run_copy(
    config: ModelCopyConfig | CopyistConfig,
    input_data: dict[str, Any],
    *,
    confirm_write: bool = False,
    set_to_filter_map: SetToFilterMap | None = None,
    ignored_map: IgnoredMap | None = None,
    using: str | None = None,
    batch_size: int | None = None,
    map_keys: MapKeys | None = None,
) -> CopyResult:
    """
    Validate and execute a copy in one call.

    This is a shortcut for building a :class:`CopyRequest` and calling
    :meth:`Copyist.execute_copy_request`.

    :param config: One root :class:`ModelCopyConfig`, or a :class:`CopyistConfig`
        with several roots.
    :param input_data: Values that root filters, ``TAKE_FROM_INPUT`` actions and
        ``FROM_INPUT`` filters read by key.
    :param confirm_write: Copy even when ``SET_TO_FILTER`` has unmatched values or some
        instances are ignored. Pass the maps from the previous result to make sure the
        data did not change since the user saw them.
    :param set_to_filter_map: ``set_to_filter_map`` from the previous, aborted result.
    :param ignored_map: ``ignored_map`` from the previous, aborted result.
    :param using: Database alias for all reads and writes. Defaults to the router choice.
    :param batch_size: ``batch_size`` for every ``bulk_create`` call.
    :param map_keys: Key mode of the result maps. Overrides ``CopyistConfig.map_keys``.
        Defaults to ``MapKeys.MODEL_NAME`` (``"Company"``); use ``MapKeys.LABEL``
        (``"demo.Company"``) when two copied models share a class name.
    :return: The :class:`CopyResult`. Check ``is_copy_successful`` before reading
        ``output_map``.
    """
    if isinstance(config, ModelCopyConfig):
        config = CopyistConfig(model_configs=[config])
    if map_keys is not None:
        config = dataclasses.replace(config, map_keys=map_keys)
    request = CopyRequest(
        config=config,
        input_data=input_data,
        confirm_write=confirm_write,
        set_to_filter_map=set_to_filter_map,
        ignored_map=ignored_map,
        using=using,
        batch_size=batch_size,
    )
    return Copyist(request).execute_copy_request()


__all__ = [
    "TAKE_FROM_ORIGIN",
    "AbortReason",
    "ConfigIssue",
    "ConfigIssueLevel",
    "CopyActions",
    "CopyIntent",
    "CopyRequest",
    "CopyResult",
    "Copyist",
    "CopyistConfig",
    "DataModificationActions",
    "DataPreparationFunc",
    "DataPreparationStep",
    "FieldCopyConfig",
    "FieldFilterConfig",
    "FieldSetToFilterMap",
    "FilterConfig",
    "FilterSource",
    "IgnoreCondition",
    "IgnoreFilter",
    "IgnoreFilterSource",
    "IgnoreFunc",
    "IgnoredMap",
    "MakeCopy",
    "MapKeys",
    "ModelCopyConfig",
    "OutputMap",
    "PostcopyFunc",
    "PostcopyStep",
    "SetToFilterFunc",
    "SetToFilterMap",
    "TakeFromInput",
    "UpdateToCopied",
    "__version__",
    "check_config",
    "run_copy",
]
