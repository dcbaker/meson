# Copyright 2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Implements an interface for posix-compliant compilers."""

import typing


class PosixCompilerMixin:

    """Interfaces that are posix compliant.

    This list is obviously very short, and is based Posix c99 interface
    specification.
    """

    def get_compile_only_args(self) -> typing.List[str]:
        return ['-c']

    def get_preprocess_only_args(self) -> typing.List[str]:
        return ['-E']

    def get_include_args(self, path: str, is_system: bool) -> typing.List[str]:
        if path == '':
            path = '.'
        return ['-I' + path]

    def get_no_optimization_args(self) -> typing.List[str]:
        return ['-O0']

    def get_output_args(self, target: str) -> typing.List[str]:
        return ['-o', target]
