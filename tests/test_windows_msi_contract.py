from pathlib import Path


TEMPLATE = Path("frontend/src-tauri/wix/main.wxs")


def _source() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_webview_detection_covers_machine_and_user_installs():
    source = _source()
    key = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    assert f'Root="HKLM" Key="{key}"' in source
    assert f'Root="HKCU" Key="{key}"' in source
    assert r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients" in source
    assert source.count('Property Id="INSTALLED_WEBVIEW2_VERSION"') == 1


def test_managed_webview_switch_is_public_secure_and_fail_closed():
    source = _source()
    assert '<Property Id="DISABLEWEBVIEW2BOOTSTRAP" Secure="yes" />' in source
    assert 'DISABLEWEBVIEW2BOOTSTRAP <> "1"' in source
    assert "Evergreen Standalone Runtime" in source
    assert source.count(
        'NOT(REMOVE OR INSTALLED_WEBVIEW2_VERSION OR DISABLEWEBVIEW2BOOTSTRAP = "1")'
    ) == 3
    assert 'AND DISABLEWEBVIEW2BOOTSTRAP <> "1"' in source


def test_webview_download_and_silent_invocation_are_pinned():
    source = _source()
    assert "https://go.microsoft.com/fwlink/p/?LinkId=2124703" in source
    assert "Invoke-WebRequest" in source
    assert "Start-Process" in source
    assert "{{webview_installer_args}} &apos;/install&apos;" in source


def test_webview_action_truth_table():
    def selected(*, installed: bool, disabled: bool, removing: bool = False) -> bool:
        return not (removing or installed or disabled)

    assert not selected(installed=True, disabled=False)
    assert not selected(installed=True, disabled=True)
    assert selected(installed=False, disabled=False)
    assert not selected(installed=False, disabled=True)


def test_autolaunch_zero_is_explicitly_false():
    source = _source()
    assert 'AUTOLAUNCHAPP AND AUTOLAUNCHAPP &lt;&gt; "0" AND NOT Installed' in source
    assert '(NOT AUTOLAUNCHAPP OR AUTOLAUNCHAPP &lt;&gt; "0")' in source


def test_release_smoke_inspects_the_built_msi():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    verifier = Path("scripts/verify-windows-msi.ps1").read_text(encoding="utf-8")
    assert "verify-windows-msi.ps1" in workflow
    tables = (
        "Property",
        "InstallExecuteSequence",
        "LaunchCondition",
        "CustomAction",
        "RegLocator",
    )
    for table in tables:
        assert f"``{table}``" in verifier
