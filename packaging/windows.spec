from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
datas = [
    (str(root / 'src/gui/serverpy.ui'), 'src/gui'),
    (str(root / 'src/project_info.json'), 'src'),
    (str(root / 'src/templates'), 'src/templates'),
    (str(root / 'server.svg'), '.'),
    (str(root / 'visual_identity/krakenlogo.svg'), 'visual_identity'),
    (str(root / 'LICENSE'), '.'),
    (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
    (str(root / 'share-folder/share-folder.ps1'), 'share-folder'),
    (str(root / 'vendor/findport'), 'vendor/findport'),
]
hiddenimports = []
for package in (
        'vendor.processhunter.core', 'vendor.processhunter.ui',
        'vendor.systemram.core', 'vendor.systemram.gui'):
    hiddenimports.extend(collect_submodules(package))

a = Analysis([str(root / 'src/main.py')], pathex=[str(root)], datas=datas,
             hiddenimports=hiddenimports, excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ServerPy',
          console=False, debug=False, upx=False, icon=str(root / 'packaging/serverpy.ico'))
coll = COLLECT(exe, a.binaries, a.datas, name='ServerPy', upx=False)
