# SPDX-license-identifier: Apache-2.0
# Copyright © 2021 Intel Corporation

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Parser and lexer for cargo's cfg() expressions.

cfg expression shave the following properties:
- they may contain a couple of non asignment expressions: unix, windows, for example
- they may consist of assignment expressions in the form
    target_arch = "x86"
    target_os = "linux"
- `all()`, `inot()`, `any()` expressions:
    all(target_arch = "x86", target_os = "linux")

    `all()` and `any()` take comma separate lists of arguments.
"""

import typing as T


FUNCTIONS = ['cfg', 'not', 'all', 'any']


class Token:

    """Base class for lex tokens."""

    def __init__(self, identifier: str):
        assert identifier, 'should not get empty identifer'
        self.identifier = identifier

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.identifier == other.identifier

    def __repr__(self) -> str:
        return f'{type(self).__name__}({self.identifier})'


class Function(Token):
    pass


class String(Token):
    pass


class Identifier(Token):
    pass


class Equal(Token):

    def __init__(self):
        super().__init__('=')


class Comma(Token):

    def __init__(self):
        super().__init__(',')


class LParen(Token):

    def __init__(self):
        super().__init__('(')


class RParen(Token):

    def __init__(self):
        super().__init__(')')


def lex(expr: str) -> T.List[Token]:
    # TODO: this is probably assigning too much meaning to things. It should
    # probably just return Identifiers, parens, and commas...
    final: T.List[str] = []

    while expr:
        for i, c in enumerate(expr):
            if c == '(':
                final.append(Function(expr[:i]))
                final.append(LParen())
                i += 1  # for the paren
                break
            if c in {' ', ')', ','}:
                if expr[0] == '"':
                    final.append(String(expr[1:i - 1]))
                elif expr[0] == '=':
                    final.append(Equal())
                elif i:  # not if the first character is not a comma, space, or )
                    final.append(Identifier(expr[:i]))

                if c == ')':
                    final.append(RParen())
                    i += 1  # for the paren
                elif c == ',':
                    final.append(Comma())
                    i += 1  # for the comma
                break
        else:
            raise Exception('WAT?')
        expr = expr[i:].lstrip()

    return final


def parse(prog: T.List[Token]):
    # Yeah, do some parsing and stuff