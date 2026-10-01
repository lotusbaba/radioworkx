"""Exploration goals, not substitutes for the deterministic regression suite."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Scenario:
    path: str
    goal: str
    values: tuple[str, ...]
    # Exact observed field labels -> one assigned value per independently run case.
    fills: tuple[tuple[str, str], ...] = ()
    search_kind: str | None = None
    search_query: str = ''
    search_result: str = ''


SCENARIOS = {
    'library-search': Scenario('/',
        'Starting on the home page, open the Search modal. Choose Artist in Search by, '
        'enter QA Artist in Search text, and verify QA Artist appears in the modal results. '
        'Stay on the home page and finish only after the matching result is visible.',
        ('QA Artist',), (('Search text', 'QA Artist'),), 'artist', 'QA Artist', 'QA Artist'),
    'auth-popup': Scenario('/',
        'Open Sign in. Switch to registration and back, try an invalid email, close the dialog with its close button, '
        'then reopen it. Verify visually that authentication remains an in-page dialog. Do not navigate away.',
        ('invalid-email', 'synthetic-password-123'),
        (('Email address', 'invalid-email'), ('Password · 12–128 characters', 'synthetic-password-123'))),
    'playlist-duplicate': Scenario('/my-music',
        'Register qa-listener@example.invalid with synthetic-password-123. Create two playlists both named QA Playlist. '
        'Finish after observing whether the duplicate is rejected.',
        ('qa-listener@example.invalid', 'synthetic-password-123', 'QA Playlist'),
        (('Email address', 'qa-listener@example.invalid'), ('Password · 12–128 characters', 'synthetic-password-123'),
         ('New playlist', 'QA Playlist'), ('Playlist name', 'QA Playlist'), ('New playlist name', 'QA Playlist'))),
    'social-sharing': Scenario('/my-music',
        'Register qa-listener@example.invalid with synthetic-password-123. Create QA Playlist, share it, '
        'open the public playlist link, return to My music and make it private. Exercise repeated share/copy controls.',
        ('qa-listener@example.invalid', 'synthetic-password-123', 'QA Playlist'),
        (('Email address', 'qa-listener@example.invalid'), ('Password · 12–128 characters', 'synthetic-password-123'),
         ('New playlist', 'QA Playlist'), ('Playlist name', 'QA Playlist'), ('New playlist name', 'QA Playlist'))),
}

# Run the whitespace variant independently; never ask a model which payload to cover.
SCENARIOS['playlist-duplicate-trimmed'] = replace(
    SCENARIOS['playlist-duplicate'],
    goal='Register qa-listener@example.invalid with synthetic-password-123. Create two playlists '
         'using the name "  QA Playlist  " including surrounding spaces. Check whether the '
         'duplicate trimmed name is rejected, then finish.',
    values=('qa-listener@example.invalid', 'synthetic-password-123', '  QA Playlist  '),
    fills=tuple((label, '  QA Playlist  ' if value == 'QA Playlist' else value)
                for label, value in SCENARIOS['playlist-duplicate'].fills))

for kind, name in [('album', 'QA Album'), ('track', 'QA Track')]:
    SCENARIOS['search-'+kind] = replace(SCENARIOS['library-search'],
        goal=f'From home, open Search, choose {kind.title()} in Search by, enter {name} '
             f'in Search text and verify {name} is visible in modal results. Stay on home.',
        values=(name,), fills=(('Search text', name),), search_kind=kind,
        search_query=name, search_result=name)
SCENARIOS['search-artist-typo'] = replace(SCENARIOS['library-search'],
    goal='From home, open Search, choose Artist, enter QA Artst and verify the fuzzy '
         'results include QA Artist. Stay on home.', values=('QA Artst',),
    fills=(('Search text', 'QA Artst'),), search_query='QA Artst')
