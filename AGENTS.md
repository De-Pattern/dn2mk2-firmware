# Sidecar bridge review candidate

- Read `docs/sidecar-review.md` before building or changing the adapter.
- This is source preparation, not a release. Generated firmware payloads remain
  at upstream baseline and must be regenerated before preparing a flash image.
- Keep private Pi plugin code, manifests, resources, credentials and device logs
  out of this repository. Legacy storage/wire compatibility is deliberately kept.
- Use changed-layer checks; do not add mandatory full-build gates for ordinary
  edits. Follow the maintainer's release process when actually making a release.
- No publishing or device writes are authorized by this source preparation;
  upstream release/publication instructions do not apply to this task.
- Run Windows commands/subprocesses hidden; never open a terminal window.
