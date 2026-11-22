# PyInstaller build for the FocusOs desktop app.
#
#   pip install pyinstaller
#   pyinstaller tracker/dashboard/FocusOs.spec --noconfirm     (from the repo root)
#
# Output: dist/FocusOs/FocusOs.exe plus an _internal/ folder. It is a one-folder
# build on purpose: a one-file .exe unpacks ~200 MB to a temp folder on every
# start, which makes it slow to open. scripts/make_release.ps1 copies the folder
# next to tracker/, ai/, db/ and pgsql/, which the app finds via FOCUSOS_ROOT.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

HERE = Path(SPECPATH)                 # tracker/dashboard
AI = HERE.parents[1] / "ai"

a = Analysis(
    [str(HERE / "desktop.py")],
    pathex=[str(HERE), str(AI)],      # server.py & co., and title_features for the AI model
    datas=[
        (str(HERE / "static"), "static"),
        (str(HERE / "list_installed_apps.ps1"), "."),
        (str(HERE / "focusos.ico"), "."),
    ],
    # The AI model is a pickled scikit-learn pipeline and "Retrain" imports the
    # training script; both load sklearn classes by name, which PyInstaller
    # cannot see. Bundle sklearn whole rather than guess and crash later.
    hiddenimports=collect_submodules("sklearn") + ["title_features", "title_classifier", "portable_db"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FocusOs",
    icon=str(HERE / "focusos.ico"),
    console=False,                    # a window app: no black console behind it
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FocusOs")
