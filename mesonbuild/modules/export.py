# SPDX-License-Identifier: Apache-2.0
# Copyright © 2025 Intel Corporation

from __future__ import annotations
import dataclasses
import os
import textwrap
import typing as T

from . import ExtensionModule, ModuleInfo
from ..build import Build, BuildTarget, InvalidArguments, SharedLibrary, StaticLibrary, Data
from ..dependencies import ExternalDependency, ExternalLibrary
from ..interpreterbase import ObjectHolder
from ..interpreterbase.decorators import KwargInfo, ContainerTypeInfo, typed_kwargs, typed_pos_args, noKwargs
from ..options import OptionKey
from ..utils.core import HoldableObject
from ..utils.universal import File, FileMode

if T.TYPE_CHECKING:
    from typing_extensions import TypedDict

    from . import ModuleState
    from ..interpreter import Interpreter
    from ..interpreterbase import TYPE_kwargs, SubProject

    class ExportKws(TypedDict):

        default: bool
        public_deps: T.List[T.Union[ExternalDependency, ExternalLibrary, SharedLibrary, StaticLibrary]]


@dataclasses.dataclass
class ExportEntry:

    name: str
    target: BuildTarget
    default: bool
    subproject: SubProject
    public_deps: T.List[T.Union[ExternalDependency, ExternalLibrary, SharedLibrary, StaticLibrary]]

    def generate_pc(self, package: str, b: Build) -> None:
        opts = b.environment.coredata.optstore
        name = self.name if self.default else f'{package}-{self.name}'

        prefix = opts.get_value(OptionKey('prefix'))
        assert isinstance(prefix, str), 'for mypy'

        inclueddir = opts.get_value(OptionKey('includedir'))
        assert isinstance(inclueddir, str), 'for mypy'

        libdir = opts.get_value(OptionKey('libdir'))
        assert isinstance(libdir, str), 'for mypy'

        lib = ''

        data = textwrap.dedent(f'''\
            prefix={prefix}
            includedir={{prefix}}/{inclueddir}
            libdir={{prefix}}/{libdir}

            Name: {name}
            Description: TODO
            Version: TODO
            Libs: -L${{libdir}} -l{lib}
            Cflags: -I${{includedir}} TODO
            ''')

        fname = os.path.join(b.environment.build_dir, b.environment.private_dir, f'{name}.pc')
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(data)

        b.data.append(Data(
            [File.from_built_file(b.environment.private_dir, fname)],
            'TODO',  # TODO: split code for calculating this out of pkgconf module
            'TODO',  # TODO: see above ^
            FileMode(),
            self.subproject,
            install_tag='devel',
        ))


@dataclasses.dataclass
class Package(HoldableObject):

    """A set of exports that are grouped together.

    This allows various libraries, executables, data, and interfaces (like
    header-only libraries) to be grouped as data and then used to generate
    """

    name: str
    entries: T.List[ExportEntry] = dataclasses.field(
        default_factory=list, init=False)

    def generate(self, b: Build) -> None:
        for entry in self.entries:
            entry.generate_pc(self.name, b)


class PackageHolder(ObjectHolder[Package]):

    def __init__(self, obj: Package, interpreter: Interpreter) -> None:
        super().__init__(obj, interpreter)
        self.methods.update({
            'export': self.export_method,
        })

    @typed_pos_args('package.export', str, BuildTarget)
    @typed_kwargs(
        'package.export',
        KwargInfo('public_deps', ContainerTypeInfo(list, (ExternalDependency, ExternalLibrary, StaticLibrary, SharedLibrary)), default=[], listify=True),
        KwargInfo('default', bool, default=False),
    )
    def export_method(self, args: T.Tuple[str, BuildTarget], kwargs: ExportKws) -> None:
        name, target = args
        if any(e.name == name for e in self.held_object.entries):
            raise InvalidArguments(f'Trying to add a second entry with name {name}')
        if kwargs['default'] and any(e.default for e in self.held_object.entries):
            raise InvalidArguments('Trying to add a second default entry')
        self.held_object.entries.append(
            ExportEntry(name, target, kwargs['default'], self.interpreter.subproject,
                        kwargs['public_deps']))


class ExportModule(ExtensionModule):

    """A module for exporting various formats of dependencies."""

    INFO = ModuleInfo('export', '1.8.0')

    def __init__(self, interpreter: Interpreter) -> None:
        super().__init__(interpreter)
        self.exports: T.Dict[str, Package] = {}
        self.methods.update({
            'create_package': self.create_package_method,
        })

    @typed_pos_args('export.create_set', optargs=[str])
    @noKwargs
    def create_package_method(self, state: ModuleState, args: T.Tuple[T.Optional[str]], kwargs: TYPE_kwargs) -> HoldableObject:
        name, *_ = args
        if name is None:
            name = state.project_name

        if name in self.exports:
            raise InvalidArguments(f'An export set called "{name}" already exists.')
        ex = Package(name)
        self.exports[name] = ex
        return ex

    def postconf_hook(self, b: Build) -> None:
        """Generate the actual export files, and create install data for them.

        :param b: the Build object
        """
        for entries in self.exports.values():
            entries.generate(b)


def initialize(interp: Interpreter) -> ExportModule:
    interp.holder_map[Package] = PackageHolder
    return ExportModule(interp)
