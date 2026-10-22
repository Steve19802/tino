'''Diagnostics parsing for both the human and the short formats.'''

from tino.services.compiler import parse_diagnostics


def test_short_format():
    stderr = (
        'fixtures/decks/fallbacks.typ:9:32: warning: exported as a picture: '
        'scaled, skewed or mirrored text\n'
        'out/broken.typ:1:9: error: unclosed delimiter\n'
    )
    assert parse_diagnostics(stderr) == [
        {
            'severity': 'warning', 'file': 'fixtures/decks/fallbacks.typ',
            'line': 9, 'column': 32,
            'message': 'exported as a picture: scaled, skewed or mirrored text',
        },
        {
            'severity': 'error', 'file': 'out/broken.typ',
            'line': 1, 'column': 9, 'message': 'unclosed delimiter',
        },
    ]


def test_human_format():
    stderr = (
        'error: unknown variable: `foo`\n'
        '  ┌─ main.typ:3:5\n'
        '  │\n'
        '3 │ foo\n'
        '  │ ^^^\n'
    )
    assert parse_diagnostics(stderr) == [
        {
            'severity': 'error', 'file': 'main.typ', 'line': 3, 'column': 5,
            'message': 'unknown variable: `foo`',
        },
    ]


def test_location_less_with_hint():
    stderr = (
        'error: typst-pptx needs Touying 0.8 or newer (found 0.7.4)\n'
        '  = hint: update the import to @preview/touying:0.8.0\n'
    )
    assert parse_diagnostics(stderr) == [
        {
            'severity': 'error', 'file': None, 'line': None, 'column': None,
            'message': 'typst-pptx needs Touying 0.8 or newer (found 0.7.4)',
        },
    ]


def test_empty():
    assert parse_diagnostics('') == []
