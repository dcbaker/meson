# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

"""Support for the Common Package System dependency generation."""

from __future__ import annotations
import typing as T

from . import NewExtensionModule, ModuleInfo

if T.TYPE_CHECKING:
    from ..interpreter import Interpreter


class CPSModule(NewExtensionModule):

    INFO = ModuleInfo('cps', added='1.5.0')


def initialize(interp: Interpreter) -> CPSModule:
    return CPSModule()
