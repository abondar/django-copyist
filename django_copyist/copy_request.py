import typing
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional

if typing.TYPE_CHECKING:
    from django_copyist.copyist import (
        CopyistConfig,
        IgnoredMap,
        OutputMap,
        SetToFilterMap,
    )


@dataclass
class CopyRequest:
    """
    This is the base class for a copy request, which serves as the input for the Copyist.

    :param input_data: The input data used to determine which models should be copied.
        It can also contain additional data that will be utilized during the copying process.
    :type input_data: dict[str, Any]
    :param config: An instance of CopyistConfig that holds all the
        necessary settings for the copying operation.
    :type config: CopyistConfig
    :param confirm_write: A flag indicating whether the copy operation should proceed even
        if there are unmatched values in the models or some models are ignored, defaults to False.
    :type confirm_write: bool, optional
    :param set_to_filter_map: A dictionary from the previous copy result that holds substitute data.
        If provided, the Copyist will compare it with the new set_to_filter_map
        to ensure that the data hasn't changed since the last copy attempt.
        If the data has changed, the Copyist will return a CopyResult with
        'is_copy_successful' set to False and an updated set_to_filter_map,
        even if 'confirm_write' is True, defaults to None.
    :type set_to_filter_map: SetToFilterMap, optional
    :param ignored_map: A dictionary from the previous copy result that
        holds data of ignored models. If provided, the Copyist will compare
        it with the new ignored_map to ensure that the data hasn't changed
        since the last copy attempt. If the data has changed,
        the Copyist will return a CopyResult with 'is_copy_successful'
        set to False and an updated ignored_map, even if 'confirm_write' is True, defaults to None.
    :type ignored_map: IgnoredMap, optional
    """

    input_data: dict[str, Any]
    config: "CopyistConfig"
    confirm_write: bool = False

    set_to_filter_map: Optional["SetToFilterMap"] = None
    ignored_map: Optional["IgnoredMap"] = None


class AbortReason(StrEnum):
    # Copy aborted because of there are unmatched values in set_to_filter_map
    NOT_MATCHED = "NOT_MATCHED"
    # Copy aborted because of there are ignored models in ignored_map
    IGNORED = "IGNORED"
    # Copy aborted because of there are changes in set_to_filter_map
    DATA_CHANGED_STF = "DATA_CHANGED_STF"
    # Copy aborted because of there are changes in ignored_map
    DATA_CHANGED_IGNORED = "DATA_CHANGED_IGNORED"


@dataclass
class CopyResult:
    """
    This is the base class for a copy result, which serves as the output for the Copyist.

    :param is_copy_successful: A flag indicating whether the copy operation was successful,
        defaults to False.
    :type is_copy_successful: bool, optional
    :param output_map: A dictionary that contains a mapping of model names to mappings of
        primary keys in the source and destination databases, defaults to None.
    :type output_map: dict, optional
    :param ignored_map: A dictionary that contains a mapping of model names to lists of
        primary keys of models that were ignored during the copying process, defaults to None.
    :type ignored_map: dict, optional
    :param set_to_filter_map: A dictionary that contains data of substitutes matched by
        the `SET_TO_FILTER` action. The structure is as follows:

        .. code-block:: python

            {
                "model_name": {
                    "field_name": {
                        "original_value": "new_value" | None
                    }
                }
            }

        Defaults to None.
    :type set_to_filter_map: dict, optional
    :param reason: The reason code, returned if `is_copy_successful` is False, defaults to None.
    :type reason: AbortReason, optional
    """

    is_copy_successful: bool
    output_map: Optional["OutputMap"]
    ignored_map: "IgnoredMap"
    set_to_filter_map: "SetToFilterMap"
    reason: AbortReason | None = None
