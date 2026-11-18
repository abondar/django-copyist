import typing
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional

from django_copyist.config import MapKeys, map_key

if typing.TYPE_CHECKING:
    from django.db.models import Model

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
    :param using: Database alias for every read and write of the copy. Defaults to
        the database router choice for each model, defaults to None.
    :type using: str, optional
    :param batch_size: ``batch_size`` for every ``bulk_create`` call, defaults to None
        (one statement per model and level, split only where the backend requires it).
    :type batch_size: int, optional
    """

    input_data: dict[str, Any]
    config: "CopyistConfig"
    confirm_write: bool = False

    set_to_filter_map: Optional["SetToFilterMap"] = None
    ignored_map: Optional["IgnoredMap"] = None
    using: str | None = None
    batch_size: int | None = None


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

    :ivar is_copy_successful: A flag indicating whether the copy operation was successful,
        defaults to False.
    :type is_copy_successful: bool, optional
    :ivar output_map: Maps model keys to dictionaries of origin primary key to copy
        primary key. Primary keys are strings. A model key is the class name
        (``"Company"``), or the label (``"demo.Company"``) with ``MapKeys.LABEL``.
        None if the copy did not run. Use :meth:`copies_of` to read it by model class.
    :type output_map: dict, optional
    :ivar ignored_map: Maps model keys to lists of primary keys of origin rows that
        were ignored during the copying process.
    :type ignored_map: dict, optional
    :ivar set_to_filter_map: A dictionary that contains data of substitutes matched by
        the `SET_TO_FILTER` action. The structure is as follows:

        .. code-block:: python

            {
                "ModelName": {
                    "field_name": {
                        "origin_pk": "substitute_pk" | None
                    }
                }
            }

        Defaults to None.
    :type set_to_filter_map: dict, optional
    :ivar reason: The reason code, returned if `is_copy_successful` is False, defaults to None.
    :type reason: AbortReason, optional
    :ivar map_keys: The key mode of the maps, from ``CopyistConfig.map_keys``.
    :type map_keys: MapKeys
    :ivar model_labels: Maps every map key to the label of its model, for example
        ``{"Company": "demo.Company"}``.
    :type model_labels: dict
    """

    is_copy_successful: bool
    output_map: Optional["OutputMap"]
    ignored_map: "IgnoredMap"
    set_to_filter_map: "SetToFilterMap"
    reason: AbortReason | None = None
    map_keys: MapKeys = MapKeys.MODEL_NAME
    model_labels: dict[str, str] = field(default_factory=dict)

    def copies_of(self, model: "type[Model]") -> dict[str, str]:
        """
        Map of origin primary key to copy primary key for one model.

        :param model: Model class.
        :return: ``{"<origin pk>": "<copy pk>"}``. Empty if the model was not copied or
            the copy did not run.
        """
        if not self.output_map:
            return {}
        key = map_key(model, self.map_keys)
        if self.model_labels and self.model_labels.get(key) != model._meta.label:
            # Same class name, different app: this model was not copied.
            return {}
        return self.output_map.get(key, {})
