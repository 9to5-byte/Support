# rebuild_support.ps1  (repo root)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# 1) Clean per-project index folders (ignore if missing)
@(
  'SUPPORT\index\revenue',
  'SUPPORT\index\regard_depend',
  'SUPPORT\index\dependq',
  'SUPPORT\index\hubble'
) | ForEach-Object {
  Remove-Item -Recurse -Force $_ -ErrorAction SilentlyContinue
}

# 2) Rebuild all (force = fresh BM25 + FAISS from converted/*.txt)
python .\SUPPORT\build\build_dependq.py --all --force
python .\SUPPORT\build\build_hubble.py --all --force
python .\SUPPORT\build\build_regard.py --all --force
python .\SUPPORT\build\build_revenue.py --all --force
Write-Host "`n[OK] Rebuilt all support indices." -ForegroundColor Green