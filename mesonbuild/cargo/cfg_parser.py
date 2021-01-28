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

_T = T.TypeVar('_T')


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
    final: T.List[str] = []

    while expr:
        for i, c in enumerate(expr):
            if c == '(':
                final.append(Identifier(expr[:i]))
                final.append(LParen())
                i += 1  # for the paren
                break
            if c in {' ', ')', ','}:
                if expr[0] == '=':
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


class AST:

    def __init__(self, root: T.Optional['FunctionNode'] = None):
        self.root = root

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AST):
            return NotImplemented
        return self.root == other.root

    def __repr__(self) -> str:
        return f'AST({self.root!r})'

    def __iter__(self) -> T.Iterator['Node']:
        yield self.root
        yield from self.root


class Node:
    pass


class FunctionNode(Node):

    def __init__(self, name: str, arguments: T.Optional[T.List[Node]] = None):
        self.name = name
        self.arguments: T.List[Node] = arguments or []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FunctionNode):
            return NotImplemented
        return self.name == other.name and self.arguments == other.arguments

    def __repr__(self) -> str:
        return f'FunctionNode({self.name}, {self.arguments!r})'

    def __iter__(self) -> T.Iterator[Node]:
        for node in self.arguments:
            yield node
            if isinstance(node, FunctionNode):
                yield from node


class StringNode(Node):

    def __init__(self, value: str):
        self.value = value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StringNode):
            return NotImplemented
        return self.value == other.value

    def __repr__(self) -> str:
        return f'StringNode({self.value})'


class ConstantNode(Node):

    def __init__(self, value: str):
        self.value = value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ConstantNode):
            return NotImplemented
        return self.value == other.value

    def __repr__(self) -> str:
        return f'ConstantNode({self.value})'

class EqualityNode(Node):

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EqualityNode):
            return NotImplemented
        return True

    def __repr__(self) -> str:
        return 'EqualityNode()'


def lookahead(it: T.Iterator[_T]) -> T.Generator[T.Tuple[_T, T.Optional[_T]], None, None]:
    """Iterator for single lookahead functionality

    This gnerator yeilds (N, N+1) then (N+1, N+2), etc.
    """
    current = next(it)
    for next_ in it:
        yield (current, next_)
        current = next_
    yield (current, None)


def parse(prog: T.List[Token]) -> AST:
    """Parse the lexed form into a Tree."""
    tree = AST()
    stack: T.List[Node] = []
    node: T.Optional[Node] = None

    for cur, nex in lookahead(iter(prog)):
        if isinstance(cur, Identifier):
            if isinstance(nex, LParen):
                # We have a function
                node = FunctionNode(cur.identifier)
                if stack:
                    p = stack[-1]
                    assert isinstance(p, FunctionNode)
                    p.arguments.append(node)
                stack.append(node)
            elif isinstance(nex, (RParen, Comma, Equal)):
                # We have an argument to a function
                assert isinstance(node, FunctionNode)
                if cur.identifier.startswith('"'):
                    node.arguments.append(StringNode(cur.identifier[1:-1]))  # strip the quotes
                else:
                    node.arguments.append(ConstantNode(cur.identifier))
        elif isinstance(cur, Equal):
            assert isinstance(node, FunctionNode)
            node.arguments.append(EqualityNode())
        elif isinstance(cur, RParen):
            del stack[-1]
            if stack:
                node = stack[-1]
            else:
                assert nex is None
        if tree.root is None:
            tree.root = node

    return tree


def transform_eq_to_function(node: Node) -> bool:
    """Lower cases of the use of = to a function.

    It's easier to work with `eq(const, str)` than `const = str`
    """
    progress = False
    if not isinstance(node, FunctionNode):
        return progress

    eq = EqualityNode()

    while eq in node.arguments:
        i = node.arguments.index(eq)
        func = FunctionNode('equal', [node.arguments[i - 1], node.arguments[i + 1]])
        args = node.arguments.copy()
        args[i - 1] = func
        del args[i:i + 2]  # left is inclusive, right is exclusive
        node.arguments = args
        progress = True

    return progress


def transform_bare_constant_to_function(node: Node) -> bool:
    """Transform bare constants into equality functions

    cargo has a short hand syntax to replace `target_famil = "foo"` with
    simply "foo". To make later handling more uniform let's convert that to
    `equal(target_family, "foo")`
    """
    progress = False
    if not isinstance(node, FunctionNode):
        return progress

    for const in [ConstantNode("unix"), ConstantNode("windows")]:
        while True:
            try:
                i = node.arguments.index(const)
            except ValueError:
                break

            n = node.arguments[i]
            assert isinstance(n, ConstantNode), 'for mypy'
            func = FunctionNode('equal', [ConstantNode('target_family'), StringNode(n.value)])
            node.arguments[i] = func
            progress = True

    return progress


def transform_ast(ast: AST, tformers: T.Sequence[T.Callable[[Node], bool]]) -> None:
    """Run a sequence of callables on the AST.

    Each transformation function should make transformations, and return True
    if it made changes, otherwise return False.
    """
    progress = True
    while progress:
        progress = False
        for node in ast:
            for t in tformers:
                progress |= t(node)