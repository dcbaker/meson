# Copyright 2017 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from .base import (  # noqa: F401
    Dependency, DependencyException, DependencyMethods, ExternalProgram,
    ExternalDependency, ExternalLibrary, ExtraFrameworkDependency,
    InternalDependency, PkgConfigDependency, DependencyFactory,
    find_external_dependency, get_dep_identifier, packages,
    _packages_accept_language
)
from .dev import GMockDependency, GTestDependency, LLVMDependency, ValgrindDependency
from .misc import (BoostDependency, MPIDependency, Python3Dependency, ThreadDependency)
from .platform import AppleFrameworks
from .ui import GLDependency, GnuStepDependency, Qt4Dependency, Qt5Dependency, SDL2Dependency, WxDependency, VulkanDependency

_ALL_METHODS = [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL,
                DependencyMethods.EXTRAFRAMEWORK]
_NO_FRAMEWORKS = [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL]

packages.update({
    # From dev:
    'gtest': GTestDependency,
    'gmock': GMockDependency,
    'llvm': LLVMDependency,
    'valgrind': ValgrindDependency,

    # From misc:
    'boost': BoostDependency,
    'mpi': MPIDependency,
    'python3': Python3Dependency,
    'threads': ThreadDependency,
    'pcap': DependencyFactory('pcap', _ALL_METHODS, config_tools=['pcap-config']),
    'cups': DependencyFactory('cups', _ALL_METHODS, config_tools=['cups-config']),
    'libwmf': DependencyFactory('libwmf', _NO_FRAMEWORKS, config_tools=['libwmf-config']),

    # From platform:
    'appleframeworks': AppleFrameworks,

    # From ui:
    'gl': GLDependency,
    'gnustep': GnuStepDependency,
    'qt4': Qt4Dependency,
    'qt5': Qt5Dependency,
    'sdl2': SDL2Dependency,
    'wxwidgets': WxDependency,
    'vulkan': VulkanDependency,
})
_packages_accept_language.update({
    'mpi',
})
