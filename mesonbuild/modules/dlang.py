# Copyright 2018 The Meson development team
# Copyright © 2020 Intel Corporation

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file contains the detection logic for external dependencies that
# are UI-related.

import json
from mesonbuild.interpreterbase import FeatureNew, permittedKwargs
import os
import typing as T

from . import ExtensionModule, ModuleReturnValue
from .. import mlog
from ..mesonlib import (
    Popen_safe, listify, unholder
)
from ..dependencies.base import (
    ExternalProgram, DubDependency, NonExistingExternalProgram
)
from ..build import Executable, InvalidArguments, BuildTarget
from ..interpreter import ExecutableHolder

if T.TYPE_CHECKING:
    from ..interpreter import Interpreter, ModuleState


class DlangModule(ExtensionModule):
    dubbin: T.Optional[ExternalProgram] = None
    __init_dub = False

    def __init__(self, interpreter: 'Interpreter'):
        super().__init__(interpreter)
        self.snippets.add('generate_dub_file')

    @classmethod
    def _init_dub(cls) -> None:
        cls.__init_dub = True
        cls.dubbin = cls.__find_dub()

    def generate_dub_file(self, interpreter: 'Interpreter', state: 'ModuleState', args: T.List[T.Any], kwargs: T.Dict[str, T.Any]) -> None:
        if not self.__init_dub:
            self._init_dub()

        if not len(args) == 2:
            raise InvalidArguments('dlang_mod.generate_dub_file takes exactly 2 positional arguments')
        name: str = args[0]
        if not isinstance(name, str):
            raise InvalidArguments('dlang_mod.generate_dub_file argument 1 must be a string')
        path: str = args[1]
        if not isinstance(path, str):
            raise InvalidArguments('dlang_mod.generate_dub_file argument 2 must be a string')

        # TODO: a typed dict would be much better for this
        config: T.Dict[str, T.Union[str, T.Dict[str, str]]] = {'name': name}

        config_path = os.path.join(path, 'dub.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf8') as ofile:
                try:
                    config = json.load(ofile)
                except ValueError:
                    mlog.warning('Failed to load the data in dub.json')

        warn_publishing = ['description', 'license']
        for arg in warn_publishing:
            if arg not in kwargs and arg not in config:
                mlog.warning('Without', mlog.bold(arg), 'the DUB package can\'t be published')

        for key, value in kwargs.items():
            if key == 'dependencies':
                _config: T.Dict[str, str] = {}
                for dep in unholder(listify(value)):
                    if isinstance(dep, DubDependency):
                        ret, _ = self._call_dubbin(['describe', dep.name])
                        if ret == 0:
                            _config[name] = dep.version or ''
                config[key] = _config
            else:
                config[key] = value

        with open(config_path, 'w', encoding='utf8') as ofile:
            ofile.write(json.dumps(config, indent=4, ensure_ascii=False))

    def _call_dubbin(self, args: T.List[str], env: T.Optional[T.Dict[str, str]] = None) -> T.Tuple[int, str]:
        p, out = Popen_safe(self.dubbin.get_command() + args, env=env)[0:2]
        return p.returncode, out.strip()

    @staticmethod
    def __find_dub() -> ExternalProgram:
        """try to find a working dub instlalation."""
        dubbin = ExternalProgram('dub', silent=True)
        if dubbin.found():
            try:
                p, out = Popen_safe(dubbin.get_command() + ['--version'])[0:2]
                if p.returncode != 0:
                    mlog.warning('Found dub {!r} but couldn\'t run it'
                                 ''.format(' '.join(dubbin.get_command())))
                    # Set to False instead of None to signify that we've already
                    # searched for it and not found it
                    dubbin = NonExistingExternalProgram('dub')
            except (FileNotFoundError, PermissionError):
                dubbin = NonExistingExternalProgram('dub')
        else:
            dubbin = NonExistingExternalProgram('dub')
        if dubbin.found():
            mlog.log('Found DUB:', mlog.bold(dubbin.get_path()),
                     '(%s)' % out.strip())
        else:
            mlog.log('Found DUB:', mlog.red('NO'))
        return dubbin

    @FeatureNew('dlang_module.test', '0.57.0')
    @permittedKwargs({'d_args', 'link_args'})
    def test(self, state: 'ModuleState', args: T.List[T.Any], kwargs: T.Dict[str, T.Any]) -> ModuleReturnValue:
        """Generate a Dlang unittest target from another target."""
        if not len(args) == 2:
            raise InvalidArguments('dlang_mod.test takes exactly 2 positional arguments')

        name: str = args[0]
        if not isinstance(name, str):
            raise InvalidArguments('first argument (name) to dlang_md.test must be a string.')

        target: BuildTarget = unholder(args[1])
        if not isinstance(target, BuildTarget):
            raise InvalidArguments('second argument (name) to dlang_md.test must be a build target (library or executable).')

        d_args: T.List[str] = unholder(listify(kwargs.get('d_args', [])))
        for a in d_args:
            if not isinstance(a, str):
                raise InvalidArguments('dlang_mod.test keyword argument "d_args" must be a string or lists of strings.')

        link_args: T.List[str] = unholder(listify(kwargs.get('link_args', [])))
        for a in link_args:
            if not isinstance(a, str):
                raise InvalidArguments('dlang_mod.test keyword argument "link_args" must be a string or lists of strings.')

        if not 'd' in target.compilers:
            raise InvalidArguments('second argument (name) todlang_md.test must use D language.')

        # TODO: should probably test that unitest args aren't already in arguments?

        dc = state.environment.coredata.compilers[target.for_machine]['d']

        new_target = Executable(
            name,
            target.subdir,
            state.subproject,
            target.for_machine,
            target.sources,
            target.objects,
            target.environment,
            {
                'd_args': d_args + dc.get_build_unittest_args(),
                'link_args': link_args + dc.get_build_unittest_args(),
                'install': False,
            }
        )

        e = ExecutableHolder(new_target, self.interpreter)
        test = self.interpreter.make_test(
            self.interpreter.current_node, [name, e], {})

        return ModuleReturnValue([], [e, test])


def initialize(*args: T.Any, **kwargs: T.Any) -> DlangModule:
    return DlangModule(*args, **kwargs)
