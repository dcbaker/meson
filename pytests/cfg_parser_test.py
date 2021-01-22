from mesonbuild.cargo.cfg_parser import *


class TestLex:

    def test_only_identifier(self) -> None:
        expected = [Function('cfg'), LParen(), Identifier('unix'), RParen()]
        actual = lex('cfg(unix)')
        assert expected == actual

    def test_only_equal(self) -> None:
        expected = [Function('cfg'), LParen(), Identifier('target_identifer'), Equal(), String('x86'), RParen()]
        actual = lex('cfg(target_identifer = "x86")')
        assert expected == actual

    def test_not_identifier(self) -> None:
        expected = [Function('cfg'), LParen(), Function('not'), LParen(), Identifier('unix'), RParen(), RParen()]
        actual = lex('cfg(not(unix))')
        assert expected == actual

    def test_not_equal(self) -> None:
        expected = [Function('cfg'), LParen(), Function('not'), LParen(), Identifier('target_identifier'),
                    Equal(), String('x86'), RParen(), RParen()]
        actual = lex('cfg(not(target_identifier = "x86"))')
        assert expected == actual

    def test_any_identifier(self) -> None:
        expected = [Function('cfg'), LParen(), Function('any'), LParen(), Identifier('unix'), Comma(),
                    Identifier('windows'), RParen(), RParen()]
        actual = lex('cfg(any(unix, windows))')
        assert expected == actual

    def test_any_identifer_and_expr(self) -> None:
        expected = [Function('cfg'), LParen(), Function('any'), LParen(), Identifier('unix'), Comma(),
                    Identifier('target_os'), Equal(), String('linux'), RParen(), RParen()]
        actual = lex('cfg(any(unix, target_os = "linux"))')
        assert expected == actual

    def test_deeply_nested(self) -> None:
        expected = [Function('cfg'), LParen(), Function('all'), LParen(), Function('not'), LParen(),
                    Identifier('target_os'), Equal(), String("windows"), RParen(), Comma(),
                    Function('any'), LParen(), Identifier('target_arch'), Equal(), String("mips"),
                    Comma(), Identifier('target_arch'), Equal(), String("aarch64"), RParen(), RParen(), RParen()]
        actual = lex('cfg(all(not(target_os = "windows"), any(target_arch = "mips", target_arch = "aarch64")))')
        assert expected == actual