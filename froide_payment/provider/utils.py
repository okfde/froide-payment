from typing import NamedTuple

from django.utils.functional import Promise


class CancelInfo(NamedTuple):
    can_cancel: bool
    message: str | Promise


class ModifyInfo(NamedTuple):
    can_modify: bool
    message: str | Promise
    can_schedule: bool
