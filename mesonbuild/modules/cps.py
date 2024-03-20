# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

"""Support for the Common Package System dependency generation."""

from __future__ import annotations
import collections
import dataclasses
import itertools
import json
import os
import typing as T

from . import NewExtensionModule, ModuleInfo
from .. import build
from ..interpreter.type_checking import NoneType
from ..interpreterbase import (
    ContainerTypeInfo, KwargInfo, ObjectHolder, InvalidArguments, noPosargs,
    typed_kwargs, typed_pos_args,
)
from ..utils.universal import File, FileMode, HoldableObject, OptionKey

if T.TYPE_CHECKING:
    from typing_extensions import Literal, TypedDict

    from . import ModuleState
    from ..build import BuildTargetTypes
    from ..interpreter import Interpreter
    from ..interpreterbase import TYPE_var

    _KNOWN_LANGS = Literal['c', 'cpp', 'fortran']

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

    target: T.Optional[BuildTargetTypes]
    includes: T.Dict[str, T.List[str]]
    arguments: T.Dict[str, T.List[str]]
    default: bool


@dataclasses.dataclass
class Package(HoldableObject):

    """A Package with it's components and configurations."""

    name: str
    version: str
    description: T.Optional[str]
    license: T.Optional[str]
    components: T.Dict[str, Component] = dataclasses.field(default_factory=dict)


# languages that CPS specifically supports
_SUPPORTED_LANGS: T.Sequence[_KNOWN_LANGS] = ['c', 'cpp', 'fortran']

_COMPILE_KW: KwargInfo[T.List[str]] = KwargInfo(
    'arguments', ContainerTypeInfo(list, str), default=[], listify=True)

_COMPILE_KWS: T.List[KwargInfo[T.List[str]]] = [
    _COMPILE_KW.evolve(name=f'{c}_arguments') for c in _SUPPORTED_LANGS]
_COMPILE_KWS.append(_COMPILE_KW)

_INC_KWS: T.List[KwargInfo[T.List[str]]] = [
    _COMPILE_KW.evolve(name=f'{c}_include_directories') for c in _SUPPORTED_LANGS]
_INC_KWS.append(_COMPILE_KW.evolve(name='include_directories'))


class PackageHolder(ObjectHolder[Package]):

    def __init__(self, obj: Package, interp: Interpreter) -> None:
        super().__init__(obj, interp)
        self.methods.update({
            'add_component': self.add_component
        })

    @staticmethod
    def _process_per_language(tmpl: str, kwargs: T.Dict[str, T.List[str]]) -> T.Dict[str, T.List[str]]:
        processed: T.Dict[str, T.List[str]] = {}
        if kwargs[tmpl]:
            processed['*'] = kwargs[tmpl]
        for lang in _SUPPORTED_LANGS:
            lname = f'{lang}_{tmpl}'
            if kwargs[lname]:  # type: ignore[literal-required]
                processed[lang] = kwargs[lname]  # type: ignore[literal-required]
        return processed

    @typed_pos_args('cps_package.add_component', (build.BuildTarget, build.CustomTarget, build.CustomTargetIndex))
    @typed_kwargs(
        'cps_package.add_component',
        KwargInfo('name', (str, NoneType)),
        KwargInfo('default', bool, default=False),
        *_COMPILE_KWS,
        *_INC_KWS,
    )
    def add_component(self, args: T.Tuple[BuildTargetTypes], kwargs: CreateComponentKWs) -> None:
        # TODO: CustomTarget with more than 1 output
        # TODO: BothLibrary

        target = args[0]

        cname = kwargs['name'] or target.name
        if cname in self.held_object.components:
            raise InvalidArguments(f'Component "{cname}" of package "{self.held_object.name}" is already defined!')

        # TODO: warn about manually adding @prefix@ or absolute paths, also warn about -I forms

        includes = self._process_per_language('include_directories', kwargs)
        arguments = self._process_per_language('arguments', kwargs)

        self.held_object.components[cname] = Component(target, includes, arguments, kwargs['default'])
        # TODO: what if a target is in multiple packages?
        CPSModule.target_map[target] = (self.held_object.name, cname)

    @noPosargs
    @typed_kwargs(
        'cps_package.add_interface',
        KwargInfo('name', str, required=True),
        KwargInfo('default', bool, default=False),
        *_COMPILE_KWS,
        *_INC_KWS,
    )
    def add_interface(self, args: T.List[TYPE_var], kwargs: CreateComponentKWs) -> None:
        cname = kwargs['name']
        if cname in self.held_object.components:
            raise InvalidArguments(f'Component "{cname}" of package "{self.held_object.name}" is already defined!')

        # TODO: warn about manually adding @prefix@ or absolute paths, also warn about -I forms

        includes = self._process_per_language('include_directories', kwargs)
        arguments = self._process_per_language('arguments', kwargs)

        self.held_object.components[cname] = Component(None, includes, arguments, kwargs['default'])


class CPSModule(NewExtensionModule):

    INFO = ModuleInfo('cps', added='1.5.0')

    _packages: T.Dict[str, Package] = {}
    target_map: T.Dict[BuildTargetTypes, T.Tuple[str, str]] = {}

    def __init__(self) -> None:
        super().__init__()
        self.methods.update({
            'create_package': self.create_package,
        })

    @staticmethod
    def __split_arguments(args: T.Dict[str, T.List[str]]) -> T.Tuple[T.Dict[str, T.List[str]], T.Dict[str, T.List[str]]]:
        defines: T.DefaultDict[str, T.List[str]] = collections.defaultdict(list)
        arguments: T.DefaultDict[str, T.List[str]] = collections.defaultdict(list)

        for lang in itertools.chain(['*'], _SUPPORTED_LANGS):
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

        # TODO: need more than just a list of packages
        package_requires: T.Set[str] = set()

        def make_component(comp: Component) -> T.Dict:
            cdata: T.Dict = {}

            if isinstance(comp.target, build.Executable):
                cdata = {'type': 'executable'}
            elif isinstance(comp.target, build.StaticLibrary):
                cdata = {'type': 'archive'}
            elif isinstance(comp.target, build.SharedLibrary):
                cdata = {'type': 'dylib'}
            elif comp.target is not None:
                raise NotImplementedError(f'Have not implemented support for "{comp.target.typename}" yet')

            if not isinstance(comp.target, build.Executable):
                defines, arguments = self.__split_arguments(comp.arguments)

                # TODO: handle prefix correctly
                cdata = {
                    # TODO: handle @prefix@ and absolute paths?
                    'includes': {k: [os.path.join('@prefix@', i) for i in v] for k, v in comp.includes.items()},
                    'definitions': defines,
                    'compile_flags': arguments,
                }

                requires: T.List[str] = []
                if comp.target is not None:
                    for t in comp.target.get_transitive_link_deps(whole_targets=False):
                        if t not in self.target_map:
                            raise NotImplementedError('TODO: make a private component for this')
                        rpkg, rcomp = self.target_map[t]
                        if rpkg != package.name:
                            if rpkg not in self._packages:
                                raise InvalidArguments(f'Tried to depend on a package "{rpkg}", which will not have a CPS package generated.')
                            # TODO: validate that this component exists
                            requires.append(f'{rpkg}:{rcomp}')
                            package_requires.add(rpkg)
                        else:
                            # TODO: validate that this component exists
                            requires.append(f':{rcomp}')
                if requires:
                    cdata['requires'] = requires

            install_dir = comp.target.get_install_dir()[0][0]
            # It shouldn't be possible for the first element to be False, only
            # for any after that, and then only for Vala. At least for
            # BuildTargets, and CustomTargets aren't yet supported.
            assert isinstance(install_dir, str), 'for mypy'

            if comp.target is not None:
                cdata['location'] = os.path.join('@prefix@', install_dir, comp.target.get_outputs()[0])
            return cdata

        priv_dir = os.path.join(b.environment.build_dir, b.environment.private_dir)
        libdir = b.environment.coredata.get_option(OptionKey('libdir'))
        assert isinstance(libdir, str), 'for mypy'

        for package in self._packages.values():
            data = {
                'name': package.name,
                'version': package.version,
                'license' : package.license[0],
                'cps_version': '0.11.0',
                'components': {n: make_component(c) for n, c in package.components.items()},
            }
            if package_requires:
                # TODO: set the values for these if we can determine them
                data['requires'] = {k: None for k in package_requires}
            if package.description:
                data['description'] = package.description

            outfile = os.path.join(priv_dir, f'{package.name}.cps')
            with open(outfile, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)

            # TODO: platform agnostic install
            # TODO: subproject
            install_dir = os.path.join(libdir, 'cps', package.name, package.version)
            bdata = build.Data(
                [File.from_absolute_file(outfile)], install_dir, install_dir, FileMode(), '')
            b.data.append(bdata)

    @typed_pos_args('cps.create_package', str, optargs=[str])
    @typed_kwargs(
        'cps.create_package',
        KwargInfo('description', (str, NoneType)),
    )
    def create_package(self, state: ModuleState, args: T.Tuple[str, T.Optional[str]], kwargs: CreatePackageKWs) -> Package:
        name, version = args
        if version is None:
            version = state.project_version
        if name in self._packages:
            # TODO: provide a better error message about where this was defined
            raise InvalidArguments(f'A CPS package called {name} already exists')

        # TODO: license-files
        # TODO: what to do about multiple licenses instead of SPDX?
        license = state.build.dep_manifest[state.project_name].license
        p = self._packages[name] = Package(
            name,
            version,
            kwargs['description'],
            license[0] if license else None,
        )

        return p


def initialize(interp: Interpreter) -> CPSModule:
    interp.holder_map[Package] = PackageHolder
    return CPSModule()
