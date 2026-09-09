"""App-wide defaults, independent workspace policy, and selection changes."""

import pytest
from pyrung.core.validation import ValidationReport
from pyrung.core.validation.config import CheckConfig, load_check_config, save_check_config
from pyrung.core.validation.registry import RULES, RuleSpec

from clicknick.services.program_check import format_validation_report
from clicknick.services.program_check_selection import ProgramCheckSelection, update_selection


def test_programs_without_workspaces_share_live_app_defaults(tmp_path):
    selection = ProgramCheckSelection(appdata=tmp_path / "appdata")
    other = ProgramCheckSelection(appdata=tmp_path / "appdata")
    assert selection.load() == CheckConfig()
    config = CheckConfig(select=("PTR",), ignore=("PTR_UNGUARDED_ACCESS",))
    selection.save(config)
    other.sync(tmp_path / "generated")
    assert other.load() == config
    assert load_check_config(tmp_path / "generated" / "pyproject.toml") == config
    other.save(CheckConfig(select=()))
    assert selection.load() == CheckConfig(select=())
    selection.sync(tmp_path / "generated")
    assert load_check_config(tmp_path / "generated" / "pyproject.toml") == CheckConfig(select=())
    assert selection.path == tmp_path / "appdata" / "check-defaults.toml"


def test_workspace_adopts_fallback_once_then_owns_its_policy(tmp_path):
    appdata, workspace = tmp_path / "settings", tmp_path / "workspace"
    temporary = ProgramCheckSelection(appdata=appdata)
    temporary.save(CheckConfig(select=("PTR",)))
    permanent = ProgramCheckSelection(workspace, appdata=appdata)
    permanent.sync(workspace)
    assert permanent.load() == temporary.load()
    permanent.save(CheckConfig(select=()))
    temporary.save(CheckConfig(select=("ALL",)))
    permanent.sync(workspace)
    assert permanent.load() == CheckConfig(select=())
    assert load_check_config(workspace / "pyproject.toml") == CheckConfig(select=())
    assert temporary.load() == CheckConfig(select=("ALL",))


def test_workspace_policy_is_preserved_and_invalid_policy_is_reported(tmp_path):
    path = tmp_path / "pyproject.toml"
    save_check_config(path, CheckConfig(extend_select=("CMP",)))
    selection = ProgramCheckSelection(tmp_path, appdata=tmp_path / "settings")
    selection.sync(tmp_path)
    assert selection.load() == CheckConfig(extend_select=("CMP",))
    path.write_text('[tool.pyrung.check]\nselect="PTR"', encoding="utf-8")
    with pytest.raises(ValueError, match="array"):
        selection.load()


def test_seeding_workspace_preserves_other_settings_and_prefixes(tmp_path):
    appdata, workspace = tmp_path / "settings", tmp_path / "workspace"
    defaults = ProgramCheckSelection(appdata=appdata)
    defaults.save(CheckConfig(extend_select=("CMP",), ignore=("CMP_STATIC_ON_LEFT",)))
    workspace.mkdir()
    path = workspace / "pyproject.toml"
    path.write_text('# keep this\n[project]\nname="mixer"\n', encoding="utf-8")
    selection = ProgramCheckSelection(workspace, appdata=appdata)
    selection.sync(workspace)
    assert selection.load() == defaults.load()
    assert "# keep this" in path.read_text(encoding="utf-8")
    assert 'name="mixer"' in path.read_text(encoding="utf-8")
    defaults.save(CheckConfig(select=()))
    selection.sync(workspace)
    assert selection.load().extend_select == ("CMP",)


@pytest.mark.parametrize(
    "config",
    [
        CheckConfig(),
        CheckConfig(select=("ALL",)),
        CheckConfig(select=("PTR",), ignore=("PTR_UNGUARDED_ACCESS",)),
    ],
)
def test_selection_edit_preserves_prefixes_and_matches_requested_checks(config):
    enabled = (config.resolve() - {"PTR_DEFAULT_BEFORE_BLOCK_START"}) | {"CMP_ALWAYS_TRUE"}
    updated = update_selection(config, set(enabled))
    assert updated.resolve() == enabled
    assert updated.select == config.select
    assert update_selection(updated, set(updated.resolve())) == updated


def test_new_rules_follow_retained_prefix_policy(monkeypatch):
    updated = update_selection(CheckConfig(select=("PTR",)), {"PTR_MAY_ESCAPE_BLOCK"})
    monkeypatch.setitem(
        RULES,
        "PTR_FUTURE",
        RuleSpec("PTR_FUTURE", "PTR", "warning", "pointer", "Future pointer rule"),
    )
    assert updated.resolve() == {"PTR_MAY_ESCAPE_BLOCK", "PTR_FUTURE"}


def test_report_does_not_call_unselected_checks_passed():
    empty = format_validation_report(ValidationReport(findings=(), checked_rules=frozenset()))
    assert "no checks selected" in empty
    assert "passed" not in empty
    selected = format_validation_report(
        ValidationReport(findings=(), checked_rules=frozenset({"RUNG_CONTRADICTION"}))
    )
    assert "1 selected checks passed" in selected
    assert "not run" in selected
