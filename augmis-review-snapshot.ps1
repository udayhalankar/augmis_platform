param(
    [string]$Output = ".\AUGMIS_REVIEW_SNAPSHOT.txt"
)

$ErrorActionPreference = "Continue"

$root = (Get-Location).Path
$exclude = '\\(\.git|\.venv|node_modules|\.next|__pycache__|data\\packages)(\\|$)'

$lines = New-Object System.Collections.Generic.List[string]

function Add-Section([string]$name) {
    $lines.Add("")
    $lines.Add(("=" * 80))
    $lines.Add($name)
    $lines.Add(("=" * 80))
}

$lines.Add("AUGMIS REVIEW SNAPSHOT")
$lines.Add("Generated: $(Get-Date -Format o)")
$lines.Add("Root: $root")

Add-Section "GIT"
$lines.Add("Branch:")
$lines.AddRange([string[]](& git branch --show-current 2>&1))
$lines.Add("")
$lines.Add("Status:")
$lines.AddRange([string[]](& git status --short 2>&1))
$lines.Add("")
$lines.Add("Remote:")
$lines.AddRange([string[]](& git remote -v 2>&1))
$lines.Add("")
$lines.Add("Latest commits:")
$lines.AddRange([string[]](& git log -10 --oneline --decorate 2>&1))
$lines.Add("")
$lines.Add(".env tracked?")
$trackedEnv = & git ls-files .env 2>&1
if ($trackedEnv) {
    $lines.AddRange([string[]]$trackedEnv)
} else {
    $lines.Add("NO")
}

Add-Section "ALEMBIC"
$lines.Add("Current:")
$lines.AddRange([string[]](& alembic current 2>&1))
$lines.Add("")
$lines.Add("Heads:")
$lines.AddRange([string[]](& alembic heads 2>&1))

Add-Section "PROJECT FILES"
Get-ChildItem -Recurse -File |
    Where-Object { $_.FullName -notmatch $exclude } |
    ForEach-Object {
        $relative = $_.FullName.Substring($root.Length).TrimStart('\')
        $lines.Add($relative)
    }

Add-Section "PHASE 4 KEY FILES"
$patterns = @(
    "services\api\app\models\iam.py",
    "services\api\app\models\email_delivery.py",
    "services\api\app\routes\invitations.py",
    "services\api\app\routes\tenant_users.py",
    "services\api\app\routes\memberships.py",
    "services\api\app\routes\webhooks.py",
    "services\api\app\services\authorization_service.py",
    "services\api\app\services\invitation_service.py",
    "services\api\app\services\tenant_user_service.py",
    "services\api\app\services\membership_service.py",
    "services\api\app\services\email_delivery_service.py",
    "apps\web\src\app\users\page.tsx",
    "apps\web\src\lib\tenant-users.ts",
    "apps\web\src\lib\invitations.ts",
    "tools\seed_rbac.py"
)

foreach ($p in $patterns) {
    if (Test-Path $p) {
        $lines.Add("FOUND   $p")
    } else {
        $lines.Add("MISSING $p")
    }
}

$lines | Set-Content -Path $Output -Encoding UTF8

Write-Host "Created $Output"
Write-Host "Review it before uploading. It intentionally excludes .env contents."
