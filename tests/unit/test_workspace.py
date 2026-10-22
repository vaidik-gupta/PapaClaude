"""Unit tests for app.workspace — directory resolution and listing."""

import os

import pytest

from app.workspace import list_subdirectories, resolve_directory


def test_resolve_directory_expands_and_absolutizes(tmp_path):
    assert resolve_directory(str(tmp_path)) == str(tmp_path.resolve())
    # A relative path resolves against the cwd.
    assert resolve_directory(".") == os.path.abspath(".")


def test_resolve_directory_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_directory("~") == str(tmp_path.resolve())


def test_resolve_directory_requires_value():
    with pytest.raises(ValueError, match="required"):
        resolve_directory("")
    with pytest.raises(ValueError, match="required"):
        resolve_directory(None)


def test_resolve_directory_rejects_missing(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        resolve_directory(str(tmp_path / "nope"))


def test_resolve_directory_rejects_file(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("hi")
    with pytest.raises(ValueError, match="does not exist"):
        resolve_directory(str(f))


def test_list_subdirectories_lists_only_dirs(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "file.txt").write_text("x")
    listing = list_subdirectories(str(tmp_path))
    assert listing["path"] == str(tmp_path.resolve())
    assert listing["entries"] == ["alpha", "beta"]
    assert listing["parent"] == str(tmp_path.resolve().parent)
    assert listing["home"] == os.path.expanduser("~")


def test_list_subdirectories_defaults_to_home(monkeypatch, tmp_path):
    (tmp_path / "x").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    listing = list_subdirectories(None)
    assert listing["path"] == str(tmp_path.resolve())
