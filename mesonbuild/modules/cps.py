# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

"""Support for the Common Package System dependency generation."""

from __future__ import annotations
import dataclasses
import typing as T

from . import NewExtensionModule, ModuleInfo
from .. import build
from ..interpreterbase import typed_pos_args, noKwargs, TYPE_kwargs, InvalidArguments

if T.TYPE_CHECKING:
    from . import ModuleState
    from ..build import BuildTargetTypes
    from ..interpreter import Interpreter


@dataclasses.dataclass
class Package:

    """A Package with it's components and configurations."""

    name: str
    version: str
    components: T.Dict[str, BuildTargetTypes] = dataclasses.field(default_factory=dict)


class CPSModule(NewExtensionModule):

    INFO = ModuleInfo('cps', added='1.5.0')

    _packages: T.Dict[str, Package] = {}

    def __init__(self) -> None:
        super().__init__()
        self.methods.update({
            'create_package': self.create_package,
            'add_component': self.add_component,
        })

    @typed_pos_args('cps.create_package', str, optargs=[str])
    @noKwargs
    def create_package(self, state: ModuleState, args: T.Tuple[str, T.Optional[str]], kwargs: TYPE_kwargs) -> None:
        name, version = args
        if version is None:
            version = state.project_version
        if name in self._packages:
            # TODO: provide a better error message about where this was defined
            raise InvalidArguments(f'A CPS package called {name} already exists')
        self._packages[name] = Package(name, version)

    @typed_pos_args('cps.add_component', str, str, (build.BuildTarget, build.CustomTarget, build.CustomTargetIndex))
    @noKwargs
    def add_component(self, state: ModuleState, args: T.Tuple[str, str, BuildTargetTypes]) -> None:
        pname, cname, target = args
        try:
            package = self._packages[pname]
        except KeyError:
            raise InvalidArguments(f'Tried to use a package "{pname}" that has not been defined.')

        if cname in package.components:
            raise InvalidArguments(f'Component "{cname}" of package "{pname}" is already defined!')

        package.components[cname] = target



def initialize(interp: Interpreter) -> CPSModule:
    return CPSModule()
