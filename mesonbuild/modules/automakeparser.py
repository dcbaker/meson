# Copyright © 2017 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This module implements a subset of automake parsing rules.

The goal is to be able to read a Makefile that consists only of variables
consisting of lists of source files. To that end only variables assignments are
supported, and all files in a variable must exist (ie, generated sources and
static sources cannot be included in the same variable.

It supports only the following syntax:

    IDENTIFIER = foo.h foo.c bar.c \
            bar.h

    OTHER := other.c \
            $(IDENTIFIER)
"""

import itertools
import os
import re

from . import ExtensionModule, ModuleReturnValue
from ..interpreter import ObjectHolder, InterpreterObject, InterpreterException
from ..interpreterbase import noKwargs
from ..mesonlib import MesonException, File, listify


DECLARATION_RE = re.compile(r'(?P<name>[a-zA-Z0-9_]+)\s+:?=(?P<files>(\s*[$()0-9a-zA-Z_./\-]+)+)')

def parser(fd):
    file = fd.read()
    file = file.replace('\\\n', '')

    parsed = {}
    for each in file.splitlines():
        # Don't choke on newlines or other pure whitespace
        if each and not each.startswith('#'):
            m = DECLARATION_RE.match(each)
            if not m:
                raise MesonException('Unparsable line in makefile: {}'.format(each))
            files = m.group('files').strip()
            new = []
            group = files.split()
            # Resolve nested variables
            for var in group:
                if var == '$()':
                    continue
                elif var.startswith('$'):
                    new.extend(parsed[var[2:-1]])
                else:
                    new.append(var)
            parsed[m.group('name')] = new
    return parsed


class MakeFileSources:

    def __init__(self, filename, sources):
        self.filename = filename
        self.sources = sources

    def __repr__(self):
        return '<MakeFileSources: {}>'.format(self.filename)

    def get(self, keys):
        root = os.path.dirname(self.filename)
        try:
            return [File.from_absolute_file(os.path.join(root, f))
                    for f in itertools.chain.from_iterable(self.sources[k] for k in keys)]
        except KeyError:
            raise MesonException(
                'Makefile "{}" doesn\'t define a variable "{}"'.format(self.filename, key))


class MakeFileSourcesHolder(InterpreterObject, ObjectHolder):

    def __init__(self, obj):
        InterpreterObject.__init__(self)
        ObjectHolder.__init__(self, obj)
        self.methods.update({
            'get': self.get,
        })

    def __repr__(self):
        return '<MakeFileSourcesHolder: {!r}>'.format(self.held_object)

    def get(self, args, kwargs):
        args = listify(args)
        if len(args) < 1:
            raise InterpreterExceptionException('MakeFileSources.get takes at least one argument')
        if not all(isinstance(v, str) for v in args):
            raise InterpreterExceptionException('Variable names must by strings.')
        return self.held_object.get(args)


class MakeFileSourcesModule(ExtensionModule):

    def load(self, state, args, kwargs):
        args = listify(args)
        if len(args) != 1:
            raise MesonException('Automake Parser module takes exactly 1 positional argument')
        filename = args[0]

        here = os.path.join(state.environment.get_source_dir(), state.subdir)
        source_file = os.path.join(here, filename)
        try:
            with open(source_file, 'r') as f:
                sources = parser(f)
        except FileNotFoundError:
            raise MesonException('Source file {} does not exist'.format(source_file))

        state.build_def_files.append(source_file)

        mod = MakeFileSourcesHolder(MakeFileSources(source_file, sources))
        return ModuleReturnValue(mod, [mod])


def initialize():
    return MakeFileSourcesModule()
