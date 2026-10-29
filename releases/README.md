# Release announcements

One file a release, `releases/vX.Y.md`: pushing it, new, to `main` makes the release vX.Y and its tag.
Its first line, `# TITLE`, names the GitHub release; the rest is the notes, posted as they
are to Discord's #announcements by `.github/workflows/discord-release.yml` (Discord markdown:
**bold**, bullet lines, links; at most about 4,000 characters, the rest cut). No firmware is
attached to a release: players build the cleared file with the patcher from their own
Elektron OS files.

The shape (the owner's posts, from v0.29): lowercase and casual, players' words, short
bullets, credit the reporter.

    # 🚨 vX.Y is out: NAME

    patcher: de-pattern.github.io/dn2mk2

    **fixed / new**
    - what changed, in a line or two each (what was wrong, what it does now)

    **test**
    1. a thing to do, and what you should hear or see

    **known issues**
    - what still misbehaves, with a workaround where there is one

    **coming next (not available yet)**
    - what the next version is for

    sha256 `first8…last8` · back up your +Drive first · not made or supported by Elektron
