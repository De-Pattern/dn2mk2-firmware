# Release announcements

One file a release, `releases/vX.Y.md`, committed on `main` before the tag `vX.Y` is pushed.
Its first line, `# TITLE`, names the GitHub release; the rest is the notes, posted as they
are to Discord's #announcements by `.github/workflows/discord-release.yml` (Discord markdown:
**bold**, bullet lines, links; at most about 4,000 characters, the rest cut). No firmware is
attached to a release: players build the cleared file with the patcher from their own
Elektron OS files.

The shape (as the posts so far):

    # vX.Y · NAME

    One or two lines: what this version is for.

    **New** / **Fixed** / **Changed**: short bullets, players' words, credit the reporter.

    **Test** (after the regression check): numbered, each one a thing to do and what to hear.

    **Known issues**: bullets.

    **Coming next** (not available yet): bullets.

    Get it: the DN2 Mod Patcher (https://de-pattern.github.io/dn2mk2/patcher.html), build vX.Y
    from your own OS files; sha256 `…` (first and last 8). Back up your +Drive first.
