"""Tests for comprehension.build_codebase_digest."""

from pathlib import Path

import pytest

from comprehension import MAX_SOURCE_BYTES, build_codebase_digest


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# PolicyAdmin\nLegacy policy system.")
    (tmp_path / "requirements.txt").write_text("flask==2.0\n")
    (tmp_path / "app.py").write_text(
        "PREMIUM_ROUNDING = 'bankers'\n" + "def rate(x):\n    return x * 1.18\n" * 50)
    (tmp_path / "db.py").write_text("import sqlite3\n")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-SECRET\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    junk = tmp_path / "node_modules" / "lib"
    junk.mkdir(parents=True)
    (junk / "index.js").write_text("module.exports = 1;")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00\x01")
    return tmp_path


class TestDigest:
    def test_includes_priority_and_source(self, sample_repo):
        digest, stats = build_codebase_digest(sample_repo)
        assert "PolicyAdmin" in digest                 # README content
        assert "flask==2.0" in digest                  # manifest content
        assert "PREMIUM_ROUNDING" in digest            # source excerpt
        assert stats.files_included >= 3

    def test_prunes_vendor_dirs(self, sample_repo):
        digest, _ = build_codebase_digest(sample_repo)
        assert "node_modules" not in digest
        assert "__pycache__" not in digest

    def test_withholds_secrets(self, sample_repo):
        digest, stats = build_codebase_digest(sample_repo)
        assert "sk-ant-SECRET" not in digest
        assert ".env" in stats.files_skipped_secret
        assert "Withheld files" in digest              # disclosed, not silent

    def test_skips_binaries(self, sample_repo):
        digest, _ = build_codebase_digest(sample_repo)
        assert "\x89PNG" not in digest

    def test_respects_total_budget(self, tmp_path):
        for i in range(60):
            (tmp_path / f"mod{i:02d}.py").write_text(f"# module {i}\n" + "x = 1\n" * 800)
        digest, stats = build_codebase_digest(tmp_path, max_total_bytes=20_000)
        assert len(digest) <= 20_000 + 5_000           # tree + withheld footer slack
        assert stats.truncated

    def test_per_file_cap(self, tmp_path):
        (tmp_path / "big.py").write_text("y = 2\n" * 5_000)
        digest, _ = build_codebase_digest(tmp_path)
        assert "truncated" in digest
        # the excerpt block itself is capped
        assert digest.count("y = 2") * 6 <= MAX_SOURCE_BYTES + 100

    def test_bad_paths_raise(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build_codebase_digest(tmp_path / "missing")
        f = tmp_path / "file.txt"; f.write_text("x")
        with pytest.raises(NotADirectoryError):
            build_codebase_digest(f)

    def test_deterministic(self, sample_repo):
        d1, _ = build_codebase_digest(sample_repo)
        d2, _ = build_codebase_digest(sample_repo)
        assert d1 == d2
