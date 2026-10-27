import os

import pytest

import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# keep the user's real settings (shortcuts, colours, recent files) out of the tests
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="pyltspice-test-config-")
# and never write autosave copies (ui/autosave.py) where a real TuxSpice would offer them
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="pyltspice-test-state-")

from pyltspice import config  # noqa: E402

needs_lib = pytest.mark.skipif(not config.SYM_DIR.is_dir(),
                               reason="LTspice library not extracted (scripts/extract_msi.py)")
needs_ngspice = pytest.mark.skipif(not config.ngspice_path(), reason="ngspice not installed")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
