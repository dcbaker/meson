# SPDX-License-Identifier: Apache-2.0
# Copyright © 2025 Intel Corporation

from __future__ import annotations
import typing as T

from . import ExtensionModule, ModuleInfo

if T.TYPE_CHECKING:
    from ..interpreter import Interpreter


class ExportModule(ExtensionModule):

    """A module for exporting various formats of dependencies."""

    INFO = ModuleInfo('export', '1.8.0')

    def __init__(self, interpreter: Interpreter) -> None:
        super().__init__(interpreter)


def initialize(interp: Interpreter) -> ExportModule:
    return ExportModule(interp)
