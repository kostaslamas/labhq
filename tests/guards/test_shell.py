import pytest

from labhq.guards.shell import UnparsableCommandError, parse


@pytest.mark.parametrize(
    ("script", "commands"),
    [
        ("a; b && c || d | e & f", [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]]),
        ("a\nb", [["a"], ["b"]]),
        ("a x 2>&1 >out <in", [["a", "x"]]),
        ("> out a x", [["a", "x"]]),
        ("echo a#b; c", [["echo", "a#b"], ["c"]]),
        ("a 'b c' \"d e\"", [["a", "b c", "d e"]]),
        ("a \\\n b", [["a", "b"]]),
    ],
)
def test_commands_split_on_operators_and_skip_redirections(
    script: str, commands: list[list[str]]
) -> None:
    assert parse(script).commands == commands


@pytest.mark.parametrize(
    ("script", "nested"),
    [
        ("echo $(a b)", ["a b"]),
        ('echo "$(a b)"', ["a b"]),
        ("echo `a b`", ["a b"]),
        ("cat <(a) >(b)", ["a", "b"]),
        ("echo $(a $(b))", ["a $(b)"]),
        ("x <<< 'a b'", ["a b"]),
    ],
)
def test_substitutions_and_here_strings_are_nested_scripts(script: str, nested: list[str]) -> None:
    assert parse(script).nested == nested


def test_here_document_bodies_are_kept_apart() -> None:
    parsed = parse("cat > f <<'EOF'\nline one\nline two\nEOF\necho done")

    assert parsed.commands == [["cat"], ["echo", "done"]]
    assert parsed.documents == ["line one\nline two"]


def test_an_unterminated_quote_is_unparsable() -> None:
    with pytest.raises(UnparsableCommandError):
        parse("echo 'oops")


def test_lenient_parsing_keeps_the_words_of_an_unbalanced_script() -> None:
    assert parse("echo it's; b", lenient=True).commands == [["echo", "it", "s"], ["b"]]
