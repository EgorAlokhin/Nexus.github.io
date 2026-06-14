"""Thread-local 'current account' so the service layer stays per-user.

A request thread (set by middleware from request.user) or a background job
(set explicitly while iterating accounts) binds the active Account here. The
sync/messaging/config helpers read it instead of a global singleton, which is
what makes concurrent users with separate credentials possible.
"""

import contextlib
import threading

_state = threading.local()


def set_current_account(account):
    _state.account = account


def get_current_account():
    return getattr(_state, "account", None)


def clear_current_account():
    _state.account = None


@contextlib.contextmanager
def use_account(account):
    prev = getattr(_state, "account", None)
    _state.account = account
    try:
        yield account
    finally:
        _state.account = prev
