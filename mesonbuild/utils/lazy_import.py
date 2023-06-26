# SPDX-license-identifier: Apache-2.0
# Copyright © 2023 Intel Corporation

from __future__ import annotations
import dataclasses
import importlib
import sys
import typing as T

if T.TYPE_CHECKING:
    import types

__all__ = ['lazy_import']


@dataclasses.dataclass
class LazyImport:

    _LazyImport__name: str
    _LazyImport__mod: T.Optional[types.ModuleType] = dataclasses.field(default=None, init=False)

    def __getattr__(self, __name: str) -> T.Any:
        """Load the promised module and return a value from it.

        :param __name: The name of the attribute
        :return: The attribute from the promised module
        """
        # If we've been asked for one of our own methods return it using super()
        # this is required to avoid infinite recursion
        if __name.startswith('_LazyImport'):
            return super().__getattribute__(__name)

        # If we haven't already loaded the module, then go ahead and import it,
        # and import it into the sys.modules mapping.
        if self._LazyImport__mod is None:
            m = importlib.import_module(self._LazyImport__name)
            sys.modules[self._LazyImport__name] = m
            self._LazyImport__mod = m
            # We set our own `__getattribute__` to that of the module here as
            # an optimizaition for anyone still holding a reference to this
            # LazyImport instance, now an attribute looking *is* an attribute
            # lookup from the module.
            setattr(self, '__getattribute__', m.__getattribute__)

        # Finally, search the module for the value the user wanted and return it.
        return getattr(self._LazyImport__mod, __name)


def lazy_import(name: str) -> types.ModuleType:
    """Return a module if it's already imported, otherwise return a promise for that import

    :param name: The name of the module to import
    :return: A module, or an opaque object that will import that object when it
        is used
    """
    if name in sys.modules:
        return sys.modules[name]

    # Yes, this isn't strictly true, but a LazyImport *acts* just like a Module
    return T.cast('types.ModuleType', LazyImport(name))
