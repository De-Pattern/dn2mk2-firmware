# Contributing

Thanks for your interest in DN2 mk2 mod! Bug reports, documentation improvements
and focused code changes all help. You do not need to work on the firmware to
contribute: clarifying a confusing instruction is a useful place to start.

## Reporting bugs and suggesting changes

Check the [existing issues](https://github.com/De-Pattern/dn2mk2-firmware/issues)
and the [known limitations](README.md#known-limitations) first. If you report a
bug, include:

- The mod version and relevant setup.
- Steps to reproduce it.
- What you expected and what happened instead.
- Relevant logs or screenshots, without private data or firmware files.

For a larger change, opening an issue to discuss the idea first helps keep the
work focused. Explain the problem you want to solve and how the change would help.

## Getting started

Fork the repository and clone your fork. Check `git remote -v`: `origin` should
point to your fork. If `upstream` is not already configured, add it once:

```sh
git remote add upstream https://github.com/De-Pattern/dn2mk2-firmware.git
```

With a clean working tree, create a branch from the latest upstream `main`:

```sh
git fetch upstream main
git switch --no-track -c docs/my-doc-fix upstream/main
```

Choose a short branch name beginning with `docs/`, `fix/`, `feat/`, `chore/` or
`analysis/`. See [BRANCHING](docs/BRANCHING.md) for the review workflow and the
local pre-push hook that guards against accidental pushes to `main`.

For Python development, use Python 3.11+ in a virtual environment, then install
from the repository root:

```sh
python -m pip install -e ".[dev]"
```

## Making and checking a change

Keep each PR focused on one problem and follow the conventions of the surrounding
code. The project's [architecture principles](docs/PRINCIPLES.md) describe the
expectations for code, evidence and documentation.

- **Documentation:** check the wording, links and Markdown preview. Run
  `git diff --check`; a text-only change does not need a firmware build or flash.
- **Python code:** run the relevant tests in `test/`, for example
  `python -m pytest test/test_aplib.py`, and add regression coverage for changed
  behavior. Report skipped tests or missing prerequisites alongside the results.
- **Firmware:** follow [SAFETY](docs/SAFETY.md) and the gate instructions in
  [CLAUDE.md](CLAUDE.md). Run affected steps first, then the full gate. Only
  `CLEARED TO FLASH` from a full run on the exact build clears it for flashing;
  partial checks do not. A failed gate or missing tool means do not flash.
  See [emulator documentation](docs/emulator.md) for the external tooling.

Update the relevant documentation and [project status](docs/STATUS.md) when a
change adds behavior or research findings. Keep Elektron OS files, generated
firmware (`.syx`, `.bin`), local resources and scratch output out of your commits.
Firmware publication follows the separate process in [CLAUDE.md](CLAUDE.md).

## Opening a pull request

1. Review your diff and commit the related changes with a message explaining why.
2. Push your branch to your fork: `git push -u origin docs/my-doc-fix`
   (replace the example branch name with yours).
3. Open a PR from your fork's branch to **De-Pattern/dn2mk2-firmware:main**.
4. Explain the problem, your change, and how you checked it. Link any relevant
   issue and say what remains untested, including hardware checks.

The repository owner reviews and merges PRs. Do not push directly to `main` or
merge your own PR. If changes are requested, add commits to the same branch and
push again to update the PR; do not force-push a published branch.
