"""App-wide defaults, independent workspace policy, and selection changes."""

import pytest
from pyrung.validation import (
    CheckConfig,
    ValidationReport,
    load_check_config,
    ordered_rules,
    save_check_config,
)

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


def test_new_rules_follow_retained_prefix_policy():
    """The edit keeps the PTR prefix and turns the other PTR rules off by name.

    pyrung has no public way to add a rule, so this test does not add one. It checks the
    selection that a new PTR rule would meet. ``CheckConfig.resolve()`` turns on every rule
    that a kept prefix matches and that ``ignore`` does not name, so a new PTR rule would be on.
    """
    updated = update_selection(CheckConfig(select=("PTR",)), {"PTR_MAY_ESCAPE_BLOCK"})
    pointer_rules = {spec.code for spec in ordered_rules() if spec.code.startswith("PTR_")}
    assert updated.select == ("PTR",)
    assert updated.extend_select == ()
    assert set(updated.ignore) == pointer_rules - {"PTR_MAY_ESCAPE_BLOCK"}
    assert updated.resolve() == {"PTR_MAY_ESCAPE_BLOCK"}


def test_report_does_not_call_unselected_checks_passed():
    empty = format_validation_report(ValidationReport(findings=(), checked_rules=frozenset()))
    assert "no checks selected" in empty
    assert "passed" not in empty
    selected = format_validation_report(
        ValidationReport(findings=(), checked_rules=frozenset({"RUNG_CONTRADICTION"}))
    )
    assert "the 1 selected check passed" in selected
    assert "not run" in selected


# Names that pyrung does not know, such as a rule's name before pyrung renamed the rule
_OLD = '[tool.pyrung.check]\nselect = ["CMP", "OLD_RULE"]\nextend-select = ["RUNG_TAUTOLOGY"]\n'


def test_a_saved_name_that_pyrung_does_not_know_is_removed_and_reported_once(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text(
        '# keep this\n[project]\nname="mixer"\n\n'
        + _OLD
        + 'ignore = ["GONE", "CMP_ALWAYS_TRUE"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="OLD_RULE"):
        load_check_config(path)
    selection = ProgramCheckSelection(tmp_path, appdata=tmp_path / "settings")

    kept = CheckConfig(
        select=("CMP",), extend_select=("RUNG_TAUTOLOGY",), ignore=("CMP_ALWAYS_TRUE",)
    )
    assert selection.load() == kept
    # The file holds the rest of the selection, and everything else in it stays
    assert load_check_config(path) == kept
    assert "# keep this" in path.read_text(encoding="utf-8")
    assert 'name="mixer"' in path.read_text(encoding="utf-8")
    [dropped] = selection.take_dropped()
    assert (dropped.path, dropped.names) == (path, ("OLD_RULE", "GONE"))
    assert dropped.describe() == (
        f"pyrung has no checks named OLD_RULE or GONE, so ClickNick removed them from the check "
        f"selection in {path}. The other checks in the selection stay. Open Choose Checks to "
        "see which checks run."
    )
    # Said once: the file no longer holds the names
    selection.sync(tmp_path)
    assert selection.load() == kept
    assert selection.take_dropped() == ()


def test_sync_removes_an_unknown_name_from_the_app_defaults_too(tmp_path):
    appdata = tmp_path / "settings"
    appdata.mkdir()
    (appdata / "check-defaults.toml").write_text(_OLD, encoding="utf-8")
    selection = ProgramCheckSelection(appdata=appdata)

    selection.sync(tmp_path / "generated")

    kept = CheckConfig(select=("CMP",), extend_select=("RUNG_TAUTOLOGY",))
    assert load_check_config(appdata / "check-defaults.toml") == kept
    assert load_check_config(tmp_path / "generated" / "pyproject.toml") == kept
    [dropped] = selection.take_dropped()
    assert dropped.names == ("OLD_RULE",)
    assert dropped.describe().startswith("pyrung has no check named OLD_RULE, so ClickNick ")
