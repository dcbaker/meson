# Copyright 2018 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import json
import shutil
import typing as T

from pathlib import Path
from .. import mesonlib
from ..mesonlib import MachineChoice, MesonException
from . import ExtensionModule
from mesonbuild.modules import ModuleReturnValue
from ..interpreterbase import (
    noPosargs, noKwargs, permittedKwargs,
    InvalidArguments,
    FeatureNew, FeatureNewKwargs, disablerIfNotFound
)
from ..interpreter import ExternalProgramHolder, extract_required_kwarg, permitted_kwargs
from ..build import known_shmod_kwargs
from .. import mlog
from ..environment import detect_cpu_family
from ..dependencies.base import (
    DependencyMethods, ExternalDependency,
    ExternalProgram, PkgConfigDependency,
    NonExistingExternalProgram
)
from ..dependencies.misc import python_factory

mod_kwargs = set(['subdir'])
mod_kwargs.update(known_shmod_kwargs)
mod_kwargs -= set(['name_prefix', 'name_suffix'])



INTROSPECT_COMMAND = '''import sysconfig
import json
import sys

install_paths = sysconfig.get_paths(scheme='posix_prefix', vars={'base': '', 'platbase': '', 'installed_base': ''})

def links_against_libpython():
    from distutils.core import Distribution, Extension
    cmd = Distribution().get_command_obj('build_ext')
    cmd.ensure_finalized()
    return bool(cmd.get_libraries(Extension('dummy', [])))

print (json.dumps ({
  'variables': sysconfig.get_config_vars(),
  'paths': sysconfig.get_paths(),
  'install_paths': install_paths,
  'version': sysconfig.get_python_version(),
  'platform': sysconfig.get_platform(),
  'is_pypy': '__pypy__' in sys.builtin_module_names,
  'link_libpython': links_against_libpython(),
}))
'''


class PythonInstallation(ExternalProgramHolder):
    def __init__(self, interpreter, python, info):
        ExternalProgramHolder.__init__(self, python, interpreter.subproject)
        self.interpreter = interpreter
        self.subproject = self.interpreter.subproject
        prefix = self.interpreter.environment.coredata.get_builtin_option('prefix')
        self.variables = info['variables']
        self.paths = info['paths']
        install_paths = info['install_paths']
        self.platlib_install_path = os.path.join(prefix, install_paths['platlib'][1:])
        self.purelib_install_path = os.path.join(prefix, install_paths['purelib'][1:])
        self.version = info['version']
        self.platform = info['platform']
        self.is_pypy = info['is_pypy']
        self.link_libpython = info['link_libpython']
        self.methods.update({
            'extension_module': self.extension_module_method,
            'dependency': self.dependency_method,
            'install_sources': self.install_sources_method,
            'get_install_dir': self.get_install_dir_method,
            'language_version': self.language_version_method,
            'found': self.found_method,
            'has_path': self.has_path_method,
            'get_path': self.get_path_method,
            'has_variable': self.has_variable_method,
            'get_variable': self.get_variable_method,
            'path': self.path_method,
        })

    @permittedKwargs(mod_kwargs)
    def extension_module_method(self, args, kwargs):
        if 'subdir' in kwargs and 'install_dir' in kwargs:
            raise InvalidArguments('"subdir" and "install_dir" are mutually exclusive')

        if 'subdir' in kwargs:
            subdir = kwargs.pop('subdir', '')
            if not isinstance(subdir, str):
                raise InvalidArguments('"subdir" argument must be a string.')

            kwargs['install_dir'] = os.path.join(self.platlib_install_path, subdir)

        # On macOS and some Linux distros (Debian) distutils doesn't link
        # extensions against libpython. We call into distutils and mirror its
        # behavior. See https://github.com/mesonbuild/meson/issues/4117
        if not self.link_libpython:
            new_deps = []
            for holder in mesonlib.extract_as_list(kwargs, 'dependencies'):
                dep = holder.held_object
                if dep.name in {'python', 'python2', 'python3'}:
                    holder = self.interpreter.holderify(dep.get_partial_dependency(compile_args=True))
                new_deps.append(holder)
            kwargs['dependencies'] = new_deps

        suffix = self.variables.get('EXT_SUFFIX') or self.variables.get('SO') or self.variables.get('.so')

        # msys2's python3 has "-cpython-36m.dll", we have to be clever
        split = suffix.rsplit('.', 1)
        suffix = split.pop(-1)
        args[0] += ''.join(s for s in split)

        kwargs['name_prefix'] = ''
        kwargs['name_suffix'] = suffix

        return self.interpreter.func_shared_module(None, args, kwargs)

    @permittedKwargs(permitted_kwargs['dependency'])
    @FeatureNewKwargs('python_installation.dependency', '0.53.0', ['embed'])
    def dependency_method(self, args, kwargs):
        if args:
            mlog.warning('python_installation.dependency() does not take any '
                         'positional arguments. It always returns a Python '
                         'dependency. This will become an error in the future.',
                         location=self.interpreter.current_node)
        if 'version' in kwargs:
            mlog.warning('Passing "version" to py_installation.dependency() '
                         'is ignored. use pymod.find_installation(version) or '
                         'dependency(python, version) instead.')
        kwargs = kwargs.copy()
        kwargs['version'] = '== {}'.format(self.version)
        for pdep in python_factory(self.interpreter.environment, MachineChoice.BUILD, kwargs):
            dep = pdep()
            if dep.found():
                break
        else:
            raise MesonException('Somehow we didn\'t find a dependency for the python interpreter?')
        return self.interpreter.holderify(dep)

    @permittedKwargs(['pure', 'subdir'])
    def install_sources_method(self, args, kwargs):
        pure = kwargs.pop('pure', False)
        if not isinstance(pure, bool):
            raise InvalidArguments('"pure" argument must be a boolean.')

        subdir = kwargs.pop('subdir', '')
        if not isinstance(subdir, str):
            raise InvalidArguments('"subdir" argument must be a string.')

        if pure:
            kwargs['install_dir'] = os.path.join(self.purelib_install_path, subdir)
        else:
            kwargs['install_dir'] = os.path.join(self.platlib_install_path, subdir)

        return self.interpreter.holderify(self.interpreter.func_install_data(None, args, kwargs))

    @noPosargs
    @permittedKwargs(['pure', 'subdir'])
    def get_install_dir_method(self, args, kwargs):
        pure = kwargs.pop('pure', True)
        if not isinstance(pure, bool):
            raise InvalidArguments('"pure" argument must be a boolean.')

        subdir = kwargs.pop('subdir', '')
        if not isinstance(subdir, str):
            raise InvalidArguments('"subdir" argument must be a string.')

        if pure:
            res = os.path.join(self.purelib_install_path, subdir)
        else:
            res = os.path.join(self.platlib_install_path, subdir)

        return self.interpreter.module_method_callback(ModuleReturnValue(res, []))

    @noPosargs
    @noKwargs
    def language_version_method(self, args, kwargs):
        return self.interpreter.module_method_callback(ModuleReturnValue(self.version, []))

    @noKwargs
    def has_path_method(self, args, kwargs):
        if len(args) != 1:
            raise InvalidArguments('has_path takes exactly one positional argument.')
        path_name = args[0]
        if not isinstance(path_name, str):
            raise InvalidArguments('has_path argument must be a string.')

        return self.interpreter.module_method_callback(ModuleReturnValue(path_name in self.paths, []))

    @noKwargs
    def get_path_method(self, args, kwargs):
        if len(args) not in (1, 2):
            raise InvalidArguments('get_path must have one or two arguments.')
        path_name = args[0]
        if not isinstance(path_name, str):
            raise InvalidArguments('get_path argument must be a string.')

        try:
            path = self.paths[path_name]
        except KeyError:
            if len(args) == 2:
                path = args[1]
            else:
                raise InvalidArguments('{} is not a valid path name'.format(path_name))

        return self.interpreter.module_method_callback(ModuleReturnValue(path, []))

    @noKwargs
    def has_variable_method(self, args, kwargs):
        if len(args) != 1:
            raise InvalidArguments('has_variable takes exactly one positional argument.')
        var_name = args[0]
        if not isinstance(var_name, str):
            raise InvalidArguments('has_variable argument must be a string.')

        return self.interpreter.module_method_callback(ModuleReturnValue(var_name in self.variables, []))

    @noKwargs
    def get_variable_method(self, args, kwargs):
        if len(args) not in (1, 2):
            raise InvalidArguments('get_variable must have one or two arguments.')
        var_name = args[0]
        if not isinstance(var_name, str):
            raise InvalidArguments('get_variable argument must be a string.')

        try:
            var = self.variables[var_name]
        except KeyError:
            if len(args) == 2:
                var = args[1]
            else:
                raise InvalidArguments('{} is not a valid variable name'.format(var_name))

        return self.interpreter.module_method_callback(ModuleReturnValue(var, []))

    @noPosargs
    @noKwargs
    @FeatureNew('Python module path method', '0.50.0')
    def path_method(self, args, kwargs):
        return super().path_method(args, kwargs)


class PythonModule(ExtensionModule):

    @FeatureNew('Python Module', '0.46.0')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snippets.add('find_installation')

    # https://www.python.org/dev/peps/pep-0397/
    def _get_win_pythonpath(self, name_or_path):
        if name_or_path not in ['python2', 'python3']:
            return None
        if not shutil.which('py'):
            # program not installed, return without an exception
            return None
        ver = {'python2': '-2', 'python3': '-3'}[name_or_path]
        cmd = ['py', ver, '-c', "import sysconfig; print(sysconfig.get_config_var('BINDIR'))"]
        _, stdout, _ = mesonlib.Popen_safe(cmd)
        directory = stdout.strip()
        if os.path.exists(directory):
            return os.path.join(directory, 'python')
        else:
            return None

    @staticmethod
    def check_python(prog: 'ExternalProgram', version: T.Union[str, T.List[str]],
                     modules: T.List[str]) -> T.Tuple[bool, T.List[str], T.List[str]]:
        if not prog.found():
            return (False, [], [])

        p, out, _ = mesonlib.Popen_safe(prog.get_command() + ['--version'])
        if p.returncode != 0:
            mlog.debug('failed to run {}'.format(version))
            return (False, [], [])
        if version and not mesonlib.version_compare_many(out, version):
            mlog.debug('Version {} does not match {}'.format(out, version))
            return (False, [], [])

        if modules:
            found_modules = []    # type: T.List[str]
            missing_modules = []  # type: T.List[str]

            for mod in modules:
                p, *_ = mesonlib.Popen_safe(
                    prog.get_command() +
                    ['-c', 'import {0}'.format(mod)])
                if p.returncode != 0:
                    missing_modules.append(mod)
                else:
                    found_modules.append(mod)

            return (bool(missing_modules), found_modules, missing_modules)

        return (True, [], [])

    @FeatureNewKwargs('python.find_installation', '0.49.0', ['disabler'])
    @FeatureNewKwargs('python.find_installation', '0.51.0', ['modules'])
    @FeatureNewKwargs('python.find_installation', '0.55.0', ['version'])
    @disablerIfNotFound
    @permittedKwargs({'required', 'modules'})
    def find_installation(self, interpreter, state, args, kwargs):
        feature_check = FeatureNew('Passing "feature" option to find_installation', '0.48.0')
        disabled, required, feature = extract_required_kwarg(kwargs, state.subproject, feature_check)
        want_modules = mesonlib.extract_as_list(kwargs, 'modules')  # type: T.List[str]
        version = kwargs.get('version', []).copy()

        if len(args) > 1:
            raise InvalidArguments('find_installation takes zero or one positional argument.')

        name = 'python3'
        if args:
            if not isinstance(args[0], str):
                raise InvalidArguments('find_installation argument must be a string.')
            if 'python2' in args[0]:
                name = 'python2'
                version.append('<3.0')
            elif 'python3' in args[0]:
                name = 'python3'
                version.append('>=3.0')
            else:
                name = 'python'

        if disabled:
            mlog.log('Program', name, 'found:', mlog.red('NO'), '(disabled by:', mlog.bold(feature), ')')
            return ExternalProgramHolder(NonExistingExternalProgram(), state.subproject)

        _potentials = ['python']
        if name != 'python3':
            _potentials.append('python2')
        if name != 'python2':
            _potentials.append('python3')
        potentials = [state.environment.lookup_binary_entry(MachineChoice.HOST, p)
                      for p in reversed(_potentials)]

        if args:
            potentials.append(args[0])
        potentials.extend([
            'python3',
            'python2',
            'python',
            mesonlib.python_command
        ])
        if mesonlib.is_windows():
            for p in ['python3', 'python2', 'python']:
                py = self._get_win_pythonpath(p)
                if py is not None:
                    potentials.append(py)

        for p in potentials:
            python = ExternalProgram(name, p, silent=True)
            msg = ['Program', python.name]
            if want_modules:
                msg.append('({})'.format(', '.join(want_modules)))

            ok, found_modules, missing_modules = self.check_python(python, version, want_modules)
            msg.append('found:')
            if ok and python.found() and not missing_modules:
                msg.extend([mlog.green('YES'), '({})'.format(' '.join(python.command))])
            else:
                msg.append(mlog.red('NO'))
            if found_modules:
                msg.append('modules:')
                msg.append(', '.join(found_modules))

            mlog.debug(*msg)
            if ok:
                break

        mlog.log(*msg)

        if not python.found():
            if required:
                raise mesonlib.MesonException('{} not found'.format(name or 'python'))
            res = ExternalProgramHolder(NonExistingExternalProgram(), state.subproject)
        elif missing_modules:
            if required:
                raise mesonlib.MesonException('{} is missing modules: {}'.format(name or 'python', ', '.join(missing_modules)))
            res = ExternalProgramHolder(NonExistingExternalProgram(), state.subproject)
        else:
            # Sanity check, we expect to have something that at least quacks in tune
            try:
                cmd = python.get_command() + ['-c', INTROSPECT_COMMAND]
                p, stdout, stderr = mesonlib.Popen_safe(cmd)
                info = json.loads(stdout)
            except json.JSONDecodeError:
                info = None
                mlog.debug('Could not introspect Python (%s): exit code %d' % (str(p.args), p.returncode))
                mlog.debug('Program stdout:\n')
                mlog.debug(stdout)
                mlog.debug('Program stderr:\n')
                mlog.debug(stderr)

            res = PythonInstallation(interpreter, python, info)

        return res


def initialize(*args, **kwargs):
    return PythonModule(*args, **kwargs)
