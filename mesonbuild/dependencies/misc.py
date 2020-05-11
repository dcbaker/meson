# Copyright 2013-2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file contains the detection logic for miscellaneous external dependencies.

from pathlib import Path
import functools
import re
import sysconfig
import typing as T

from .. import mlog
from .. import mesonlib
from ..environment import detect_cpu_family

from .base import (
    DependencyException, DependencyMethods, ExternalDependency,
    PkgConfigDependency, CMakeDependency, ConfigToolDependency,
    ExtraFrameworkDependency,
    factory_methods, DependencyFactory, find_external_program,
)

if T.TYPE_CHECKING:
    from ..environment import Environment, MachineChoice
    from .base import DependencyType  # noqa: F401


@factory_methods({DependencyMethods.PKGCONFIG, DependencyMethods.CMAKE})
def netcdf_factory(env: 'Environment', for_machine: 'MachineChoice',
                   kwargs: T.Dict[str, T.Any], methods: T.List[DependencyMethods]) -> T.List['DependencyType']:
    language = kwargs.get('language', 'c')
    if language not in ('c', 'cpp', 'fortran'):
        raise DependencyException('Language {} is not supported with NetCDF.'.format(language))

    candidates = []  # type: T.List['DependencyType']

    if DependencyMethods.PKGCONFIG in methods:
        if language == 'fortran':
            pkg = 'netcdf-fortran'
        else:
            pkg = 'netcdf'

        candidates.append(functools.partial(PkgConfigDependency, pkg, env, kwargs, language=language))

    if DependencyMethods.CMAKE in methods:
        candidates.append(functools.partial(CMakeDependency, 'NetCDF', env, kwargs, language=language))

    return candidates


class OpenMPDependency(ExternalDependency):
    # Map date of specification release (which is the macro value) to a version.
    VERSIONS = {
        '201811': '5.0',
        '201611': '5.0-revision1',  # This is supported by ICC 19.x
        '201511': '4.5',
        '201307': '4.0',
        '201107': '3.1',
        '200805': '3.0',
        '200505': '2.5',
        '200203': '2.0',
        '199810': '1.0',
    }

    def __init__(self, environment, kwargs):
        language = kwargs.get('language')
        super().__init__('openmp', environment, kwargs, language=language)
        self.is_found = False
        if self.clib_compiler.get_id() == 'pgi':
            # through at least PGI 19.4, there is no macro defined for OpenMP, but OpenMP 3.1 is supported.
            self.version = '3.1'
            self.is_found = True
            self.compile_args = self.link_args = self.clib_compiler.openmp_flags()
            return
        try:
            openmp_date = self.clib_compiler.get_define(
                '_OPENMP', '', self.env, self.clib_compiler.openmp_flags(), [self], disable_cache=True)[0]
        except mesonlib.EnvironmentException as e:
            mlog.debug('OpenMP support not available in the compiler')
            mlog.debug(e)
            openmp_date = None

        if openmp_date:
            self.version = self.VERSIONS[openmp_date]
            # Flang has omp_lib.h
            header_names = ('omp.h', 'omp_lib.h')
            for name in header_names:
                if self.clib_compiler.has_header(name, '', self.env, dependencies=[self], disable_cache=True)[0]:
                    self.is_found = True
                    self.compile_args = self.link_args = self.clib_compiler.openmp_flags()
                    break
            if not self.is_found:
                mlog.log(mlog.yellow('WARNING:'), 'OpenMP found but omp.h missing.')


class ThreadDependency(ExternalDependency):
    def __init__(self, name: str, environment, kwargs):
        super().__init__(name, environment, kwargs)
        self.is_found = True
        # Happens if you are using a language with threads
        # concept without C, such as plain Cuda.
        if self.clib_compiler is None:
            self.compile_args = []
            self.link_args = []
        else:
            self.compile_args = self.clib_compiler.thread_flags(environment)
            self.link_args = self.clib_compiler.thread_link_flags(environment)

    @staticmethod
    def get_methods():
        return [DependencyMethods.AUTO, DependencyMethods.CMAKE]


class BlocksDependency(ExternalDependency):
    def __init__(self, environment, kwargs):
        super().__init__('blocks', environment, kwargs)
        self.name = 'blocks'
        self.is_found = False

        if self.env.machines[self.for_machine].is_darwin():
            self.compile_args = []
            self.link_args = []
        else:
            self.compile_args = ['-fblocks']
            self.link_args = ['-lBlocksRuntime']

            if not self.clib_compiler.has_header('Block.h', '', environment, disable_cache=True) or \
               not self.clib_compiler.find_library('BlocksRuntime', environment, []):
                mlog.log(mlog.red('ERROR:'), 'BlocksRuntime not found.')
                return

        source = '''
            int main(int argc, char **argv)
            {
                int (^callback)(void) = ^ int (void) { return 0; };
                return callback();
            }'''

        with self.clib_compiler.compile(source, extra_args=self.compile_args + self.link_args) as p:
            if p.returncode != 0:
                mlog.log(mlog.red('ERROR:'), 'Compiler does not support blocks extension.')
                return

            self.is_found = True


@factory_methods({DependencyMethods.PKGCONFIG, DependencyMethods.SYSCONFIG, DependencyMethods.EXTRAFRAMEWORK})
def python_factory(env: 'Environment', for_machine: 'MachineChoice',
                   kwargs: T.Dict[str, T.Any], methods: T.List[DependencyMethods]) -> T.List['DependencyType']:
    """Python is a special kind of painful to find.

    Some Linux distros ship one version of python3, and a single pkg-config
    file, python3.pc. Other's ship multiple versions with python-3.X.pc
    pkg-config files. We want to search for all of those.
    """
    embed = kwargs.get('embed', False)
    choices = []  # type: T.List[DependencyType]
    if DependencyMethods.PKGCONFIG in methods:
        # In this case we want to find all cases of python3
        for prog in find_external_program(env, for_machine, 'pkgconfig', 'Pkg-config', env.default_pkgconfig):
            if not prog.found():
                continue
            p, *_ = mesonlib.Popen_safe(prog.get_command() + ['--version'])
            if p.returncode == 0:
                break
        else:
            mlog.debug("Couldn't find pkg-config.")
            return []

        p, out, _ = mesonlib.Popen_safe(prog.get_command() + ['--list-all'])
        if p.returncode != 0:
            mlog.debug("Failed to run pkg-config.")
            return []

        for pkg in reversed(sorted(out.split('\n'))):
            if pkg.startswith('python'):
                if embed:
                    p, modversion, _ = mesonlib.Popen_safe(prog.get_command() + [pkg, '--mod-version'])
                    if mesonlib.version_compare(modversion, '>= 3.8') and not pkg.endswith('-embed'):
                        continue
                choices.append(functools.partial(PkgConfigDependency, pkg.split(' ')[0], env, kwargs))
    if DependencyMethods.SYSCONFIG in methods:
        choices.append(functools.partial(PythonDependencySystem, 'python', env, kwargs))
    if DependencyMethods.EXTRAFRAMEWORK in methods:
        nwargs = kwargs.copy()
        nwargs['paths'] = ['/Library/Frameworks']
        choices.append(functools.partial(ExtraFrameworkDependency, 'Python', env, nwargs))
    return choices


class PythonDependencySystem(ExternalDependency):
    def __init__(self, name, environment, kwargs):
        super().__init__(name, environment, kwargs)

        if not environment.machines.matches_build_machine(self.for_machine):
            return

        self.name = 'python'
        self.static = kwargs.get('static', False)

        if mesonlib.is_windows():
            self._find_libpy_windows(environment)
        else:
            self._find_libpy(python_holder, environment)
        if self.is_found:
            mlog.debug('Found "python-{}" via SYSCONFIG module'.format(self.version))
            py_lookup_method = 'sysconfig'

    def _find_libpy(self, python_holder, environment):
        if python_holder.is_pypy:
            if self.major_version == 3:
                libname = 'pypy3-c'
            else:
                libname = 'pypy-c'
            libdir = os.path.join(self.variables.get('base'), 'bin')
            libdirs = [libdir]
        else:
            libname = 'python{}'.format(self.version)
            if 'DEBUG_EXT' in self.variables:
                libname += self.variables['DEBUG_EXT']
            if 'ABIFLAGS' in self.variables:
                libname += self.variables['ABIFLAGS']
            libdirs = []

        largs = self.clib_compiler.find_library(libname, environment, libdirs)
        if largs is not None:
            self.link_args = largs

        self.is_found = largs is not None or self.link_libpython

        inc_paths = mesonlib.OrderedSet([
            self.variables.get('INCLUDEPY'),
            self.paths.get('include'),
            self.paths.get('platinclude')])

        self.compile_args += ['-I' + path for path in inc_paths if path]

    def get_windows_python_arch(self):
        if self.platform == 'mingw':
            pycc = self.variables.get('CC')
            if pycc.startswith('x86_64'):
                return '64'
            elif pycc.startswith(('i686', 'i386')):
                return '32'
            else:
                mlog.log('MinGW Python built with unknown CC {!r}, please file'
                         'a bug'.format(pycc))
                return None
        elif self.platform == 'win32':
            return '32'
        elif self.platform in ('win64', 'win-amd64'):
            return '64'
        mlog.log('Unknown Windows Python platform {!r}'.format(self.platform))
        return None

    def get_windows_link_args(self):
        if self.platform.startswith('win'):
            vernum = self.variables.get('py_version_nodot')
            if self.static:
                libpath = Path('libs') / 'libpython{}.a'.format(vernum)
            else:
                comp = self.get_compiler()
                if comp.id == "gcc":
                    libpath = 'python{}.dll'.format(vernum)
                else:
                    libpath = Path('libs') / 'python{}.lib'.format(vernum)
            lib = Path(self.variables.get('base')) / libpath
        elif self.platform == 'mingw':
            if self.static:
                libname = self.variables.get('LIBRARY')
            else:
                libname = self.variables.get('LDLIBRARY')
            lib = Path(self.variables.get('LIBDIR')) / libname
        if not lib.exists():
            mlog.log('Could not find Python3 library {!r}'.format(str(lib)))
            return None
        return [str(lib)]

    def _find_libpy_windows(self, env):
        '''
        Find python3 libraries on Windows and also verify that the arch matches
        what we are building for.
        '''
        pyarch = self.get_windows_python_arch()
        if pyarch is None:
            self.is_found = False
            return
        arch = detect_cpu_family(env.coredata.compilers.host)
        if arch == 'x86':
            arch = '32'
        elif arch == 'x86_64':
            arch = '64'
        else:
            # We can't cross-compile Python 3 dependencies on Windows yet
            mlog.log('Unknown architecture {!r} for'.format(arch),
                     mlog.bold(self.name))
            self.is_found = False
            return
        # Pyarch ends in '32' or '64'
        if arch != pyarch:
            mlog.log('Need', mlog.bold(self.name), 'for {}-bit, but '
                     'found {}-bit'.format(arch, pyarch))
            self.is_found = False
            return
        # This can fail if the library is not found
        largs = self.get_windows_link_args()
        if largs is None:
            self.is_found = False
            return
        self.link_args = largs
        # Compile args
        inc_paths = mesonlib.OrderedSet([
            self.variables.get('INCLUDEPY'),
            self.paths.get('include'),
            self.paths.get('platinclude')])

        self.compile_args += ['-I' + path for path in inc_paths if path]

        # https://sourceforge.net/p/mingw-w64/mailman/message/30504611/
        if pyarch == '64' and self.major_version == 2:
            self.compile_args += ['-DMS_WIN64']

        self.is_found = True

    def log_tried(self):
        return 'sysconfig'

class PcapDependencyConfigTool(ConfigToolDependency):

    tools = ['pcap-config']
    tool_name = 'pcap-config'

    @staticmethod
    def finish_init(self) -> None:
        self.compile_args = self.get_config_value(['--cflags'], 'compile_args')
        self.link_args = self.get_config_value(['--libs'], 'link_args')
        self.version = self.get_pcap_lib_version()

    @staticmethod
    def get_methods():
        return [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL]

    def get_pcap_lib_version(self):
        # Since we seem to need to run a program to discover the pcap version,
        # we can't do that when cross-compiling
        if not self.env.machines.matches_build_machine(self.for_machine):
            return None

        v = self.clib_compiler.get_return_value('pcap_lib_version', 'string',
                                                '#include <pcap.h>', self.env, [], [self])
        v = re.sub(r'libpcap version ', '', v)
        v = re.sub(r' -- Apple version.*$', '', v)
        return v


class CupsDependencyConfigTool(ConfigToolDependency):

    tools = ['cups-config']
    tool_name = 'cups-config'

    @staticmethod
    def finish_init(ctdep):
        ctdep.compile_args = ctdep.get_config_value(['--cflags'], 'compile_args')
        ctdep.link_args = ctdep.get_config_value(['--ldflags', '--libs'], 'link_args')

    @staticmethod
    def get_methods():
        if mesonlib.is_osx():
            return [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL, DependencyMethods.EXTRAFRAMEWORK, DependencyMethods.CMAKE]
        else:
            return [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL, DependencyMethods.CMAKE]


class LibWmfDependencyConfigTool(ConfigToolDependency):

    tools = ['libwmf-config']
    tool_name = 'libwmf-config'

    @staticmethod
    def finish_init(ctdep):
        ctdep.compile_args = ctdep.get_config_value(['--cflags'], 'compile_args')
        ctdep.link_args = ctdep.get_config_value(['--libs'], 'link_args')

    @staticmethod
    def get_methods():
        return [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL]


class LibGCryptDependencyConfigTool(ConfigToolDependency):

    tools = ['libgcrypt-config']
    tool_name = 'libgcrypt-config'

    @staticmethod
    def finish_init(ctdep):
        ctdep.compile_args = ctdep.get_config_value(['--cflags'], 'compile_args')
        ctdep.link_args = ctdep.get_config_value(['--libs'], 'link_args')
        ctdep.version = ctdep.get_config_value(['--version'], 'version')[0]

    @staticmethod
    def get_methods():
        return [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL]


class GpgmeDependencyConfigTool(ConfigToolDependency):

    tools = ['gpgme-config']
    tool_name = 'gpg-config'

    @staticmethod
    def finish_init(ctdep):
        ctdep.compile_args = ctdep.get_config_value(['--cflags'], 'compile_args')
        ctdep.link_args = ctdep.get_config_value(['--libs'], 'link_args')
        ctdep.version = ctdep.get_config_value(['--version'], 'version')[0]

    @staticmethod
    def get_methods():
        return [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL]


class ShadercDependency(ExternalDependency):

    def __init__(self, environment, kwargs):
        super().__init__('shaderc', environment, kwargs)

        static_lib = 'shaderc_combined'
        shared_lib = 'shaderc_shared'

        libs = [shared_lib, static_lib]
        if self.static:
            libs.reverse()

        cc = self.get_compiler()

        for lib in libs:
            self.link_args = cc.find_library(lib, environment, [])
            if self.link_args is not None:
                self.is_found = True

                if self.static and lib != static_lib:
                    mlog.warning('Static library {!r} not found for dependency {!r}, may '
                                 'not be statically linked'.format(static_lib, self.name))

                break

    def log_tried(self):
        return 'system'

    @staticmethod
    def get_methods():
        return [DependencyMethods.SYSTEM, DependencyMethods.PKGCONFIG]


@factory_methods({DependencyMethods.PKGCONFIG})
def curses_factory(env: 'Environment', for_machine: 'MachineChoice',
                   kwargs: T.Dict[str, T.Any], methods: T.List[DependencyMethods]) -> T.List['DependencyType']:
    candidates = []  # type: T.List['DependencyType']

    if DependencyMethods.PKGCONFIG in methods:
        pkgconfig_files = ['ncurses', 'ncursesw']
        for pkg in pkgconfig_files:
            candidates.append(functools.partial(PkgConfigDependency, pkg, env, kwargs))

    return candidates


@factory_methods({DependencyMethods.PKGCONFIG, DependencyMethods.SYSTEM})
def shaderc_factory(env: 'Environment', for_machine: 'MachineChoice',
                    kwargs: T.Dict[str, T.Any], methods: T.List[DependencyMethods]) -> T.List['DependencyType']:
    """Custom DependencyFactory for ShaderC.

    ShaderC's odd you get three different libraries from the same build
    thing are just easier to represent as a separate function than
    twisting DependencyFactory even more.
    """
    candidates = []  # type: T.List['DependencyType']

    if DependencyMethods.PKGCONFIG in methods:
        # ShaderC packages their shared and static libs together
        # and provides different pkg-config files for each one. We
        # smooth over this difference by handling the static
        # keyword before handing off to the pkg-config handler.
        shared_libs = ['shaderc']
        static_libs = ['shaderc_combined', 'shaderc_static']

        if kwargs.get('static', False):
            c = [functools.partial(PkgConfigDependency, name, env, kwargs)
                 for name in static_libs + shared_libs]
        else:
            c = [functools.partial(PkgConfigDependency, name, env, kwargs)
                 for name in shared_libs + static_libs]
        candidates.extend(c)

    if DependencyMethods.SYSTEM in methods:
        candidates.append(functools.partial(ShadercDependency, env, kwargs))

    return candidates


cups_factory = DependencyFactory(
    'cups',
    [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL, DependencyMethods.EXTRAFRAMEWORK, DependencyMethods.CMAKE],
    configtool_class=CupsDependencyConfigTool,
    cmake_name='Cups',
)

gpgme_factory = DependencyFactory(
    'gpgme',
    [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL],
    configtool_class=GpgmeDependencyConfigTool,
)

libgcrypt_factory = DependencyFactory(
    'libgcrypt',
    [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL],
    configtool_class=LibGCryptDependencyConfigTool,
)

libwmf_factory = DependencyFactory(
    'libwmf',
    [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL],
    configtool_class=LibWmfDependencyConfigTool,
)

pcap_factory = DependencyFactory(
    'pcap',
    [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL],
    configtool_class=PcapDependencyConfigTool,
    pkgconfig_name='libpcap',
)

threads_factory = DependencyFactory(
    'threads',
    [DependencyMethods.SYSTEM, DependencyMethods.CMAKE],
    cmake_name='Threads',
    system_class=ThreadDependency,
)
