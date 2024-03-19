# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

"""Support for the Common Package System dependency generation."""

from __future__ import annotations
import collections
import dataclasses
import json
import os
import typing as T

from . import NewExtensionModule, ModuleInfo
from .. import build
from ..interpreter.type_checking import NoneType
from ..interpreterbase import KwargInfo, typed_pos_args, typed_kwargs, InvalidArguments, ContainerTypeInfo

if T.TYPE_CHECKING:
    from typing_extensions import TypedDict

    from . import ModuleState
    from ..build import BuildTargetTypes
    from ..interpreter import Interpreter

    class CreatePackageKWs(TypedDict):

        description: T.Optional[str]

    class CreateComponentKWs(TypedDict):

        name: T.Optional[str]
        default: bool

        include_directories: T.List[str]
        c_include_directories: T.List[str]
        cpp_include_directories: T.List[str]
        fortran_include_directories: T.List[str]

        arguments: T.List[str]
        c_arguments: T.List[str]
        cpp_arguments: T.List[str]
        fortran_arguments: T.List[str]


@dataclasses.dataclass
class Component:

    target: BuildTargetTypes
    includes: T.Dict[str, build.IncludeDirs]
    arguments: T.Dict[str, T.List[str]]
    default: bool


@dataclasses.dataclass
class Package:

    """A Package with it's components and configurations."""

    name: str
    version: str
    description: T.Optional[str]
    license: T.Optional[str]
    components: T.Dict[str, Component] = dataclasses.field(default_factory=dict)


# languages that CPS specifically supports
_SUPPORTED_LANGS: T.Sequence[str] = ['c', 'cpp', 'fortran']

_COMPILE_KW: KwargInfo[T.List[str]] = KwargInfo(
    'arguments', ContainerTypeInfo(list, str), default=[], listify=True)

_COMPILE_KWS: T.List[KwargInfo[T.List[str]]] = [
    _COMPILE_KW.evolve(name=f'{c}_arguments') for c in _SUPPORTED_LANGS]
_COMPILE_KWS.append(_COMPILE_KW)

_INC_KWS: T.List[KwargInfo[T.List[str]]] = [
    _COMPILE_KW.evolve(name=f'{c}_include_directories') for c in _SUPPORTED_LANGS]
_INC_KWS.append(_COMPILE_KW.evolve(name='include_directories'))


class CPSModule(NewExtensionModule):

    INFO = ModuleInfo('cps', added='1.5.0')

    _packages: T.Dict[str, Package] = {}

    def __init__(self) -> None:
        super().__init__()
        self.methods.update({
            'create_package': self.create_package,
            'create_component': self.create_component,
        })

    @staticmethod
    def __split_arguments(args: T.Dict[str, T.List[str]]) -> T.Tuple[T.Dict[str, T.List[str]], T.Dict[str, T.List[str]]]:
        defines: T.DefaultDict[str, T.List[str]] = collections.defaultdict(list)
        arguments: T.DefaultDict[str, T.List[str]] = collections.defaultdict(list)

        for lang in ['*'] + _SUPPORTED_LANGS:
            if lang not in args:
                continue
            for a in args[lang]:
                if a.startswith(('-D', '/D')):
                    defines[lang].append(a[1:])
                elif a.startswith(('-U','/I')):
                    defines[lang].append(f'!{a[1:]}')
                else:
                    arguments[lang].append(a)

        return defines, arguments

    def postconf_hook(self, b: build.Build) -> None:

        def make_component(comp: Component) -> T.Dict:
            cdata: T.Dict = {}
            if isinstance(comp.target, build.Executable):
                cdata = {'type': 'executable'}
            elif isinstance(comp.target, (build.StaticLibrary, build.SharedLibrary)):
                defines, arguments = self.__split_arguments(comp.arguments)

                # TODO: handle prefix correctly
                cdata = {
                    'type': 'archive' if isinstance(comp.target, build.StaticLibrary) else 'dylib',
                    # TODO: handle @prefix@ and absolute paths?
                    'includes': {k: [os.path.join('@prefix@', i) for i in v] for k, v in comp.includes.items()},
                    'definitions': defines,
                    'compile_flags': arguments,
                }
            else:
                raise NotImplementedError(f'Have not implemented support for "{comp.target.typename}" yet')

            cdata['location'] = os.path.join(
                '@prefix@',
                comp.target.get_install_dir()[0][0],
                comp.target.get_outputs()[0],
            )
            return cdata

        priv_dir = os.path.join(b.environment.build_dir, b.environment.private_dir)

        for package in self._packages.values():
            data = {
                'name': package.name,
                'version': package.version,
                'license' : package.license[0],
                'cps_version': '0.11.0',
                'components': {n: make_component(c) for n, c in package.components.items()},
            }
            if package.description:
                data['description'] = package.description

            with open(os.path.join(priv_dir, f'{package.name}.cps'), 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)

    @typed_pos_args('cps.create_package', str, optargs=[str])
    @typed_kwargs(
        'cps.create_package',
        KwargInfo('description', (str, NoneType)),
    )
    def create_package(self, state: ModuleState, args: T.Tuple[str, T.Optional[str]], kwargs: CreatePackageKWs) -> None:
        name, version = args
        if version is None:
            version = state.project_version
        if name in self._packages:
            # TODO: provide a better error message about where this was defined
            raise InvalidArguments(f'A CPS package called {name} already exists')
        self._packages[name] = Package(
            name,
            version,
            kwargs['description'],
            state.build.dep_manifest[state.project_name].license,  # TODO: license-files?
        )

    @typed_pos_args('cps.create_component', str, (build.BuildTarget, build.CustomTarget, build.CustomTargetIndex))
    @typed_kwargs(
        'cps.create_component',
        KwargInfo('name', (str, NoneType)),
        KwargInfo('default', bool, default=False),
        *_COMPILE_KWS,
        *_INC_KWS,
    )
    def create_component(self, state: ModuleState, args: T.Tuple[str, BuildTargetTypes], kwargs: CreateComponentKWs) -> None:
        # TODO: CustomTarget with more than 1 output
        # TODO: BothLibrary

        pname, target = args
        try:
            package = self._packages[pname]
        except KeyError:
            raise InvalidArguments(f'Tried to use a package "{pname}" that has not been defined.')

        cname = kwargs['name'] or target.name
        if cname in package.components:
            raise InvalidArguments(f'Component "{cname}" of package "{pname}" is already defined!')

        # TODO: warn about manually adding @prefix@ or absolute paths, also warn about -I forms

        includes: T.Dict[str, T.List[str]] = {}
        if kwargs['include_directories']:
            includes['*'] = kwargs['include_directories']
        for lang in _SUPPORTED_LANGS:
            lname = f'{lang}_include_directories'
            if kwargs[lname]:
                includes[lang] = kwargs[lname]

        arguments: T.Dict[str, T.List[str]] = {}
        if kwargs['arguments']:
            arguments['*'] = kwargs['arguments']
        for lang in _SUPPORTED_LANGS:
            lname = f'{lang}_arguments'
            if kwargs[lname]:
                arguments[lang] = kwargs[lname]

        package.components[cname] = Component(target, includes, arguments, kwargs['default'])


def initialize(interp: Interpreter) -> CPSModule:
    return CPSModule()
