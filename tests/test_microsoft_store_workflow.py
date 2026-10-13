from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "microsoft-store.yml"


def load_workflow():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def test_store_workflow_is_manual_signed_and_distribution_scoped():
    workflow = load_workflow()
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["env"]["VOICESTUDIO_DISTRIBUTION"] == "microsoft-store"
    package = workflow["jobs"]["package"]
    build = next(
        step for step in package["steps"] if step.get("name") == "Build signed Microsoft Store installer"
    )
    assert set(build["env"]) == {"CSC_LINK", "CSC_KEY_PASSWORD"}
    assert "secrets.ELECTRON_WINDOWS_CSC_LINK" in build["env"]["CSC_LINK"]
    assert "electron-builder" in build["run"]
    assert "--publish never" in build["run"]
    for step in package["steps"]:
        if step is not build:
            assert "CSC_LINK" not in step.get("env", {})
            assert "CSC_KEY_PASSWORD" not in step.get("env", {})


def test_staging_is_owner_gated_immutable_and_does_not_submit_listing():
    workflow = load_workflow()
    guard = next(
        step
        for step in workflow["jobs"]["validate"]["steps"]
        if step.get("name") == "Validate target and publication authority"
    )
    assert 'test "$DISPATCH_ACTOR" = "$OWNER" && test "$RERUN_ACTOR" = "$OWNER"' in guard["run"]
    stage = workflow["jobs"]["stage"]
    assert stage["if"] == "inputs.stage_package_urls == true"
    stage_script = stage["steps"][-1]["run"]
    assert "Refusing to replace immutable Store package" in stage_script
    assert "--clobber" not in stage_script
    source = WORKFLOW.read_text()
    assert "store-submission-api" not in source
    assert "Partner Center submission remains owner-gated" in source


def test_store_package_records_authenticode_and_provenance_evidence():
    workflow = load_workflow()
    names = [step.get("name") for step in workflow["jobs"]["package"]["steps"]]
    assert "Verify Authenticode signatures" in names
    assert "Validate clean silent install, launch and uninstall" in names
    assert "Validate upgrade from the previous direct release" in names
    assert "Record artifact provenance" in names
    handoff = workflow["jobs"]["handoff"]
    assert any(step.get("name") == "Create Partner Center handoff" for step in handoff["steps"])
    assert any(step.get("name") == "Add canonical listing assets" for step in handoff["steps"])
