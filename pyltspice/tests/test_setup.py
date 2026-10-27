"""First-run setup: finding the user's LTspice installer and extracting it from the GUI."""
import os
import time

from PySide6.QtWidgets import QDialog

from pyltspice import config, setup_lib


def test_find_installers_looks_one_level_down(tmp_path):
    (tmp_path / "dl").mkdir()
    (tmp_path / "proj" / "ltspice").mkdir(parents=True)
    a = tmp_path / "dl" / "LTspice64.msi"
    b = tmp_path / "proj" / "LTspice64.msi"
    deep = tmp_path / "proj" / "ltspice" / "LTspice64.msi"      # two levels down: not searched
    for p in (a, b, deep, tmp_path / "dl" / "other.msi"):
        p.write_bytes(b"x")
    os.utime(a, (1, 1))
    found = setup_lib.find_installers([tmp_path / "dl", tmp_path, tmp_path / "missing"])
    assert found == [b.resolve(), a.resolve()]                   # newest first


def _wait(qapp, cond, timeout=5):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


def test_setup_dialog_extracts_then_accepts(qapp, tmp_path, monkeypatch):
    from pyltspice.ui import setup_dialog
    lib = tmp_path / "lib_root"
    monkeypatch.setattr(config, "LIB_ROOT", lib)
    monkeypatch.setattr(config, "SYM_DIR", lib / "lib" / "sym")
    monkeypatch.setattr(setup_lib, "have_7z", lambda: True)
    msi = tmp_path / "LTspice64.msi"
    msi.write_bytes(b"x")
    calls = []

    def fake_extract(path, dest, log=print):
        calls.append((path, dest))
        if not calls[1:]:
            raise RuntimeError("7z failed: broken archive")
        log("Extracting lib.zip...")
        (dest / "lib" / "sym").mkdir(parents=True)
    monkeypatch.setattr(setup_lib, "extract", fake_extract)

    assert setup_dialog.library_missing()
    dlg = setup_dialog.SetupDialog(installers=[msi])
    assert dlg.msi() == msi and dlg.extract_btn.isEnabled()
    dlg.extract_btn.click()                       # first try fails: the error is shown, can retry
    _wait(qapp, lambda: not dlg.running)
    assert "broken archive" in dlg.log.text() and dlg.result() != QDialog.Accepted
    assert dlg.extract_btn.isEnabled()
    dlg.extract_btn.click()
    assert dlg.running and not dlg.later_btn.isEnabled()
    _wait(qapp, lambda: dlg.result() == QDialog.Accepted)
    assert dlg.result() == QDialog.Accepted and calls[-1] == (msi, lib)
    assert not setup_dialog.library_missing()


def test_setup_dialog_without_installer_or_7z(qapp, tmp_path, monkeypatch):
    from pyltspice.ui import setup_dialog
    monkeypatch.setattr(setup_lib, "have_7z", lambda: True)
    dlg = setup_dialog.SetupDialog(installers=[])
    assert not dlg.extract_btn.isEnabled() and "Analog Devices" in dlg.hint.text()
    dlg.combo.setEditText(str(tmp_path / "nope.msi"))
    assert not dlg.extract_btn.isEnabled() and "doesn't exist" in dlg.hint.text()
    monkeypatch.setattr(setup_lib, "have_7z", lambda: False)
    (tmp_path / "LTspice64.msi").write_bytes(b"x")
    dlg.combo.setEditText(str(tmp_path / "LTspice64.msi"))
    assert "p7zip-full" in dlg.hint.text()
