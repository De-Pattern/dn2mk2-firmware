# How work reaches `main`

**`main` is merged into by the repository owner, and by nobody and nothing
else.** Everything below exists to make that true in practice rather than by
good intentions.

## The loop

```
feature identified
  └─ branch from main
      └─ develop on the branch
          └─ one atomic commit per group of related actions
              └─ push the branch
                  └─ open an MR, and stop
```

The owner reviews and merges. An MR is not merged by its author.

### Branch from `main`, not from wherever you happen to be

```
git checkout main && git pull
git checkout -b <kind>/<short-subject>
```

`<kind>` is what the change is: `feat`, `fix`, `docs`, `chore`, `analysis`.
The subject is a few words, hyphenated, naming the thing rather than the ticket
— `feat/lfo4-page`, `docs/branching-rules`, `fix/aplib-negative-offset`.

**Documentation-only work gets a branch too.** So does the change that
introduces a rule. There is no size below which this is skipped; the point is
that every change is reviewable as a unit, and an exception costs more to argue
about than to follow.

### One atomic commit per group of actions

A commit is a group of related actions, not a file and not a day. `git add -A`
followed by "wip" is not a commit; neither is one commit per file when the
files change together for one reason.

The test: could this commit be reverted on its own and leave the repository
consistent? If not, it is either too big or too small.

Commit messages say **why**, and say what a number was measured against.
`git log` here is part of the documentation — see `docs/PRINCIPLES.md` §11,
inherited from DNX.

### Open the MR, then stop

Push the branch. Open the MR. Hand over the link. Do not merge it, do not
force-push it once it is pushed, and do not start merging it into other
branches to unblock yourself.

## Never push to `main`

Not to fix a typo, not to land something "obviously safe", not because the
branch is behind. If work has already started on `main` by mistake, branch from
where it is and push the branch — do not push `main` and tidy up afterwards.

### The local guard

`.githooks/pre-push` refuses a push whose target is `main`. It is version
controlled but hooks are not installed automatically, so once per clone:

```
git config core.hooksPath .githooks
```

It is a seatbelt, not the rule. The rule holds whether or not it is installed,
and it can be bypassed with `--no-verify` by anyone who has decided to — which
is the point at which it has done its job by making the decision explicit.

### The server-side guard

The local hook cannot protect the repository from a clone that never installed
it. Branch protection on `main` is the only version that actually holds, and
only the owner can set it. **Enabled 2026-09-07:**

| Setting | |
|---|---|
| Pull request required before merging | yes |
| Approving reviews required | 1 |
| Force pushes | blocked |
| Branch deletion | blocked |
| Required status checks | none |
| Enforced for administrators | no |

Two consequences worth knowing before they surprise someone.

**One approval is required and GitHub does not let you approve your own pull
request.** On a repository with one contributor that means the review box can
never be ticked the normal way, so a merge goes through the administrator
route below rather than through an approval.

**Administrators are not bound**, which is what makes that route exist. The
owner can still merge without an approval and, if it ever becomes necessary,
force-push. That is deliberate: the protection is here to stop accidents and
to stop anyone else, not to lock the owner out of their own repository. It does
mean the rule about not pushing to `main` is still a rule rather than a
mechanism, for exactly one person.

## What this does not change

`docs/PRINCIPLES.md` still governs how the code inside a branch is built.
This file governs only how it gets from a branch to `main`.
