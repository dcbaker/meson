# Copyright 2012-2017 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import abc
import os
import shlex
import typing

from . import mesonlib

if typing.TYPE_CHECKING:
    from .coredata import OptionDictType
    from .environment import Environment


class StaticLinker:

    def __init__(self, exelist: typing.List[str]):
        self.exelist = exelist

    def can_linker_accept_rsp(self) -> bool:
        """
        Determines whether the linker can accept arguments using the @rsp syntax.
        """
        return mesonlib.is_windows()

    def get_base_link_args(self, options: 'OptionDictType') -> typing.List[str]:
        """Like compilers.get_base_link_args, but for the static linker."""
        return []

    def get_exelist(self) -> typing.List[str]:
        return self.exelist.copy()

    def get_std_link_args(self) -> typing.List[str]:
        return []

    def get_buildtype_linker_args(self, buildtype: str) -> typing.List[str]:
        return []

    def get_output_args(self, target: str) -> typing.List[str]:
        return[]

    def get_coverage_link_args(self) -> typing.List[str]:
        return []

    def build_rpath_args(self, build_dir: str, from_dir: str, rpath_paths: str,
                         build_rpath: str, install_rpath: str) -> typing.List[str]:
        return []

    def thread_link_flags(self, env: 'Environment') -> typing.List[str]:
        return []

    def openmp_flags(self) -> typing.List[str]:
        return []

    def get_option_link_args(self, options: 'OptionDictType') -> typing.List[str]:
        return []

    @classmethod
    def unix_args_to_native(cls, args: typing.List[str]) -> typing.List[str]:
        return args

    def get_link_debugfile_args(self, targetfile: str) -> typing.List[str]:
        # Static libraries do not have PDB files
        return []

    def get_always_args(self) -> typing.List[str]:
        return []

    def get_linker_always_args(self) -> typing.List[str]:
        return []


class VisualStudioLikeLinker:
    always_args = ['/NOLOGO']

    def __init__(self, machine: str):
        self.machine = machine

    def get_always_args(self) -> typing.List[str]:
        return self.always_args.copy()

    def get_linker_always_args(self) -> typing.List[str]:
        return self.always_args.copy()

    def get_output_args(self, target: str) -> typing.List[str]:
        args = []  # type: typing.List[str]
        if self.machine:
            args += ['/MACHINE:' + self.machine]
        args += ['/OUT:' + target]
        return args

    @classmethod
    def unix_args_to_native(cls, args: typing.List[str]) -> typing.List[str]:
        from .compilers import VisualStudioCCompiler
        return VisualStudioCCompiler.unix_args_to_native(args)


class VisualStudioLinker(VisualStudioLikeLinker, StaticLinker):

    """Microsoft's lib static linker."""

    def __init__(self, exelist: typing.List[str], machine: str):
        StaticLinker.__init__(self, exelist)
        VisualStudioLikeLinker.__init__(self, machine)


class IntelVisualStudioLinker(VisualStudioLikeLinker, StaticLinker):

    """Intel's xilib static linker."""

    def __init__(self, exelist: typing.List[str], machine: str):
        StaticLinker.__init__(self, exelist)
        VisualStudioLikeLinker.__init__(self, machine)


class ArLinker(StaticLinker):

    def __init__(self, exelist: typing.List[str]):
        super().__init__(exelist)
        self.id = 'ar'
        pc, stdo = mesonlib.Popen_safe(self.exelist + ['-h'])[0:2]
        # Enable deterministic builds if they are available.
        if '[D]' in stdo:
            self.std_args = ['csrD']
        else:
            self.std_args = ['csr']

    def get_std_link_args(self) -> typing.List[str]:
        return self.std_args

    def get_output_args(self, target: str) -> typing.List[str]:
        return [target]


class ArmarLinker(ArLinker):

    def __init__(self, exelist: typing.List[str]):
        StaticLinker.__init__(self, exelist)
        self.id = 'armar'
        self.std_args = ['-csr']

    def can_linker_accept_rsp(self) -> bool:
        # armar cann't accept arguments using the @rsp syntax
        return False


class DLinker(StaticLinker):
    def __init__(self, exelist: typing.List[str], arch: str):
        super().__init__(exelist)
        self.id = exelist[0]
        self.arch = arch

    def get_std_link_args(self) -> typing.List[str]:
        return ['-lib']

    def get_output_args(self, target: str) -> typing.List[str]:
        return ['-of=' + target]

    def get_linker_always_args(self) -> typing.List[str]:
        if mesonlib.is_windows():
            if self.arch == 'x86_64':
                return ['-m64']
            elif self.arch == 'x86_mscoff' and self.id == 'dmd':
                return ['-m32mscoff']
            return ['-m32']
        return []


class CcrxLinker(StaticLinker):

    def __init__(self, exelist: typing.List[str]):
        super().__init__(exelist)
        self.id = 'rlink'

    def can_linker_accept_rsp(self) -> bool:
        return False

    def get_output_args(self, target: str) -> typing.List[str]:
        return ['-output=%s' % target]

    def get_linker_always_args(self) -> typing.List[str]:
        return ['-nologo', '-form=library']


def prepare_rpaths(raw_rpaths: str, build_dir: str, from_dir: str) -> typing.List[str]:
    # The rpaths we write must be relative if they point to the build dir,
    # because otherwise they have different length depending on the build
    # directory. This breaks reproducible builds.
    internal_format_rpaths = [evaluate_rpath(p, build_dir, from_dir) for p in raw_rpaths]
    ordered_rpaths = order_rpaths(internal_format_rpaths)
    return ordered_rpaths


def order_rpaths(rpath_list: typing.List[str]) -> typing.List[str]:
    # We want rpaths that point inside our build dir to always override
    # those pointing to other places in the file system. This is so built
    # binaries prefer our libraries to the ones that may lie somewhere
    # in the file system, such as /lib/x86_64-linux-gnu.
    #
    # The correct thing to do here would be C++'s std::stable_partition.
    # Python standard library does not have it, so replicate it with
    # sort, which is guaranteed to be stable.
    return sorted(rpath_list, key=os.path.isabs)


def evaluate_rpath(p: str, build_dir: str, from_dir: str) -> str:
    if p == from_dir:
        return '' # relpath errors out in this case
    elif os.path.isabs(p):
        return p # These can be outside of build dir.
    else:
        return os.path.relpath(os.path.join(build_dir, p), os.path.join(build_dir, from_dir))


class DynamicLinker(metaclass=abc.ABCMeta):

    """Base class for dynamic linkers."""

    _BUILDTYPE_ARGS = {
        'plain': [],
        'debug': [],
        'debugoptimized': [],
        'release': [],
        'minsize': [],
        'custom': [],
    }  # type: typing.Dict[str, typing.List[str]]

    def __init__(self, exelist: typing.List[str], for_machine: mesonlib.MachineChoice,
                 id_: str, *, version: str = 'unknown version'):
        self.exelist = exelist
        self.for_machine = for_machine
        self.version = version
        self.id = id_

    def __repr__(self) -> str:
        return '<{}: v{} `{}`>'.format(type(self).__name__, self.version, ' '.join(self.exelist))

    def get_id(self) -> str:
        return self.id

    def get_version_string(self) -> str:
        return '({} {})'.format(self.id, self.version)

    def get_exelist(self) -> typing.List[str]:
        return self.exelist.copy()

    def get_accepts_rsp(self) -> bool:
        # TODO: is it really a matter of is_windows or is it for_windows?
        return mesonlib.is_windows()

    def get_always_args(self) -> typing.List[str]:
        return []

    def get_lib_prefix(self) -> str:
        return ''

    # XXX: is use_ldflags a compiler or a linker attribute?

    def get_args_from_envvars(self) -> typing.List[str]:
        flags = os.environ.get('LDFLAGS')
        if not flags:
            return []
        return shlex.split(flags)

    def get_option_args(self, options: 'OptionDictType') -> typing.List[str]:
        return []

    def has_multi_arguments(self, args: typing.List[str], env: 'Environment') -> typing.Tuple[bool, bool]:
        m = 'Language {} does not support has_multi_link_arguments.'
        raise mesonlib.EnvironmentException(m.format(self.id))

    def get_debugfile_args(self, targetfile: str) -> typing.List[str]:
        """Some compilers (MSVC) write debug into a separate file.

        This method takes the target object path and returns a list of
        commands to append to the linker invocation to control where that
        file is written.
        """
        return []

    def get_std_shared_lib_args(self) -> typing.List[str]:
        return []

    def get_std_shared_module_args(self, options: 'OptionDictType') -> typing.List[str]:
        return self.get_std_shared_lib_args()

    def get_pie_args(self) -> typing.List[str]:
        # TODO: this really needs to take a boolean and return the args to
        # disable pie, otherwise it only acts to enable pie if pie *isn't* the
        # default.
        m = 'Linker {} does not support position-independent executable'
        raise mesonlib.EnvironmentException(m.format(self.id))

    def get_lto_args(self) -> typing.List[str]:
        return []

    def sanitizer_args(self, value: str) -> typing.List[str]:
        return []

    def get_buildtype_args(self, buildtype: str) -> typing.List[str]:
        # We can override these in children by just overriding the
        # _BUILDTYPE_ARGS value.
        return self._BUILDTYPE_ARGS[buildtype]

    def get_asneeded_args(self) -> typing.List[str]:
        return []

    def get_link_whole_for(self, args: typing.List[str]) -> typing.List[str]:
        raise mesonlib.EnvironmentException(
            'Linker {} does not support link_whole'.format(self.id))

    def get_allow_undefined_args(self) -> typing.List[str]:
        raise mesonlib.EnvironmentException(
            'Linker {} does not support allow undefined'.format(self.id))

    def invoked_by_compiler(self) -> bool:
        """True if meson uses the compiler to invoke the linker."""
        return True

    @abc.abstractmethod
    def get_output_args(self, outname: str) -> typing.List[str]:
        pass

    def get_coverage_args(self) -> typing.List[str]:
        m = "Linker {} doesn't implement coverage data generation.".format(self.id)
        raise mesonlib.EnvironmentException(m)

    @abc.abstractmethod
    def get_search_args(self, dirname: str) -> typing.List[str]:
        pass

    def export_dynamic_args(self, env: 'Environment') -> typing.List[str]:
        return []

    def import_library_args(self, implibname: str) -> typing.List[str]:
        """The name of the outputted import library.

        This implementation is used only on Windows by compilers that use GNU ld
        """
        return []

    def thread_flags(self, env: 'Environment') -> typing.List[str]:
        return []

    def no_undefined_args(self) -> typing.List[str]:
        """Arguments to error if there are any undefined symbols at link time.

        This is the inverse of get_allow_undefined_args().

        TODO: A future cleanup might merge this and
              get_allow_undefined_args() into a single method taking a
              boolean
        """
        return []

    def fatal_warnings(self) -> typing.List[str]:
        """Arguments to make all warnings errors."""
        return []

    def bitcode_args(self) -> typing.List[str]:
        raise mesonlib.MesonException('This linker does not support bitcode bundles')

    def get_debug_crt_args(self) -> typing.List[str]:
        return []

    def build_rpath_args(self, env: 'Environment', build_dir: str, from_dir: str,
                         rpath_paths: str, build_rpath: str,
                         install_rpath: str) -> typing.List[str]:
        return []


class PosixDynamicLinkerMixin:

    """Mixin class for POSIX-ish linkers.

    This is obviously a pretty small subset of the linker interface, but
    enough dynamic linkers that meson supports are POSIX-like but not
    GNU-like that it makes sense to split this out.
    """

    def get_output_args(self, outname: str) -> typing.List[str]:
        return ['-o', outname]

    def get_std_shared_lib_args(self) -> typing.List[str]:
        return ['-shared']

    def get_search_args(self, dirname: str) -> typing.List[str]:
        return ['-L', dirname]


class GnuLikeDynamicLinkerMixin:

    """Mixin class for dynamic linkers that provides gnu-like interface.

    This acts as a base for the GNU linkers (bfd and gold), the Intel Xild
    (which comes with ICC), LLVM's lld, and other linkers like GNU-ld.
    """

    _BUILDTYPE_ARGS = {
        'plain': [],
        'debug': [],
        'debugoptimized': [],
        'release': ['-Wl,-O1'],
        'minsize': [],
        'custom': [],
    }  # type: typing.Dict[str, typing.List[str]]

    def get_pie_args(self) -> typing.List[str]:
        return ['-pie']

    def get_asneeded_args(self) -> typing.List[str]:
        return ['-Wl,--as-needed']
    
    def get_link_whole_for(self, args: typing.List[str]) -> typing.List[str]:
        if not args:
            return args
        return ['-Wl,--whole-archive'] + args + ['-Wl,--no-whole-archive']

    def get_allow_undefined_args(self) -> typing.List[str]:
        return ['-Wl,--allow-shlib-undefined']

    def get_lto_args(self) -> typing.List[str]:
        return ['-flto']

    def sanitizer_args(self, value: str) -> typing.List[str]:
        if value == 'none':
            return []
        return ['-fsanitize=' + value]

    def invoked_by_compiler(self) -> bool:
        """True if meson uses the compiler to invoke the linker."""
        return True

    def get_coverage_args(self) -> typing.List[str]:
        return ['--coverage']

    def export_dynamic_args(self, env: 'Environment') -> typing.List[str]:
        m = env.machines[self.for_machine]
        if m.is_windows() or m.is_cygwin():
            return ['-Wl,--export-all-symbols']
        return ['-Wl,-export-dynamic']

    def import_library_args(self, implibname: str) -> typing.List[str]:
        return ['-Wl,--out-implib=' + implibname]

    def thread_flags(self, env: 'Environment') -> typing.List[str]:
        if env.machines[self.for_machine].is_haiku():
            return []
        return ['-pthread']

    def no_undefined_args(self) -> typing.List[str]:
        return ['-Wl,--no-undefined']

    def fatal_warnings(self) -> typing.List[str]:
        return ['-Wl,--fatal-warnings']

    def get_soname_args(self, env: 'Environment', prefix: str, shlib_name: str,
                        suffix: str, soversion: str, darwin_versions: typing.Tuple[str, str],
                        is_shared_module: bool) -> typing.List[str]:
        m = env.machines[self.for_machine]
        if m.is_windows() or m.is_cygwin():
            # For PE/COFF the soname argument has no effect
            return []
        sostr = '' if soversion is None else '.' + soversion
        return ['-Wl,-soname,{}{}.{}{}'.format(prefix, shlib_name, suffix, sostr)]

    def build_rpath_args(self, env: 'Environment', build_dir: str, from_dir: str,
                         rpath_paths: str, build_rpath: str,
                         install_rpath: str) -> typing.List[str]:
        m = env.machines[self.for_machine]
        if m.is_windows() or m.is_cygwin():
            return []
        if not rpath_paths and not install_rpath and not build_rpath:
            return []
        args = []
        origin_placeholder = '$ORIGIN'
        processed_rpaths = prepare_rpaths(rpath_paths, build_dir, from_dir)
        # Need to deduplicate rpaths, as macOS's install_name_tool
        # is *very* allergic to duplicate -delete_rpath arguments
        # when calling depfixer on installation.
        all_paths = mesonlib.OrderedSet([os.path.join(origin_placeholder, p) for p in processed_rpaths])
        # Build_rpath is used as-is (it is usually absolute).
        if build_rpath != '':
            all_paths.add(build_rpath)

        # TODO: should this actually be "for (dragonfly|open)bsd"?
        if mesonlib.is_dragonflybsd() or mesonlib.is_openbsd():
            # This argument instructs the compiler to record the value of
            # ORIGIN in the .dynamic section of the elf. On Linux this is done
            # by default, but is not on dragonfly/openbsd for some reason. Without this
            # $ORIGIN in the runtime path will be undefined and any binaries
            # linked against local libraries will fail to resolve them.
            args.append('-Wl,-z,origin')

        # In order to avoid relinking for RPATH removal, the binary needs to contain just
        # enough space in the ELF header to hold the final installation RPATH.
        paths = ':'.join(all_paths)
        if len(paths) < len(install_rpath):
            padding = 'X' * (len(install_rpath) - len(paths))
            if not paths:
                paths = padding
            else:
                paths = paths + ':' + padding
        args.append('-Wl,-rpath,' + paths)

        # TODO: should this actually be "for solaris/sunos"?
        if mesonlib.is_sunos():
            return args

        # Rpaths to use while linking must be absolute. These are not
        # written to the binary. Needed only with GNU ld:
        # https://sourceware.org/bugzilla/show_bug.cgi?id=16936
        # Not needed on Windows or other platforms that don't use RPATH
        # https://github.com/mesonbuild/meson/issues/1897
        #
        # In addition, this linker option tends to be quite long and some
        # compilers have trouble dealing with it. That's why we will include
        # one option per folder, like this:
        #
        #   -Wl,-rpath-link,/path/to/folder1 -Wl,-rpath,/path/to/folder2 ...
        #
        # ...instead of just one single looooong option, like this:
        #
        #   -Wl,-rpath-link,/path/to/folder1:/path/to/folder2:...
        args.extend(['-Wl,-rpath-link,' + os.path.join(build_dir, p) for p in rpath_paths])

        return args


class AppleDynamicLinker(PosixDynamicLinkerMixin, DynamicLinker):

    """Apple's ld implementation."""

    def get_asneeded_args(self) -> typing.List[str]:
        return ['-Wl,-dead_strip_dylibs']

    def get_allow_undefined_args(self) -> typing.List[str]:
        return ['-Wl,-undefined,dynamic_lookup']

    def get_std_shared_module_args(self, options: 'OptionDictType') -> typing.List[str]:
        return ['-bundle', '-Wl,-undefined,dynamic_lookup']

    def get_link_whole_for(self, args: typing.List[str]) -> typing.List[str]:
        result = []  # type: typing.List[str]
        for a in args:
            result.extend(['-Wl,-force_load', a])
        return result

    def no_undefined_args(self) -> typing.List[str]:
        return ['-Wl,-undefined,error']

    def get_always_args(self) -> typing.List[str]:
        return ['-Wl,-headerpad_max_install_names']

    def bitcode_args(self) -> typing.List[str]:
        return ['-Wl,-bitcode_bundle']

    def fatal_warnings(self) -> typing.List[str]:
        return ['-Wl,-fatal_warnings']

    def get_soname_args(self, env: 'Environment', prefix: str, shlib_name: str,
                        suffix: str, soversion: str, darwin_versions: typing.Tuple[str, str],
                        is_shared_module: bool) -> typing.List[str]:
        if is_shared_module:
            return []
        install_name = ['@rpath/', prefix, shlib_name]
        if soversion is not None:
            install_name.append('.' + soversion)
        install_name.append('.dylib')
        args = ['-install_name', ''.join(install_name)]
        if darwin_versions:
            args.extend(['-compatibility_version', darwin_versions[0],
                         '-current_version', darwin_versions[1]])
        return args

    def build_rpath_args(self, env: 'Environment', build_dir: str, from_dir: str,
                         rpath_paths: str, build_rpath: str,
                         install_rpath: str) -> typing.List[str]:
        if not rpath_paths and not install_rpath and not build_rpath:
            return []
        # Ensure that there is enough space for install_name_tool in-place
        # editing of large RPATHs
        args = ['-Wl,-headerpad_max_install_names']
        # @loader_path is the equivalent of $ORIGIN on macOS
        # https://stackoverflow.com/q/26280738
        origin_placeholder = '@loader_path'
        processed_rpaths = prepare_rpaths(rpath_paths, build_dir, from_dir)
        all_paths = mesonlib.OrderedSet([os.path.join(origin_placeholder, p) for p in processed_rpaths])
        if build_rpath != '':
            all_paths.add(build_rpath)
        args.extend(['-Wl,-rpath,' + rp for rp in all_paths])

        return args


class GnuDynamicLinker(GnuLikeDynamicLinkerMixin, PosixDynamicLinkerMixin, DynamicLinker):

    """Representation of GNU ld.bfd and ld.gold."""

    pass


class LLVMDynamicLinker(GnuLikeDynamicLinkerMixin, PosixDynamicLinkerMixin, DynamicLinker):

    """Representation of LLVM's lld (not lld-link) linker.

    This is only the posix-like linker.
    """

    pass


class XildLinuxDynamicLinker(GnuLikeDynamicLinkerMixin, PosixDynamicLinkerMixin, DynamicLinker):

    """Representation of Intel's Xild linker.

    This is only the linux-like linker which dispatches to Gnu ld.
    """

    pass


class XildAppleDynamicLinker(AppleDynamicLinker):

    """Representation of Intel's Xild linker.

    This is the apple linker, which dispatches to Apple's ld.
    """

    pass


class CcrxDynamicLinker(DynamicLinker):

    """Linker for Renesis CCrx compiler."""

    def __init__(self, for_machine: mesonlib.MachineChoice,
                 *, version: str = 'unknown version'):
        super().__init__(['rlink.exe'], for_machine, 'rlink',
                         version=version)

    def get_accepts_rsp(self) -> bool:
        return False

    def get_lib_prefix(self) -> str:
        return '-lib='

    def get_std_shared_lib_args(self) -> typing.List[str]:
        return []

    def get_output_args(self, outputname: str) -> typing.List[str]:
        return ['-output=%s' % outputname]

    def get_search_args(self, dirname: str) -> typing.NoReturn:
        raise EnvironmentError('rlink.exe does not have a search dir argument')

    def get_allow_undefined_args(self) -> typing.List[str]:
        return []

    def get_soname_args(self, env: 'Environment', prefix: str, shlib_name: str,
                        suffix: str, soversion: str, darwin_versions: typing.Tuple[str, str],
                        is_shared_module: bool) -> typing.List[str]:
        return []


class ArmDynamicLinker(PosixDynamicLinkerMixin, DynamicLinker):

    """Linker for the ARM compiler."""

    def __init__(self, for_machine: mesonlib.MachineChoice,
                 *, version: str = 'unknown version'):
        super().__init__(['armlink'], for_machine, 'armlink',
                         version=version)

    def get_accepts_rsp(self) -> bool:
        return False

    def get_std_shared_lib_args(self) -> typing.List[str]:
        return []

    def get_allow_undefined_args(self) -> typing.List[str]:
        return []
