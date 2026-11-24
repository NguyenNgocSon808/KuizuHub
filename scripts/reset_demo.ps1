param()

$repositoryRoot = Split-Path -Parent $PSScriptRoot
python "$repositoryRoot/scripts/seed_db.py" --reset
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
Write-Host "Demo database recreated at $repositoryRoot/server/data/exam.db"
