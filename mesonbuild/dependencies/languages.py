# Copyright 2020 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This file contains dependencies for building against programming languages."""

import typing as T

from .base import ConfigToolDependency

if T.TYPE_CHECKING:
    from ..environment import Environment


class PHPConfigToolDependency(ConfigToolDependency):

    tool_name = 'php-config'
    tools = ['php-config']

    """Integration for php-config."""

    def __init__(self, environment: 'Environment', kwargs: T.Dict[str, T.Any]):
        super().__init__('php', environment, kwargs)
        if not self.is_found:
            return
        self.compile_args = self.get_config_value(['--includes'], 'compile_args')
        self.link_args = self.get_config_value(['--ldflags', '--libs'], 'link_args')
        version = self.get_config_value(['--version'], 'version')
        self.version = version[0] if version else None
