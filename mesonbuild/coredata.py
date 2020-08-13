# Copyrighs 2012-2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from . import mlog, mparser
import pickle, os, uuid
import sys
from itertools import chain
from ._pathlib import PurePath
from collections import OrderedDict, defaultdict
from .mesonlib import (
    MesonException, EnvironmentException, MachineChoice, PerMachine,
    default_libdir, default_libexecdir, default_prefix, split_args
)
from .wrap import WrapMode
import ast
import argparse
import configparser
import enum
import shlex
import typing as T

if T.TYPE_CHECKING:
    from . import dependencies
    from .compilers.compilers import Compiler, CompileResult  # noqa: F401
    from .environment import Environment
    from .mesonlib import OptionOverrideProxy

    OptionDictType = T.Union[T.Dict[str, 'UserOption[T.Any]'], OptionOverrideProxy]
    CompilerCheckCacheKey = T.Tuple[T.Tuple[str, ...], str, str, T.Tuple[str, ...], str]
    KeyedOptionDictType = T.Dict[OptionKey, 'UserOption[T.Any]']

version = '0.55.999'
backendlist = ['ninja', 'vs', 'vs2010', 'vs2015', 'vs2017', 'vs2019', 'xcode']

default_yielding = False

# Can't bind this near the class method it seems, sadly.
_T = T.TypeVar('_T')


class ArgumentGroup(enum.Enum):

    """Enum used to specify what kind of argument a thing is."""

    BUILTIN = 0
    BASE = 1
    COMPILER = 2
    USER = 3
    BACKEND = 4


def classify_argument(key: 'OptionKey') -> ArgumentGroup:
    """Classify arguments into groups so we know which dict to assign them to."""

    from .compilers import base_options
    all_builtins = set(BUILTIN_OPTIONS) | set(BUILTIN_OPTIONS_PER_MACHINE) | set(builtin_dir_noprefix_options)

    if key.name in base_options:
        assert key.machine is MachineChoice.HOST
        return ArgumentGroup.BASE
    elif key.language is not None:
        return ArgumentGroup.COMPILER
    elif key.name in all_builtins:
        return ArgumentGroup.BUILTIN
    elif key.name.startswith('backend_'):
        return ArgumentGroup.BACKEND
    else:
        assert key.machine is MachineChoice.HOST
        return ArgumentGroup.USER


class OptionKey:

    """Represents an option key in the various option dictionaries.

    This provides a flexible, powerful way to map option names from their
    external form (things like subproject:build.option) to something that
    internally easier to reason about and produce.
    """

    def __init__(self, name: str, subproject: str = '',
                 machine: MachineChoice = MachineChoice.HOST,
                 language: T.Optional[str] = None):
        self.name = name
        self.subproject = subproject
        self.machine = machine
        self.language = language

    def __hash__(self) -> int:
        return hash((self.name, self.subproject, self.machine, self.language))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, OptionKey):
            return (
                self.name == other.name and
                self.subproject == other.subproject and
                self.machine is other.machine and
                self.language == other.language)
        return NotImplemented

    def __str__(self) -> str:
        out = self.name
        if self.language:
            out = '{}_{}'.format(self.language, out)
        if self.machine is MachineChoice.BUILD:
            out = 'build.{}'.format(out)
        if self.subproject:
            out = '{}:{}'.format(self.subproject, out)
        return out

    def __repr__(self) -> str:
        return 'OptionKey("{}", "{}", {!r}, "{}")'.format(
            self.name, self.subproject, self.machine, self.language
        )

    @classmethod
    def from_string(cls, raw: str) -> 'OptionKey':
        """Parse the raw command line format into a three part tuple.

        This takes strings like `mysubproject:build.myoption` and Creates an
        OptionKey out of them.
        """
        from .compilers import all_languages
        langs = tuple('{}_'.format(c) for c in all_languages)

        try:
            subproject, raw2 = raw.split(':')
        except ValueError:
            subproject, raw2 = '', raw

        if raw2.startswith('build.'):
            opt = raw2.lstrip('build.')
            for_machine = MachineChoice.BUILD
        else:
            opt = raw2
            for_machine = MachineChoice.HOST
        if opt.startswith(langs):
            lang, opt = opt.split('_', 1)
        else:
            lang = None
        assert ':' not in opt
        assert 'build.' not in opt

        return cls(opt, subproject, for_machine, lang)

    def copy(self) -> 'OptionKey':
        """Return a copy of the OptionKey."""
        return OptionKey(self.name, self.subproject, self.machine, self.language)

    def evolve(self, name: T.Optional[str] = None, subproject: T.Optional[str] = None,
               machine: T.Optional[MachineChoice] = None, language: T.Optional[str] = None) -> 'OptionKey':
        """Create a new copy of this key, but with alterted members.

        For example:
        >>> a = OptionKey('foo', '', MachineChoice.Host)
        >>> b = a.copy()
        >>> b.subproject = 'bar'
        >>> b == a.evolve(subproject='bar)
        True
        """
        new = self.copy()
        if name is not None:
            new.name = name
        if subproject is not None:
            new.subproject = subproject
        if machine is not None:
            new.machine = machine
        if language is not None:
            # This is tricky, language is valid as none, but we need to have a way to ignore it...
            new.language = language
        return new

    def as_root(self) -> 'OptionKey':
        """Convenience method for key.evolve(subproject='')."""
        return self.evolve(subproject='')

    def as_build(self) -> 'OptionKey':
        """Convenience method for key.evolve(machine=MachinceChoice.BUILD)."""
        return self.evolve(machine=MachineChoice.BUILD)

    def as_host(self) -> 'OptionKey':
        """Convenience method for key.evolve(machine=MachinceChoice.HOST)."""
        return self.evolve(machine=MachineChoice.HOST)


class MesonVersionMismatchException(MesonException):
    '''Build directory generated with Meson version is incompatible with current version'''
    def __init__(self, old_version: str, current_version: str) -> None:
        super().__init__('Build directory has been generated with Meson version {}, '
                         'which is incompatible with the current version {}.'
                         .format(old_version, current_version))
        self.old_version = old_version
        self.current_version = current_version


class UserOption(T.Generic[_T]):
    def __init__(self, description: str, choices: T.Optional[T.Union[str, T.List[_T]]], yielding: T.Optional[bool]):
        super().__init__()
        self.choices = choices
        self.description = description
        if yielding is None:
            yielding = default_yielding
        if not isinstance(yielding, bool):
            raise MesonException('Value of "yielding" must be a boolean.')
        self.yielding = yielding

    def printable_value(self) -> T.Union[str, int, bool, T.List[T.Union[str, int, bool]]]:
        assert isinstance(self.value, (str, int, bool, list))
        return self.value

    # Check that the input is a valid value and return the
    # "cleaned" or "native" version. For example the Boolean
    # option could take the string "true" and return True.
    def validate_value(self, value: T.Any) -> _T:
        raise RuntimeError('Derived option class did not override validate_value.')

    def set_value(self, newvalue: T.Any) -> None:
        self.value = self.validate_value(newvalue)

class UserStringOption(UserOption[str]):
    def __init__(self, description: str, value: T.Any, yielding: T.Optional[bool] = None):
        super().__init__(description, None, yielding)
        self.set_value(value)

    def validate_value(self, value: T.Any) -> str:
        if not isinstance(value, str):
            raise MesonException('Value "%s" for string option is not a string.' % str(value))
        return value

class UserBooleanOption(UserOption[bool]):
    def __init__(self, description: str, value, yielding: T.Optional[bool] = None) -> None:
        super().__init__(description, [True, False], yielding)
        self.set_value(value)

    def __bool__(self) -> bool:
        return self.value

    def validate_value(self, value: T.Any) -> bool:
        if isinstance(value, bool):
            return value
        if not isinstance(value, str):
            raise MesonException('Value {} cannot be converted to a boolean'.format(value))
        if value.lower() == 'true':
            return True
        if value.lower() == 'false':
            return False
        raise MesonException('Value %s is not boolean (true or false).' % value)

class UserIntegerOption(UserOption[int]):
    def __init__(self, description: str, value: T.Any, yielding: T.Optional[bool] = None):
        min_value, max_value, default_value = value
        self.min_value = min_value
        self.max_value = max_value
        c = []
        if min_value is not None:
            c.append('>=' + str(min_value))
        if max_value is not None:
            c.append('<=' + str(max_value))
        choices = ', '.join(c)
        super().__init__(description, choices, yielding)
        self.set_value(default_value)

    def validate_value(self, value: T.Any) -> int:
        if isinstance(value, str):
            value = self.toint(value)
        if not isinstance(value, int):
            raise MesonException('New value for integer option is not an integer.')
        if self.min_value is not None and value < self.min_value:
            raise MesonException('New value %d is less than minimum value %d.' % (value, self.min_value))
        if self.max_value is not None and value > self.max_value:
            raise MesonException('New value %d is more than maximum value %d.' % (value, self.max_value))
        return value

    def toint(self, valuestring: str) -> int:
        try:
            return int(valuestring)
        except ValueError:
            raise MesonException('Value string "%s" is not convertible to an integer.' % valuestring)

class UserUmaskOption(UserIntegerOption, UserOption[T.Union[str, int]]):
    def __init__(self, description: str, value: T.Any, yielding: T.Optional[bool] = None):
        super().__init__(description, (0, 0o777, value), yielding)
        self.choices = ['preserve', '0000-0777']

    def printable_value(self) -> str:
        if self.value == 'preserve':
            return self.value
        return format(self.value, '04o')

    def validate_value(self, value: T.Any) -> T.Union[str, int]:
        if value is None or value == 'preserve':
            return 'preserve'
        return super().validate_value(value)

    def toint(self, valuestring: T.Union[str, int]) -> int:
        try:
            return int(valuestring, 8)
        except ValueError as e:
            raise MesonException('Invalid mode: {}'.format(e))

class UserComboOption(UserOption[str]):
    def __init__(self, description: str, choices: T.List[str], value: T.Any, yielding: T.Optional[bool] = None):
        super().__init__(description, choices, yielding)
        if not isinstance(self.choices, list):
            raise MesonException('Combo choices must be an array.')
        for i in self.choices:
            if not isinstance(i, str):
                raise MesonException('Combo choice elements must be strings.')
        self.set_value(value)

    def validate_value(self, value: T.Any) -> str:
        if value not in self.choices:
            if isinstance(value, bool):
                _type = 'boolean'
            elif isinstance(value, (int, float)):
                _type = 'number'
            else:
                _type = 'string'
            optionsstring = ', '.join(['"%s"' % (item,) for item in self.choices])
            raise MesonException('Value "{}" (of type "{}") for combo option "{}" is not one of the choices.'
                                 ' Possible choices are (as string): {}.'.format(
                                     value, _type, self.description, optionsstring))
        return value

class UserArrayOption(UserOption[T.List[str]]):
    def __init__(self, description: str, value: T.Union[str, T.List[str]], split_args: bool = False, user_input: bool = False, allow_dups: bool = False, **kwargs: T.Any) -> None:
        super().__init__(description, kwargs.get('choices', []), yielding=kwargs.get('yielding', None))
        self.split_args = split_args
        self.allow_dups = allow_dups
        self.value = self.validate_value(value, user_input=user_input)

    def validate_value(self, value: T.Union[str, T.List[str]], user_input: bool = True) -> T.List[str]:
        # User input is for options defined on the command line (via -D
        # options). Users can put their input in as a comma separated
        # string, but for defining options in meson_options.txt the format
        # should match that of a combo
        if not user_input and isinstance(value, str) and not value.startswith('['):
            raise MesonException('Value does not define an array: ' + value)

        if isinstance(value, str):
            if value.startswith('['):
                try:
                    newvalue = ast.literal_eval(value)
                except ValueError:
                    raise MesonException('malformed option {}'.format(value))
            elif value == '':
                newvalue = []
            else:
                if self.split_args:
                    newvalue = split_args(value)
                else:
                    newvalue = [v.strip() for v in value.split(',')]
        elif isinstance(value, list):
            newvalue = value
        else:
            raise MesonException('"{}" should be a string array, but it is not'.format(newvalue))

        if not self.allow_dups and len(set(newvalue)) != len(newvalue):
            msg = 'Duplicated values in array option is deprecated. ' \
                  'This will become a hard error in the future.'
            mlog.deprecation(msg)
        for i in newvalue:
            if not isinstance(i, str):
                raise MesonException('String array element "{0}" is not a string.'.format(str(newvalue)))
        if self.choices:
            bad = [x for x in newvalue if x not in self.choices]
            if bad:
                raise MesonException('Options "{}" are not in allowed choices: "{}"'.format(
                    ', '.join(bad), ', '.join(self.choices)))
        return newvalue


class UserFeatureOption(UserComboOption):
    static_choices = ['enabled', 'disabled', 'auto']

    def __init__(self, description: str, value: T.Any, yielding: T.Optional[bool] = None):
        super().__init__(description, self.static_choices, value, yielding)

    def is_enabled(self) -> bool:
        return self.value == 'enabled'

    def is_disabled(self) -> bool:
        return self.value == 'disabled'

    def is_auto(self) -> bool:
        return self.value == 'auto'

if T.TYPE_CHECKING:
    CacheKeyType = T.Tuple[T.Tuple[T.Any, ...], ...]
    SubCacheKeyType = T.Tuple[T.Any, ...]


class DependencyCacheType(enum.Enum):

    OTHER = 0
    PKG_CONFIG = 1
    CMAKE = 2

    @classmethod
    def from_type(cls, dep: 'dependencies.Dependency') -> 'DependencyCacheType':
        from . import dependencies
        # As more types gain search overrides they'll need to be added here
        if isinstance(dep, dependencies.PkgConfigDependency):
            return cls.PKG_CONFIG
        if isinstance(dep, dependencies.CMakeDependency):
            return cls.CMAKE
        return cls.OTHER


class DependencySubCache:

    def __init__(self, type_: DependencyCacheType):
        self.types = [type_]
        self.__cache = {}  # type: T.Dict[SubCacheKeyType, dependencies.Dependency]

    def __getitem__(self, key: 'SubCacheKeyType') -> 'dependencies.Dependency':
        return self.__cache[key]

    def __setitem__(self, key: 'SubCacheKeyType', value: 'dependencies.Dependency') -> None:
        self.__cache[key] = value

    def __contains__(self, key: 'SubCacheKeyType') -> bool:
        return key in self.__cache

    def values(self) -> T.Iterable['dependencies.Dependency']:
        return self.__cache.values()


class DependencyCache:

    """Class that stores a cache of dependencies.

    This class is meant to encapsulate the fact that we need multiple keys to
    successfully lookup by providing a simple get/put interface.
    """

    def __init__(self, builtins_per_machine: PerMachine[T.Dict[str, UserOption[T.Any]]], for_machine: MachineChoice):
        self.__cache = OrderedDict()  # type: T.MutableMapping[CacheKeyType, DependencySubCache]
        self.__builtins_per_machine = builtins_per_machine
        self.__for_machine = for_machine

    def __calculate_subkey(self, type_: DependencyCacheType) -> T.Tuple[T.Any, ...]:
        if type_ is DependencyCacheType.PKG_CONFIG:
            return tuple(self.__builtins_per_machine[self.__for_machine]['pkg_config_path'].value)
        elif type_ is DependencyCacheType.CMAKE:
            return tuple(self.__builtins_per_machine[self.__for_machine]['cmake_prefix_path'].value)
        assert type_ is DependencyCacheType.OTHER, 'Someone forgot to update subkey calculations for a new type'
        return tuple()

    def __iter__(self) -> T.Iterator['CacheKeyType']:
        return self.keys()

    def put(self, key: 'CacheKeyType', dep: 'dependencies.Dependency') -> None:
        t = DependencyCacheType.from_type(dep)
        if key not in self.__cache:
            self.__cache[key] = DependencySubCache(t)
        subkey = self.__calculate_subkey(t)
        self.__cache[key][subkey] = dep

    def get(self, key: 'CacheKeyType') -> T.Optional['dependencies.Dependency']:
        """Get a value from the cache.

        If there is no cache entry then None will be returned.
        """
        try:
            val = self.__cache[key]
        except KeyError:
            return None

        for t in val.types:
            subkey = self.__calculate_subkey(t)
            try:
                return val[subkey]
            except KeyError:
                pass
        return None

    def values(self) -> T.Iterator['dependencies.Dependency']:
        for c in self.__cache.values():
            yield from c.values()

    def keys(self) -> T.Iterator['CacheKeyType']:
        return iter(self.__cache.keys())

    def items(self) -> T.Iterator[T.Tuple['CacheKeyType', T.List['dependencies.Dependency']]]:
        for k, v in self.__cache.items():
            vs = []
            for t in v.types:
                subkey = self.__calculate_subkey(t)
                if subkey in v:
                    vs.append(v[subkey])
            yield k, vs

    def clear(self) -> None:
        self.__cache.clear()

# Can't bind this near the class method it seems, sadly.
_V = T.TypeVar('_V')

# This class contains all data that must persist over multiple
# invocations of Meson. It is roughly the same thing as
# cmakecache.

class CoreData:

    def __init__(self, options: argparse.Namespace, scratch_dir: str, meson_command: T.List[str]):
        self.lang_guids = {
            'default': '8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942',
            'c': '8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942',
            'cpp': '8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942',
            'test': '3AC096D0-A1C2-E12C-1390-A8335801FDAB',
            'directory': '2150E333-8FDC-42A3-9474-1A3956D46DE8',
        }
        self.test_guid = str(uuid.uuid4()).upper()
        self.regen_guid = str(uuid.uuid4()).upper()
        self.install_guid = str(uuid.uuid4()).upper()
        self.meson_command = meson_command
        self.target_guids = {}
        self.version = version
        self.builtins = {} # type: OptionDictType
        self.builtins_per_machine = PerMachine({}, {})
        self.backend_options = {} # type: OptionDictType
        self.user_options = {} # type: OptionDictType
        self.compiler_options = PerMachine(
            defaultdict(dict),
            defaultdict(dict),
        ) # type: PerMachine[T.defaultdict[str, OptionDictType]]
        self.base_options = {} # type: OptionDictType
        self.cross_files = self.__load_config_files(options, scratch_dir, 'cross')
        self.compilers = PerMachine(OrderedDict(), OrderedDict())  # type: PerMachine[T.Dict[str, Compiler]]

        build_cache = DependencyCache(self.builtins_per_machine, MachineChoice.BUILD)
        host_cache = DependencyCache(self.builtins_per_machine, MachineChoice.BUILD)
        self.deps = PerMachine(build_cache, host_cache)  # type: PerMachine[DependencyCache]
        self.compiler_check_cache = OrderedDict()  # type: T.Dict[CompilerCheckCacheKey, compiler.CompileResult]

        # Only to print a warning if it changes between Meson invocations.
        self.config_files = self.__load_config_files(options, scratch_dir, 'native')
        self.builtin_options_libdir_cross_fixup()
        self.init_builtins('')

    @staticmethod
    def __load_config_files(options: argparse.Namespace, scratch_dir: str, ftype: str) -> T.List[str]:
        # Need to try and make the passed filenames absolute because when the
        # files are parsed later we'll have chdir()d.
        if ftype == 'cross':
            filenames = options.cross_file
        else:
            filenames = options.native_file

        if not filenames:
            return []

        found_invalid = []  # type: T.List[str]
        missing = []        # type: T.List[str]
        real = []           # type: T.List[str]
        for i, f in enumerate(filenames):
            f = os.path.expanduser(os.path.expandvars(f))
            if os.path.exists(f):
                if os.path.isfile(f):
                    real.append(os.path.abspath(f))
                    continue
                elif os.path.isdir(f):
                    found_invalid.append(os.path.abspath(f))
                else:
                    # in this case we've been passed some kind of pipe, copy
                    # the contents of that file into the meson private (scratch)
                    # directory so that it can be re-read when wiping/reconfiguring
                    copy = os.path.join(scratch_dir, '{}.{}.ini'.format(uuid.uuid4(), ftype))
                    with open(f, 'r') as rf:
                        with open(copy, 'w') as wf:
                            wf.write(rf.read())
                    real.append(copy)

                    # Also replace the command line argument, as the pipe
                    # probably won't exist on reconfigure
                    filenames[i] = copy
                    continue
            if sys.platform != 'win32':
                paths = [
                    os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
                ] + os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':')
                for path in paths:
                    path_to_try = os.path.join(path, 'meson', ftype, f)
                    if os.path.isfile(path_to_try):
                        real.append(path_to_try)
                        break
                else:
                    missing.append(f)
            else:
                missing.append(f)

        if missing:
            if found_invalid:
                mlog.log('Found invalid candidates for', ftype, 'file:', *found_invalid)
            mlog.log('Could not find any valid candidate for', ftype, 'files:', *missing)
            raise MesonException('Cannot find specified {} file: {}'.format(ftype, f))
        return real

    def builtin_options_libdir_cross_fixup(self):
        # By default set libdir to "lib" when cross compiling since
        # getting the "system default" is always wrong on multiarch
        # platforms as it gets a value like lib/x86_64-linux-gnu.
        if self.cross_files:
            BUILTIN_OPTIONS['libdir'].default = 'lib'

    def sanitize_prefix(self, prefix):
        prefix = os.path.expanduser(prefix)
        if not os.path.isabs(prefix):
            raise MesonException('prefix value {!r} must be an absolute path'
                                 ''.format(prefix))
        if prefix.endswith('/') or prefix.endswith('\\'):
            # On Windows we need to preserve the trailing slash if the
            # string is of type 'C:\' because 'C:' is not an absolute path.
            if len(prefix) == 3 and prefix[1] == ':':
                pass
            # If prefix is a single character, preserve it since it is
            # the root directory.
            elif len(prefix) == 1:
                pass
            else:
                prefix = prefix[:-1]
        return prefix

    def sanitize_dir_option_value(self, prefix: str, option: str, value: T.Any) -> T.Any:
        '''
        If the option is an installation directory option and the value is an
        absolute path, check that it resides within prefix and return the value
        as a path relative to the prefix.

        This way everyone can do f.ex, get_option('libdir') and be sure to get
        the library directory relative to prefix.

        .as_posix() keeps the posix-like file seperators Meson uses.
        '''
        try:
            value = PurePath(value)
        except TypeError:
            return value
        if option.endswith('dir') and value.is_absolute() and \
           option not in builtin_dir_noprefix_options:
            # Value must be a subdir of the prefix
            # commonpath will always return a path in the native format, so we
            # must use pathlib.PurePath to do the same conversion before
            # comparing.
            msg = ('The value of the {!r} option is \'{!s}\' which must be a '
                   'subdir of the prefix {!r}.\nNote that if you pass a '
                   'relative path, it is assumed to be a subdir of prefix.')
            # os.path.commonpath doesn't understand case-insensitive filesystems,
            # but PurePath().relative_to() does.
            try:
                value = value.relative_to(prefix)
            except ValueError:
                raise MesonException(msg.format(option, value, prefix))
            if '..' in str(value):
                raise MesonException(msg.format(option, value, prefix))
        return value.as_posix()

    def init_builtins(self, subproject: str):
        # Create builtin options with default values
        for key, opt in BUILTIN_OPTIONS.items():
            self.add_builtin_option(self.builtins, key, opt, subproject)
        for for_machine in iter(MachineChoice):
            for key, opt in BUILTIN_OPTIONS_PER_MACHINE.items():
                self.add_builtin_option(self.builtins_per_machine[for_machine], key, opt, subproject)

    def add_builtin_option(self, opts_map, key, opt, subproject):
        if subproject:
            if opt.yielding:
                # This option is global and not per-subproject
                return
            optname = subproject + ':' + key
            value = opts_map[key].value
        else:
            optname = key
            value = None
        opts_map[optname] = opt.init_option(key, value, default_prefix())

    def init_backend_options(self, backend_name: str) -> None:
        if backend_name == 'ninja':
            self.backend_options['backend_max_links'] = \
                UserIntegerOption(
                    'Maximum number of linker processes to run or 0 for no '
                    'limit',
                    (0, None, 0))
        elif backend_name.startswith('vs'):
            self.backend_options['backend_startup_project'] = \
                UserStringOption(
                    'Default project to execute in Visual Studio',
                    '')

    def get_builtin_option(self, key: T.Union[OptionKey, str]) -> T.Union[str, int, bool, T.List[str], WrapMode]:
        if isinstance(key, str):
            key = OptionKey.from_string(key)
        v = self.get_builtin_option_raw(key)
        if key.name == 'wrap_mode':
            return WrapMode.from_string(v.value)
        return v.value

    def get_builtin_option_raw(self, opt: OptionKey) -> T.Optional[UserOption]:
        """Get the UserOption associated with an optoin tuple."""
        assert opt.language is None
        if opt.name in BUILTIN_OPTIONS_PER_MACHINE:
            source = self.builtins_per_machine[opt.machine]
            # The option needs to be looked up without the build. prefix,
            opt = opt.as_host()
        else:
            assert opt.machine is MachineChoice.HOST
            source = self.builtins

        try:
            v = source[str(opt)]
        except KeyError:
            v = None

        if v is None or v.yielding:
            try:
                v = source[str(opt.as_root())]
            except KeyError:
                raise MesonException('Tried to get unknown builtin option %s.' % repr(opt))

        return v

    def get_any_option(self, key: OptionKey) -> UserOption[_T]:
        """Return an option object given a name, no matter where it's stored."""
        classifier = classify_argument(key)
        if classifier is ArgumentGroup.BASE:
            return self.base_options[key.name]
        elif classifier is ArgumentGroup.USER:
            return self.user_options[str(key)]
        elif classifier is ArgumentGroup.BUILTIN:
            return self.get_builtin_option_raw(key)
        elif classifier is ArgumentGroup.BACKEND:
            return self.backend_options[key.name]
        elif classifier is ArgumentGroup.COMPILER:
            return self.compiler_options[key.machine][key.language][key.name]
        raise MesonException('Unknown enum value {}'.format(classifier))

    def set_any_option(self, key: OptionKey, value: T.Union[str, int, bool, T.List[str]]) -> UserOption[_T]:
        """Return an option object given a name, no matter where it's stored."""
        classifier = classify_argument(key)
        if classifier is ArgumentGroup.BUILTIN:
            self.set_builtin_option(key, value)
        else:
            self.get_any_option(key).set_value(value)

    def set_builtin_option(self, key: OptionKey, value: T.Union[str, int, bool, T.List[str]]) -> None:
        self.get_builtin_option_raw(key).set_value(value)
        if key.name == 'buildtype':
            self.set_others_from_buildtype(value)
        elif key.name in {'debug', 'optimization'}:
            self.set_buildtype_from_others()

    def set_others_from_buildtype(self, value: str) -> None:
        if value == 'plain':
            opt = '0'
            debug = False
        elif value == 'debug':
            opt = '0'
            debug = True
        elif value == 'debugoptimized':
            opt = '2'
            debug = True
        elif value == 'release':
            opt = '3'
            debug = False
        elif value == 'minsize':
            opt = 's'
            debug = True
        else:
            assert(value == 'custom')
            return
        # Do *not* use set_builtin_option here to avoid infinite recursion
        self.get_builtin_option_raw(OptionKey('optimization')).set_value(opt)
        self.get_builtin_option_raw(OptionKey('debug')).set_value(debug)

    def set_buildtype_from_others(self) -> None:
        opt = self.get_builtin_option('optimization')
        debug = self.get_builtin_option('debug')
        if opt == '0' and not debug:
            mode = 'plain'
        elif opt == '0' and debug:
            mode = 'debug'
        elif opt == '2' and debug:
            mode = 'debugoptimized'
        elif opt == '3' and not debug:
            mode = 'release'
        elif opt == 's' and debug:
            mode = 'minsize'
        else:
            mode = 'custom'
        # Do *not* use set_builtin_option here to avoid inifinite recursion
        self.get_builtin_option_raw(OptionKey('buildtype')).set_value(mode)

    @classmethod
    def flatten_lang_iterator(
        cls,
        outer # : T.Iterable[T.Tuple[str, T.Dict[str, _V]]]
    ) -> T.Iterable[T.Tuple[str, _V]]:
        return cls._flatten_pair_iterator((lang + '_', opts) for lang, opts in outer)

    @staticmethod
    def _flatten_pair_iterator(
        outer # : T.Iterable[T.Tuple[str, T.Dict[str, _V]]]
    ) -> T.Iterable[T.Tuple[str, _V]]:
        for k0, v0 in outer:
            for k1, v1 in v0.items():
                yield (k0 + k1, v1)

    def validate_option_value(self, option_name: str, override_value):
        try:
            opt = self.get_any_option(OptionKey.from_string(option_name))
        except KeyError:
            raise MesonException('Tried to validate unknown option %s.' % option_name)
        try:
            return opt.validate_value(override_value)
        except MesonException as e:
            raise MesonException('Validation failed for option %s: ' % option_name) from e

    def get_external_args(self, for_machine: MachineChoice, lang):
        return self.compiler_options[for_machine][lang]['args'].value

    def get_external_link_args(self, for_machine: MachineChoice, lang):
        return self.compiler_options[for_machine][lang]['link_args'].value

    def merge_user_options(self, options: T.Dict[str, T.Union[str, bool, int]]) -> None:
        for (name, value) in options.items():
            if name not in self.user_options:
                self.user_options[name] = value
            else:
                oldval = self.user_options[name]
                if type(oldval) != type(value):
                    self.user_options[name] = value

    def is_cross_build(self, when_building_for: MachineChoice = MachineChoice.HOST) -> bool:
        if when_building_for == MachineChoice.BUILD:
            return False
        return len(self.cross_files) > 0

    def strip_build_option_names(self, options: 'KeyedOptionDictType') -> 'KeyedOptionDictType':
        res = OrderedDict()
        for k, v in options.items():
            if k.machine is MachineChoice.BUILD:
                k = k.as_host()
            res[k] = v
        return res

    def copy_build_options_from_regular_ones(self):
        assert not self.is_cross_build()
        for k, o in self.builtins_per_machine.host.items():
            self.builtins_per_machine.build[k].set_value(o.value)
        for lang, host_opts in self.compiler_options.host.items():
            build_opts = self.compiler_options.build[lang]
            for k, o in host_opts.items():
                if k in build_opts:
                    build_opts[k].set_value(o.value)

    def set_options(self, options: T.Dict[OptionKey, T.Any], subproject: str = '', warn_unknown: bool = True) -> None:
        if not self.is_cross_build():
            options = self.strip_build_option_names(options)
        # Set prefix first because it's needed to sanitize other options
        # TODO: this should move to set_builtin_option
        p = OptionKey('prefix')
        if p in options:
            prefix = self.sanitize_prefix(options[p])
            self.set_builtin_option(p, prefix)
            for key in builtin_dir_noprefix_options:
                k = OptionKey(key)
                if k not in options:
                    self.set_builtin_option(k, BUILTIN_OPTIONS[key].prefixed_default(key, prefix))
        else:
            prefix = self.builtins['prefix'].value

        unknown_options = []
        for k, v in options.items():
            if k.name == 'prefix':
                continue
            try:
                if k.name in BUILTIN_DIR_OPTIONS or k.name in builtin_dir_noprefix_options:
                    v = self.sanitize_dir_option_value(prefix, k.name, v)
                self.set_any_option(k, v)
            except KeyError:
                unknown_options.append(str(k))
        if unknown_options and warn_unknown:
            unknown_options = ', '.join(sorted(unknown_options))
            sub = 'In subproject {}: '.format(subproject) if subproject else ''
            mlog.warning('{}Unknown options: "{}"'.format(sub, unknown_options))
            mlog.log('The value of new options can be set with:')
            mlog.log(mlog.bold('meson setup <builddir> --reconfigure -Dnew_option=new_value ...'))
        if not self.is_cross_build():
            self.copy_build_options_from_regular_ones()

    def set_default_options(self, default_options: 'T.OrderedDict[OptionKey, str]', subproject: str, env: 'Environment') -> None:
        options = OrderedDict()  # type: T.OrderedDict[OptionKey, str]

        # TODO: validate these
        from .compilers import all_languages, base_options
        # split arguments that can be set now, and those that cannot so they
        # can be set later, when they've been initialized.
        for k, v in default_options.items():
            classifier = classify_argument(k)
            if classifier is ArgumentGroup.COMPILER:
                for k in [k, k.as_build()]:
                    if k not in env.compiler_options:
                        env.compiler_options[k] = v
            elif classifier is ArgumentGroup.BASE:
                if not subproject and k.name not in env.base_options:
                    env.base_options[k.name] = v
            elif classifier is ArgumentGroup.BUILTIN:
                if k.subproject and subproject:
                    mlog.warning('Cannot set supbroject defaults from other subprojects')
                    continue

                # Options for subproject should be be put into the options
                # dict, but they do need to be put into env.builtin_options
                if not k.subproject:
                    options[k] = v

                if subproject:
                    k = k.evolve(subproject=subproject)

                if k not in env.builtin_options:
                    env.builtin_options[k] = v
                if self.is_cross_build():
                    k = k.as_build()
                    if k not in env.builtin_options:
                        env.builtin_options[k] = v
            elif classifier is ArgumentGroup.USER:
                # Options for subproject should be be put into the options
                # dict, but they do need to be put into env.builtin_options
                if not k.subproject:
                    options[k] = v
                else:
                    env.project_options[k] = v
            else:
                options[k] = v

        for k, v in env.builtin_options.items():
            if k.subproject not in {subproject, ''}:
                continue
            if k.machine is MachineChoice.BUILD and k.name not in BUILTIN_OPTIONS_PER_MACHINE:
                continue
            if (subproject and k.name in BUILTIN_OPTIONS and not BUILTIN_OPTIONS[k.name].yielding and
                    k.subproject == '' and k.evolve(subproject=subproject) in env.builtin_options):
                # Don't use the superproject option if there is a subproject version
                continue
            options[k] = v

        breakpoint()

        options.update({k: v for k, v in env.project_options.items() if k.subproject == subproject})

        self.set_options(options, subproject=subproject)

    def add_lang_args(self, lang: str, comp: T.Type['Compiler'],
                      for_machine: MachineChoice, env: 'Environment') -> None:
        """Add global language arguments that are needed before compiler/linker detection."""
        from .compilers import compilers

        for k, o in compilers.get_global_options(
                lang,
                comp,
                for_machine,
                env.is_cross_build(),
                env.properties[for_machine]).items():
            # prefixed compiler options affect just this machine
            key = OptionKey(k, machine=for_machine, language=lang)
            if key in env.compiler_options:
                o.set_value(env.compiler_options[key])
            self.compiler_options[for_machine][lang].setdefault(k, o)

    def process_new_compiler(self, lang: str, comp: 'Compiler', env: 'Environment') -> None:
        from . import compilers

        self.compilers[comp.for_machine][lang] = comp

        for k, o in comp.get_options().items():
            key = OptionKey(k, machine=comp.for_machine, language=lang)
            if key in env.compiler_options:
                o.set_value(env.compiler_options[key])
            self.compiler_options[comp.for_machine][lang].setdefault(k, o)

        enabled_opts = []
        for optname in comp.base_options:
            if optname in self.base_options:
                continue
            oobj = compilers.base_options[optname]
            if optname in env.base_options:
                oobj.set_value(env.base_options[optname])
                enabled_opts.append(optname)
            self.base_options[optname] = oobj
        self.emit_base_options_warnings(enabled_opts)

    def emit_base_options_warnings(self, enabled_opts: list):
        if 'b_bitcode' in enabled_opts:
            mlog.warning('Base option \'b_bitcode\' is enabled, which is incompatible with many linker options. Incompatible options such as \'b_asneeded\' have been disabled.', fatal=False)
            mlog.warning('Please see https://mesonbuild.com/Builtin-options.html#Notes_about_Apple_Bitcode_support for more details.', fatal=False)

class CmdLineFileParser(configparser.ConfigParser):
    def __init__(self) -> None:
        # We don't want ':' as key delimiter, otherwise it would break when
        # storing subproject options like "subproject:option=value"
        super().__init__(delimiters=['='], interpolation=None)

    def optionxform(self, option: str) -> str:
        # Don't call str.lower() on keys
        return option

class MachineFileParser():
    def __init__(self, filenames: T.List[str]) -> None:
        self.parser = CmdLineFileParser()
        self.constants = {'True': True, 'False': False}
        self.sections = {}

        self.parser.read(filenames)

        # Parse [constants] first so they can be used in other sections
        if self.parser.has_section('constants'):
            self.constants.update(self._parse_section('constants'))

        for s in self.parser.sections():
            if s == 'constants':
                continue
            self.sections[s] = self._parse_section(s)

    def _parse_section(self, s):
        self.scope = self.constants.copy()
        section = {}
        for entry, value in self.parser.items(s):
            if ' ' in entry or '\t' in entry or "'" in entry or '"' in entry:
                raise EnvironmentException('Malformed variable name {!r} in machine file.'.format(entry))
            # Windows paths...
            value = value.replace('\\', '\\\\')
            try:
                ast = mparser.Parser(value, 'machinefile').parse()
                res = self._evaluate_statement(ast.lines[0])
            except MesonException:
                raise EnvironmentException('Malformed value in machine file variable {!r}.'.format(entry))
            except KeyError as e:
                raise EnvironmentException('Undefined constant {!r} in machine file variable {!r}.'.format(e.args[0], entry))
            section[entry] = res
            self.scope[entry] = res
        return section

    def _evaluate_statement(self, node):
        if isinstance(node, (mparser.StringNode)):
            return node.value
        elif isinstance(node, mparser.BooleanNode):
            return node.value
        elif isinstance(node, mparser.NumberNode):
            return node.value
        elif isinstance(node, mparser.ArrayNode):
            return [self._evaluate_statement(arg) for arg in node.args.arguments]
        elif isinstance(node, mparser.IdNode):
            return self.scope[node.value]
        elif isinstance(node, mparser.ArithmeticNode):
            l = self._evaluate_statement(node.left)
            r = self._evaluate_statement(node.right)
            if node.operation == 'add':
                if (isinstance(l, str) and isinstance(r, str)) or \
                   (isinstance(l, list) and isinstance(r, list)):
                    return l + r
            elif node.operation == 'div':
                if isinstance(l, str) and isinstance(r, str):
                    return os.path.join(l, r)
        raise EnvironmentException('Unsupported node type')

def parse_machine_files(filenames):
    parser = MachineFileParser(filenames)
    return parser.sections

def get_cmd_line_file(build_dir: str) -> str:
    return os.path.join(build_dir, 'meson-private', 'cmd_line.txt')

def read_cmd_line_file(build_dir: str, options: argparse.Namespace) -> None:
    filename = get_cmd_line_file(build_dir)
    if not os.path.isfile(filename):
        return

    config = CmdLineFileParser()
    config.read(filename)

    # Do a copy because config is not really a dict. options.cmd_line_options
    # overrides values from the file.
    d = {OptionKey.from_string(k): v for k, v in config['options'].items()}
    d.update(options.cmd_line_options)
    options.cmd_line_options = d

    properties = config['properties']
    if not options.cross_file:
        options.cross_file = ast.literal_eval(properties.get('cross_file', '[]'))
    if not options.native_file:
        # This will be a string in the form: "['first', 'second', ...]", use
        # literal_eval to get it into the list of strings.
        options.native_file = ast.literal_eval(properties.get('native_file', '[]'))

def cmd_line_options_to_string(options: argparse.Namespace) -> T.Dict[str, str]:
    return {str(k): str(v) for k, v in options.cmd_line_options.items()}

def write_cmd_line_file(build_dir: str, options: argparse.Namespace) -> None:
    filename = get_cmd_line_file(build_dir)
    config = CmdLineFileParser()

    properties = OrderedDict()
    if options.cross_file:
        properties['cross_file'] = options.cross_file
    if options.native_file:
        properties['native_file'] = options.native_file

    config['options'] = cmd_line_options_to_string(options)
    config['properties'] = properties
    with open(filename, 'w') as f:
        config.write(f)

def update_cmd_line_file(build_dir: str, options: argparse.Namespace):
    filename = get_cmd_line_file(build_dir)
    config = CmdLineFileParser()
    config.read(filename)
    config['options'].update(cmd_line_options_to_string(options))
    with open(filename, 'w') as f:
        config.write(f)

def get_cmd_line_options(build_dir: str, options: argparse.Namespace) -> str:
    copy = argparse.Namespace(**vars(options))
    read_cmd_line_file(build_dir, copy)
    cmdline = ['-D{}={}'.format(k, v) for k, v in copy.cmd_line_options.items()]
    if options.cross_file:
        cmdline += ['--cross-file {}'.format(f) for f in options.cross_file]
    if options.native_file:
        cmdline += ['--native-file {}'.format(f) for f in options.native_file]
    return ' '.join([shlex.quote(x) for x in cmdline])

def major_versions_differ(v1: str, v2: str) -> bool:
    return v1.split('.')[0:2] != v2.split('.')[0:2]

def load(build_dir: str) -> CoreData:
    filename = os.path.join(build_dir, 'meson-private', 'coredata.dat')
    load_fail_msg = 'Coredata file {!r} is corrupted. Try with a fresh build tree.'.format(filename)
    try:
        with open(filename, 'rb') as f:
            obj = pickle.load(f)
    except (pickle.UnpicklingError, EOFError):
        raise MesonException(load_fail_msg)
    except AttributeError:
        raise MesonException(
            "Coredata file {!r} references functions or classes that don't "
            "exist. This probably means that it was generated with an old "
            "version of meson.".format(filename))
    if not isinstance(obj, CoreData):
        raise MesonException(load_fail_msg)
    if major_versions_differ(obj.version, version):
        raise MesonVersionMismatchException(obj.version, version)
    return obj

def save(obj: CoreData, build_dir: str) -> str:
    filename = os.path.join(build_dir, 'meson-private', 'coredata.dat')
    prev_filename = filename + '.prev'
    tempfilename = filename + '~'
    if major_versions_differ(obj.version, version):
        raise MesonException('Fatal version mismatch corruption.')
    if os.path.exists(filename):
        import shutil
        shutil.copyfile(filename, prev_filename)
    with open(tempfilename, 'wb') as f:
        pickle.dump(obj, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tempfilename, filename)
    return filename


def register_builtin_arguments(parser: argparse.ArgumentParser) -> None:
    for n, b in BUILTIN_OPTIONS.items():
        b.add_to_argparse(n, parser, '', '')
    for n, b in BUILTIN_OPTIONS_PER_MACHINE.items():
        b.add_to_argparse(n, parser, '', ' (just for host machine)')
        b.add_to_argparse(n, parser, 'build.', ' (just for build machine)')
    parser.add_argument('-D', action='append', dest='projectoptions', default=[], metavar="option",
                        help='Set the value of an option, can be used several times to set multiple options.')

def create_options_dict(options: T.List[str]) -> 'KeyedOptionDictType':
    result = OrderedDict()
    for o in options:
        try:
            (key, value) = o.split('=', 1)
        except ValueError:
            raise MesonException('Option {!r} must have a value separated by equals sign.'.format(o))
        result[OptionKey.from_string(key)] = value
    return result

def parse_cmd_line_options(args: argparse.Namespace) -> None:
    args.cmd_line_options = create_options_dict(args.projectoptions)

    # Merge builtin options set with --option into the dict.
    for name in chain(
            (OptionKey(k) for k in BUILTIN_OPTIONS.keys()),
            (OptionKey(k, machine=MachineChoice.BUILD) for k in BUILTIN_OPTIONS_PER_MACHINE.keys()),
            (OptionKey(k) for k in BUILTIN_OPTIONS_PER_MACHINE.keys()),
    ):
        value = getattr(args, str(name), None)
        if value is not None:
            if name in args.cmd_line_options:
                cmdline_name = BuiltinOption.argparse_name_to_arg(name.name)
                raise MesonException(
                    'Got argument {0} as both -D{0} and {1}. Pick one.'.format(name, cmdline_name))
            args.cmd_line_options[name] = value
            delattr(args, str(name))


_U = T.TypeVar('_U', bound=UserOption[_T])

class BuiltinOption(T.Generic[_T, _U]):

    """Class for a builtin option type.

    There are some cases that are not fully supported yet.
    """

    def __init__(self, opt_type: T.Type[_U], description: str, default: T.Any, yielding: bool = True, *,
                 choices: T.Any = None):
        self.opt_type = opt_type
        self.description = description
        self.default = default
        self.choices = choices
        self.yielding = yielding

    def init_option(self, name: str, value: T.Optional[T.Any], prefix: str) -> _U:
        """Create an instance of opt_type and return it."""
        if value is None:
            value = self.prefixed_default(name, prefix)
        keywords = {'yielding': self.yielding, 'value': value}
        if self.choices:
            keywords['choices'] = self.choices
        return self.opt_type(self.description, **keywords)

    def _argparse_action(self) -> T.Optional[str]:
        # If the type is a boolean, the presence of the argument in --foo form
        # is to enable it. Disabling happens by using -Dfoo=false, which is
        # parsed under `args.projectoptions` and does not hit this codepath.
        if isinstance(self.default, bool):
            return 'store_true'
        return None

    def _argparse_choices(self) -> T.Any:
        if self.opt_type is UserBooleanOption:
            return [True, False]
        elif self.opt_type is UserFeatureOption:
            return UserFeatureOption.static_choices
        return self.choices

    @staticmethod
    def argparse_name_to_arg(name: str) -> str:
        if name == 'warning_level':
            return '--warnlevel'
        else:
            return '--' + name.replace('_', '-')

    def prefixed_default(self, name: str, prefix: str = '') -> T.Any:
        if self.opt_type in [UserComboOption, UserIntegerOption]:
            return self.default
        try:
            return builtin_dir_noprefix_options[name][prefix]
        except KeyError:
            pass
        return self.default

    def add_to_argparse(self, name: str, parser: argparse.ArgumentParser, prefix: str, help_suffix: str) -> None:
        kwargs = OrderedDict()

        c = self._argparse_choices()
        b = self._argparse_action()
        h = self.description
        if not b:
            h = '{} (default: {}).'.format(h.rstrip('.'), self.prefixed_default(name))
        else:
            kwargs['action'] = b
        if c and not b:
            kwargs['choices'] = c
        kwargs['default'] = argparse.SUPPRESS
        kwargs['dest'] = prefix + name

        cmdline_name = self.argparse_name_to_arg(prefix + name)
        parser.add_argument(cmdline_name, help=h + help_suffix, **kwargs)


# Update `docs/markdown/Builtin-options.md` after changing the options below
BUILTIN_DIR_OPTIONS = OrderedDict([
    ('prefix',          BuiltinOption(UserStringOption, 'Installation prefix', default_prefix())),
    ('bindir',          BuiltinOption(UserStringOption, 'Executable directory', 'bin')),
    ('datadir',         BuiltinOption(UserStringOption, 'Data file directory', 'share')),
    ('includedir',      BuiltinOption(UserStringOption, 'Header file directory', 'include')),
    ('infodir',         BuiltinOption(UserStringOption, 'Info page directory', 'share/info')),
    ('libdir',          BuiltinOption(UserStringOption, 'Library directory', default_libdir())),
    ('libexecdir',      BuiltinOption(UserStringOption, 'Library executable directory', default_libexecdir())),
    ('localedir',       BuiltinOption(UserStringOption, 'Locale data directory', 'share/locale')),
    ('localstatedir',   BuiltinOption(UserStringOption, 'Localstate data directory', 'var')),
    ('mandir',          BuiltinOption(UserStringOption, 'Manual page directory', 'share/man')),
    ('sbindir',         BuiltinOption(UserStringOption, 'System executable directory', 'sbin')),
    ('sharedstatedir',  BuiltinOption(UserStringOption, 'Architecture-independent data directory', 'com')),
    ('sysconfdir',      BuiltinOption(UserStringOption, 'Sysconf data directory', 'etc')),
])  # type: OptionDictType

BUILTIN_CORE_OPTIONS = OrderedDict([
    ('auto_features',   BuiltinOption(UserFeatureOption, "Override value of all 'auto' features", 'auto')),
    ('backend',         BuiltinOption(UserComboOption, 'Backend to use', 'ninja', choices=backendlist)),
    ('buildtype',       BuiltinOption(UserComboOption, 'Build type to use', 'debug',
                                      choices=['plain', 'debug', 'debugoptimized', 'release', 'minsize', 'custom'])),
    ('debug',           BuiltinOption(UserBooleanOption, 'Debug', True)),
    ('default_library', BuiltinOption(UserComboOption, 'Default library type', 'shared', choices=['shared', 'static', 'both'],
                                      yielding=False)),
    ('errorlogs',       BuiltinOption(UserBooleanOption, "Whether to print the logs from failing tests", True)),
    ('install_umask',   BuiltinOption(UserUmaskOption, 'Default umask to apply on permissions of installed files', '022')),
    ('layout',          BuiltinOption(UserComboOption, 'Build directory layout', 'mirror', choices=['mirror', 'flat'])),
    ('optimization',    BuiltinOption(UserComboOption, 'Optimization level', '0', choices=['0', 'g', '1', '2', '3', 's'])),
    ('stdsplit',        BuiltinOption(UserBooleanOption, 'Split stdout and stderr in test logs', True)),
    ('strip',           BuiltinOption(UserBooleanOption, 'Strip targets on install', False)),
    ('unity',           BuiltinOption(UserComboOption, 'Unity build', 'off', choices=['on', 'off', 'subprojects'])),
    ('unity_size',      BuiltinOption(UserIntegerOption, 'Unity block size', (2, None, 4))),
    ('warning_level',   BuiltinOption(UserComboOption, 'Compiler warning level to use', '1', choices=['0', '1', '2', '3'], yielding=False)),
    ('werror',          BuiltinOption(UserBooleanOption, 'Treat warnings as errors', False, yielding=False)),
    ('wrap_mode',       BuiltinOption(UserComboOption, 'Wrap mode', 'default', choices=['default', 'nofallback', 'nodownload', 'forcefallback'])),
    ('force_fallback_for', BuiltinOption(UserArrayOption, 'Force fallback for those subprojects', [])),
])  # type: OptionDictType

BUILTIN_OPTIONS = OrderedDict(chain(BUILTIN_DIR_OPTIONS.items(), BUILTIN_CORE_OPTIONS.items()))

BUILTIN_OPTIONS_PER_MACHINE = OrderedDict([
    ('pkg_config_path', BuiltinOption(UserArrayOption, 'List of additional paths for pkg-config to search', [])),
    ('cmake_prefix_path', BuiltinOption(UserArrayOption, 'List of additional prefixes for cmake to search', [])),
])

# Special prefix-dependent defaults for installation directories that reside in
# a path outside of the prefix in FHS and common usage.
builtin_dir_noprefix_options = {
    'sysconfdir':     {'/usr': '/etc'},
    'localstatedir':  {'/usr': '/var',     '/usr/local': '/var/local'},
    'sharedstatedir': {'/usr': '/var/lib', '/usr/local': '/var/local/lib'},
}

FORBIDDEN_TARGET_NAMES = {'clean': None,
                          'clean-ctlist': None,
                          'clean-gcno': None,
                          'clean-gcda': None,
                          'coverage': None,
                          'coverage-text': None,
                          'coverage-xml': None,
                          'coverage-html': None,
                          'phony': None,
                          'PHONY': None,
                          'all': None,
                          'test': None,
                          'benchmark': None,
                          'install': None,
                          'uninstall': None,
                          'build.ninja': None,
                          'scan-build': None,
                          'reconfigure': None,
                          'dist': None,
                          'distcheck': None,
                          }

