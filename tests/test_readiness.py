"""Readiness gate: config block, install, instructions, and the bundled launcher."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dsagt import readiness as rd

LAUNCHER = (
    Path(__file__).parent.parent
    / "src"
    / "dsagt"
    / "codes"
    / "aidrin"
    / "scripts"
    / "aidrin.py"
)


class TestConfigBlock:

    def test_defaults_to_shared_install_path(self):
        block = rd.readiness_block("aidrin")
        assert block == {
            "tool": "aidrin",
            "executable": str(rd.AIDRIN_EXECUTABLE),
            "profile": "quality",
        }

    def test_explicit_executable_and_profile(self, tmp_path):
        block = rd.readiness_block(
            "aidrin", executable=tmp_path / "aidrin", profile="supervised"
        )
        assert block["executable"] == str(tmp_path / "aidrin")
        assert block["profile"] == "supervised"

    def test_rejects_unknown_tool_or_profile(self):
        with pytest.raises(ValueError):
            rd.readiness_block("nope")
        with pytest.raises(ValueError):
            rd.readiness_block("aidrin", profile="nope")


class TestEnsureAidrin:

    def test_skips_when_installed(self, tmp_path, monkeypatch):
        exe = tmp_path / "aidrin" / "bin" / "aidrin"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: pytest.fail("must not run uv")
        )
        assert rd.ensure_aidrin(tmp_path / "aidrin") == exe

    def test_runs_venv_then_pip(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(rd.shutil, "which", lambda name: "/usr/bin/uv")
        install = tmp_path / "aidrin"
        assert rd.ensure_aidrin(install) == install / "bin" / "aidrin"
        assert calls[0][:2] == ["uv", "venv"] and calls[0][-1] == str(install)
        assert calls[1][:3] == ["uv", "pip", "install"]
        assert calls[1][-1] == rd.AIDRIN_SPEC

    def test_failure_raises_with_stderr_and_cleans_up(self, tmp_path, monkeypatch):
        install = tmp_path / "aidrin"

        def fake_run(cmd, **kw):
            install.mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(cmd, 1, "", "no network")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(rd.shutil, "which", lambda name: "/usr/bin/uv")
        with pytest.raises(RuntimeError, match="no network"):
            rd.ensure_aidrin(install)
        assert not install.exists()


class TestInstructionsBlock:

    def test_carries_marker_profile_and_metrics(self):
        text = rd.instructions_block(rd.readiness_block("aidrin", profile="quality"))
        assert rd.READINESS_MARKER in text
        assert "`quality`: completeness, duplicity, outliers" in text
        assert "audit/step_N_pre.aidrin.json" in text
        # The marker must not collide with the master-instructions marker.
        assert "DSAgt Pipeline Builder" not in text


# ---------------------------------------------------------------------------
# The bundled launcher, driven end-to-end with a fake ``aidrin`` executable.
# ---------------------------------------------------------------------------

FAKE_AIDRIN = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[0] == "run":
    print(json.dumps({"metric": args[1], "file": args[2], "extra": args[3:]}))
elif args[0] == "list":
    print(json.dumps({"data-quality": []}))
else:
    sys.exit("unknown")
"""


@pytest.fixture
def project(tmp_path):
    """A project dir with a readiness block pointing at a fake aidrin."""
    exe = tmp_path / "fake-aidrin"
    exe.write_text(FAKE_AIDRIN)
    exe.chmod(0o755)
    pdir = tmp_path / "proj"
    (pdir / ".dsagt").mkdir(parents=True)
    (pdir / ".dsagt" / "config.yaml").write_text(
        "project: p\nagent: claude\nreadiness:\n  tool: aidrin\n"
        f"  executable: {exe}\n  profile: quality\n"
    )
    (pdir / "data.csv").write_text("a\n1\n")
    return pdir


def run_launcher(pdir: Path, *args: str, env: dict | None = None):
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        cwd=pdir,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


class TestLauncher:

    def test_gate_runs_profile_and_writes_report(self, project):
        proc = run_launcher(
            project, "gate", "data.csv", "--report", "audit/step_1_pre.aidrin.json"
        )
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert list(report["metrics"]) == ["completeness", "duplicity", "outliers"]
        assert report["metrics"]["outliers"]["file"] == "data.csv"
        on_disk = json.loads((project / "audit" / "step_1_pre.aidrin.json").read_text())
        assert on_disk == report

    def test_supervised_profile_passes_column_arguments(self, project):
        proc = run_launcher(
            project,
            "gate",
            "data.csv",
            "--profile",
            "supervised",
            "--target",
            "label",
            "--numerical",
            "a,b",
        )
        assert proc.returncode == 0, proc.stderr
        metrics = json.loads(proc.stdout)["metrics"]
        assert metrics["class-imbalance"]["extra"] == ["label"]
        assert metrics["feature-relevance"]["extra"] == ["", "a,b", "label"]

    def test_supervised_without_target_fails_clearly(self, project):
        proc = run_launcher(project, "gate", "data.csv", "--profile", "supervised")
        assert proc.returncode != 0
        assert "requires --target" in proc.stderr

    def test_passthrough_and_report(self, project):
        proc = run_launcher(project, "--report", "audit/list.json", "list")
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == {"data-quality": []}
        assert (project / "audit" / "list.json").exists()

    def test_env_override_wins_over_config(self, project, tmp_path):
        other = tmp_path / "other-aidrin"
        other.write_text(FAKE_AIDRIN.replace('"data-quality"', '"env"'))
        other.chmod(0o755)
        proc = run_launcher(project, "list", env={"DSAGT_AIDRIN_BIN": str(other)})
        assert json.loads(proc.stdout) == {"env": []}

    def test_missing_config_fails_clearly(self, tmp_path):
        proc = run_launcher(tmp_path, "list")
        assert proc.returncode != 0
        assert "DSAGT_AIDRIN_BIN" in proc.stderr
