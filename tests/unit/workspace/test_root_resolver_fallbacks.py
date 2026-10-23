"""Unit tests for the fallback branches of ``specify_cli.workspace.root_resolver``.

The existing ``test_root_resolver.py`` drives the resolver through real git
repositories.  These tests cover the defensive early-return and fallback paths
of ``resolve_status_lock_root`` and ``canonicalize_feature_dir`` instead.  The
git-backed collaborators (``is_registered_coord_worktree`` and
``resolve_canonical_root``) are replaced with test doubles (stubs that return or
raise a canned result, mocks that also record how they were called), so no git
repository has to exist on disk.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from specify_cli.coordination import surface_resolver
from specify_cli.core.constants import KITTY_SPECS_DIR
from specify_cli.workspace import root_resolver
from specify_cli.workspace.root_resolver import (
    WorkspaceRootNotFound,
    canonicalize_feature_dir,
    resolve_status_lock_root,
)


pytestmark = [pytest.mark.fast, pytest.mark.unit]


def _stub_registry(monkeypatch: pytest.MonkeyPatch, *, registered: bool = False, unreadable: bool = False) -> Mock:
    """Replace the git worktree-registry lookup with a test double."""
    error = surface_resolver.WorktreeRegistryUnavailable(repo_root=Path("repo"), detail="registry unreadable")
    double = Mock(side_effect=error) if unreadable else Mock(return_value=registered)
    monkeypatch.setattr(surface_resolver, "is_registered_coord_worktree", double)
    return double


def _stub_resolver(monkeypatch: pytest.MonkeyPatch, *, root: Path | None = None, not_found_at: Path | None = None) -> Mock:
    """Replace the canonical-root resolver with a test double."""
    double = Mock(side_effect=WorkspaceRootNotFound(not_found_at)) if not_found_at is not None else Mock(return_value=root)
    monkeypatch.setattr(root_resolver, "resolve_canonical_root", double)
    return double


def test_status_lock_root_is_feature_dir_outside_kitty_specs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    resolver = _stub_resolver(monkeypatch)
    feature_dir = tmp_path / "adhoc" / "some-mission"

    assert resolve_status_lock_root(feature_dir) == feature_dir
    resolver.assert_not_called()


def test_canonicalize_returns_input_outside_kitty_specs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _stub_registry(monkeypatch)
    resolver = _stub_resolver(monkeypatch)
    feature_dir = tmp_path / "adhoc" / "some-mission"

    assert canonicalize_feature_dir(feature_dir) == feature_dir
    registry.assert_not_called()
    resolver.assert_not_called()


def test_canonicalize_keeps_coord_path_when_registry_is_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_registry(monkeypatch, unreadable=True)
    resolver = _stub_resolver(monkeypatch)
    feature_dir = tmp_path / ".worktrees" / "042-demo-coord" / KITTY_SPECS_DIR / "042-demo"

    assert canonicalize_feature_dir(feature_dir) == feature_dir
    resolver.assert_not_called()


def test_canonicalize_resolves_when_registry_is_unreadable_and_path_is_not_coord(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_registry(monkeypatch, unreadable=True)
    canonical_root = tmp_path / "main"
    canonical_feature_dir = canonical_root / KITTY_SPECS_DIR / "042-demo"
    canonical_feature_dir.mkdir(parents=True)
    resolver = _stub_resolver(monkeypatch, root=canonical_root)
    feature_dir = tmp_path / "checkout" / KITTY_SPECS_DIR / "042-demo"

    assert canonicalize_feature_dir(feature_dir) == canonical_feature_dir
    resolver.assert_called_once_with(feature_dir)


def test_canonicalize_returns_input_when_no_canonical_root_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_registry(monkeypatch)
    feature_dir = tmp_path / "loose" / KITTY_SPECS_DIR / "042-demo"
    resolver = _stub_resolver(monkeypatch, not_found_at=tmp_path)

    assert canonicalize_feature_dir(feature_dir) == feature_dir
    resolver.assert_called_once_with(feature_dir)


def test_canonicalize_returns_input_when_canonical_feature_dir_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_registry(monkeypatch)
    canonical_root = tmp_path / "main"
    canonical_root.mkdir()
    _stub_resolver(monkeypatch, root=canonical_root)
    feature_dir = tmp_path / "worktree" / KITTY_SPECS_DIR / "042-demo"

    assert canonicalize_feature_dir(feature_dir) == feature_dir


def test_canonicalize_redirects_to_existing_canonical_feature_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _stub_registry(monkeypatch)
    canonical_root = tmp_path / "main"
    canonical_feature_dir = canonical_root / KITTY_SPECS_DIR / "042-demo"
    canonical_feature_dir.mkdir(parents=True)
    _stub_resolver(monkeypatch, root=canonical_root)
    feature_dir = tmp_path / "worktree" / KITTY_SPECS_DIR / "042-demo"

    assert canonicalize_feature_dir(feature_dir) == canonical_feature_dir
    registry.assert_called_once_with(feature_dir)


class FakeWorktreeRegistry:
    """Fake: a small working in-memory registry used instead of reading git."""

    def __init__(self, registered: set[Path]) -> None:
        self.registered = set(registered)
        self.queries: list[Path] = []

    def __call__(self, path: Path, **_: object) -> bool:
        self.queries.append(path)
        return path in self.registered


def test_canonicalize_uses_fake_registry_to_tell_registered_coord_from_plain_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coord_feature_dir = tmp_path / ".worktrees" / "042-demo-coord" / KITTY_SPECS_DIR / "042-demo"
    plain_feature_dir = tmp_path / "checkout" / KITTY_SPECS_DIR / "042-demo"
    fake = FakeWorktreeRegistry(registered={coord_feature_dir})
    monkeypatch.setattr(surface_resolver, "is_registered_coord_worktree", fake)
    _stub_resolver(monkeypatch, root=tmp_path / "main")

    assert canonicalize_feature_dir(coord_feature_dir) == coord_feature_dir
    assert canonicalize_feature_dir(plain_feature_dir) == plain_feature_dir
    assert fake.queries == [coord_feature_dir, plain_feature_dir]
