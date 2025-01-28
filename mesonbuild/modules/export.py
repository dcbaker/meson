# SPDX-License-Identifier: Apache-2.0
# Copyright © 2025 Intel Corporation

from __future__ import annotations
import dataclasses
import typing as T

from mesonbuild.interpreter import Interpreter

from . import ExtensionModule, ModuleInfo
from ..build import BuildTarget, InvalidArguments
from ..interpreterbase import ObjectHolder
from ..interpreterbase.decorators import typed_pos_args, noKwargs
from ..utils.core import HoldableObject

if T.TYPE_CHECKING:
    from . import ModuleState
    from ..interpreter import Interpreter
    from ..interpreterbase import TYPE_kwargs


@dataclasses.dataclass
class ExportSet(HoldableObject):

    """A set of exports that are grouped together.

    This allows various libraries, executables, data, and interfaces (like
    header-only libraries) to be grouped as data and then used to generate
    """

    name: str
    targets: T.Dict[str, BuildTarget] = dataclasses.field(
        default_factory=dict, init=False)


class ExportSetHolder(ObjectHolder[ExportSet]):

    def __init__(self, obj: ExportSet, interpreter: Interpreter) -> None:
        super().__init__(obj, interpreter)
        self.methods.update({
            'export': self.export_method,
        })

    @typed_pos_args('export_set.export', str, BuildTarget)
    @noKwargs
    def export_method(self, args: T.Tuple[str, BuildTarget], kwargs: TYPE_kwargs) -> None:
        name, target = args
        if name in self.held_object.targets:
            raise InvalidArguments(f'Already added an export target named {name}')
        self.held_object.targets[name] = target


class ExportModule(ExtensionModule):

    """A module for exporting various formats of dependencies."""

    INFO = ModuleInfo('export', '1.8.0')

    def __init__(self, interpreter: Interpreter) -> None:
        super().__init__(interpreter)
        self.exports: T.Dict[str, ExportSet] = {}
        self.methods.update({
            'create_set': self.create_set_method,
        })

    @typed_pos_args('export.create_set', str)
    @noKwargs
    def create_set_method(self, state: ModuleState, args: T.Tuple[str], kwargs: TYPE_kwargs) -> HoldableObject:
        name, *_ = args
        if name in self.exports:
            raise InvalidArguments(f'An export set called "{name}" already exists.')
        ex = ExportSet(name)
        self.exports[name] = ex
        return ex


def initialize(interp: Interpreter) -> ExportModule:
    interp.holder_map[ExportSet] = ExportSetHolder
    return ExportModule(interp)
