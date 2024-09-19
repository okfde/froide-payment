from collections import namedtuple

CancelInfo = namedtuple("CancelInfo", ("can_cancel", "message"))

ModifyInfo = namedtuple("ModifyInfo", ("can_modify", "message", "can_schedule"))
