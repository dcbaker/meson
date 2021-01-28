from mesonbuild.cargo.cfg_parser import *


class TestLex:

    def test_only_identifier(self) -> None:
        expected = [Identifier('cfg'), LParen(), Identifier('unix'), RParen()]
        actual = lex('cfg(unix)')
        assert expected == actual

    def test_only_equal(self) -> None:
        expected = [Identifier('cfg'), LParen(), Identifier('target_identifer'), Equal(), Identifier('"x86"'), RParen()]
        actual = lex('cfg(target_identifer = "x86")')
        assert expected == actual

    def test_not_identifier(self) -> None:
        expected = [Identifier('cfg'), LParen(), Identifier('not'), LParen(), Identifier('unix'), RParen(), RParen()]
        actual = lex('cfg(not(unix))')
        assert expected == actual

    def test_not_equal(self) -> None:
        expected = [Identifier('cfg'), LParen(), Identifier('not'), LParen(), Identifier('target_identifier'),
                    Equal(), Identifier('"x86"'), RParen(), RParen()]
        actual = lex('cfg(not(target_identifier = "x86"))')
        assert expected == actual

    def test_any_identifier(self) -> None:
        expected = [Identifier('cfg'), LParen(), Identifier('any'), LParen(), Identifier('unix'), Comma(),
                    Identifier('windows'), RParen(), RParen()]
        actual = lex('cfg(any(unix, windows))')
        assert expected == actual

    def test_any_identifer_and_expr(self) -> None:
        expected = [Identifier('cfg'), LParen(), Identifier('any'), LParen(), Identifier('unix'), Comma(),
                    Identifier('target_os'), Equal(), Identifier('"linux"'), RParen(), RParen()]
        actual = lex('cfg(any(unix, target_os = "linux"))')
        assert expected == actual

    def test_deeply_nested(self) -> None:
        expected = [Identifier('cfg'), LParen(), Identifier('all'), LParen(), Identifier('not'), LParen(),
                    Identifier('target_os'), Equal(), Identifier('"windows"'), RParen(), Comma(),
                    Identifier('any'), LParen(), Identifier('target_arch'), Equal(), Identifier('"mips"'),
                    Comma(), Identifier('target_arch'), Equal(), Identifier('"aarch64"'), RParen(), RParen(), RParen()]
        actual = lex('cfg(all(not(target_os = "windows"), any(target_arch = "mips", target_arch = "aarch64")))')
        assert expected == actual


class TestParse:

    def test_single_function_with_const(self) -> None:
        expected = AST(FunctionNode('cfg', [ConstantNode('unix')]))

        lexed = lex('cfg(unix)')
        ast = parse(lexed)

        assert ast == expected

    def test_single_function_with_two_consts(self) -> None:
        expected = AST(FunctionNode('cfg', [ConstantNode('unix'), ConstantNode('windows')]))

        lexed = lex('cfg(unix, windows)')
        ast = parse(lexed)

        assert ast == expected

    def test_nested_function_with_const(self) -> None:
        expected = AST(FunctionNode('cfg', [FunctionNode('not', [ConstantNode('windows')])]))

        lexed = lex('cfg(not(windows))')
        ast = parse(lexed)

        assert ast == expected

    def test_eq(self) -> None:
        expected = AST(FunctionNode('cfg', [ConstantNode('target_os'), EqualityNode(), StringNode('windows')]))

        lexed = lex('cfg(target_os = "windows")')
        ast = parse(lexed)

        assert ast == expected

    def test_deeply_nested(self) -> None:
        expected = AST(FunctionNode('cfg', [FunctionNode('any', [FunctionNode('all', [ConstantNode('target_os'), EqualityNode(), StringNode('windows'), ConstantNode('target_arch'), EqualityNode(), StringNode('x86')]), ConstantNode('unix')])]))

        lexed = lex('cfg(any(all(target_os = "windows", target_arch = "x86"), unix))')
        ast = parse(lexed)

        assert ast == expected