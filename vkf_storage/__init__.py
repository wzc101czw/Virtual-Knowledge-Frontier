"""VKF Storage Core: offline, local-first persistent cognitive objects."""
from .core import Storage, VKFError, NotFound, Conflict, InvalidInput, UnsupportedSchema

__all__ = ["Storage", "VKFError", "NotFound", "Conflict", "InvalidInput", "UnsupportedSchema"]
__version__ = "0.1.0"
