"""v0.48: the gate cache's guard against another worktree's passes (scripts/gate_cache.py
_foreign, v0.47), with its negative control.

The scenario it exists for (v0.47): a cache copied from v046-wt into v047-wt. Its records
named v046-wt's files; looked up from v047-wt, those files were still there and unchanged,
so every input "matched" and v0.46's unit-test pass was reused for v0.47's changed tree.

Reproduced here in a temporary directory laid out as the real one: a repository (its .git
directory) and two worktrees of it (each a .git file naming a gitdir whose commondir is the
repository's). A pass is stored in worktree A reading A's own file; the cache file is copied
into worktree B, whose own copy of that file differs."""

from __future__ import annotations

import pathlib
import shutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import gate_cache as GC                                         # noqa: E402


def _layout(tmp: pathlib.Path):
    repo = tmp / "repo"
    (repo / ".git" / "worktrees" / "a").mkdir(parents=True)
    (repo / ".git" / "worktrees" / "b").mkdir(parents=True)
    trees = {}
    for n in ("a", "b"):
        wt = tmp / f"{n}-wt"
        (wt / "test").mkdir(parents=True)
        gd = repo / ".git" / "worktrees" / n
        (gd / "commondir").write_text("../..\n")
        (wt / ".git").write_text(f"gitdir: {gd}\n")
        (wt / "test" / "test_x.py").write_text(f"# {n}'s tree\n")
        trees[n] = wt
    return trees


def _store_pass_in(wt: pathlib.Path):
    f = wt / "test" / "test_x.py"
    ins = {str(f): "f:" + GC._sha(str(f))}
    GC.store(wt, "unit", ["pytest", "test/test_x.py"], ins, "a pass", "sha-a")
    return ins


def test_own_pass_is_reused(tmp_path):
    t = _layout(tmp_path)
    _store_pass_in(t["a"])
    assert GC.lookup(t["a"], "unit", ["pytest", "test/test_x.py"], t["a"]) is not None


def test_a_pass_copied_from_another_worktree_is_refused(tmp_path):
    t = _layout(tmp_path)
    _store_pass_in(t["a"])
    (t["b"] / "out").mkdir()
    shutil.copytree(t["a"] / "out" / "gate_cache", t["b"] / "out" / "gate_cache")
    # B's own file differs, A's is untouched: the stale record's input still hashes the same
    (t["b"] / "test" / "test_x.py").write_text("# b changed\n")
    assert GC.lookup(t["b"], "unit", ["pytest", "test/test_x.py"], t["b"]) is None


def test_negative_control_without_the_guard_the_stale_pass_is_reused(tmp_path, monkeypatch):
    """the guard is what refuses it: switched off, the very same lookup reuses A's pass for B"""
    t = _layout(tmp_path)
    _store_pass_in(t["a"])
    (t["b"] / "out").mkdir()
    shutil.copytree(t["a"] / "out" / "gate_cache", t["b"] / "out" / "gate_cache")
    (t["b"] / "test" / "test_x.py").write_text("# b changed\n")
    monkeypatch.setattr(GC, "_foreign", lambda path, root: False)
    assert GC.lookup(t["b"], "unit", ["pytest", "test/test_x.py"], t["b"]) is not None


def test_an_unrelated_sibling_directory_is_not_foreign(tmp_path):
    t = _layout(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "f").write_text("x")
    assert not GC._foreign(str(other / "f"), t["a"])
    assert GC._foreign(str(t["b"] / "test" / "test_x.py"), t["a"])
    assert not GC._foreign(str(t["a"] / "test" / "test_x.py"), t["a"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
