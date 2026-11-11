# Keep the command-line interface aligned with dev.sh (including --prod).
#requires -Version 5.1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-Python([string] $Executable, [string[]] $PrefixArguments = @()) {
    try {
        $version = & $Executable @PrefixArguments -c 'import sys; print(int(sys.version_info >= (3, 11) and sys.platform == ''win32''))' 2>$null
        return $LASTEXITCODE -eq 0 -and "$version" -eq '1'
    }
    catch { return $false }
}

function Add-CarrierToPath([string] $Directory) {
    $normalizedDirectory = $Directory.Replace('/', '\').TrimEnd('\')
    foreach ($scope in @('User', 'Process')) {
        $existingPath = [Environment]::GetEnvironmentVariable('Path', $scope)
        $entries = @($existingPath -split ';' | ForEach-Object {
            [Environment]::ExpandEnvironmentVariables($_.Trim().Trim('"')).Replace('/', '\').TrimEnd('\')
        })
        if ($normalizedDirectory -notin $entries) {
            $updatedPath = if ($existingPath) { "$Directory;$existingPath" } else { $Directory }
            [Environment]::SetEnvironmentVariable('Path', $updatedPath, $scope)
        }
    }
}

try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'dev.ps1 requires Windows; use dev.sh on Linux or macOS'
    }
    $pythonExecutable = $null
    $pythonArguments = @()
    $configuredPython = if ($env:AIXAND_DEV_PYTHON) { $env:AIXAND_DEV_PYTHON } else { $env:CARRIER_DEV_PYTHON }
    if ($configuredPython) {
        if (-not (Test-Python $configuredPython)) {
            throw 'CARRIER_DEV_PYTHON must name a working Windows Python 3.11+ executable'
        }
        $pythonExecutable = $configuredPython
    }
    else {
        foreach ($name in @('py', 'python', 'python3')) {
            $candidate = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($null -eq $candidate) { continue }
            $prefixArguments = if ($name -eq 'py') { @('-3') } else { @() }
            if (Test-Python $candidate.Source $prefixArguments) {
                $pythonExecutable = $candidate.Source
                $pythonArguments = $prefixArguments
                break
            }
        }
        # Use an existing uv-managed interpreter if Python is not on PATH.
        if (-not $pythonExecutable) {
            $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($null -ne $uv) {
                $candidate = & $uv.Source python find '>=3.11' 2>$null
                if ($LASTEXITCODE -eq 0 -and (Test-Python "$candidate")) {
                    $pythonExecutable = "$candidate"
                }
            }
        }
    }
    if (-not $pythonExecutable) {
        throw 'Python 3.11+ is required. Install Python or set CARRIER_DEV_PYTHON to its executable path.'
    }
    & $pythonExecutable @pythonArguments (Join-Path $PSScriptRoot 'scripts/carrier_dev.py') @args
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $productOptions = @('--artifact', '--prefix', '--product', '--scope', '--owner', '--register-path', '--command-policy')
    $isProduct = @($args | Where-Object { $_ -in $productOptions -or $_ -match '^--(artifact|prefix|product|scope|owner|command-policy)=' }).Count -gt 0
    if (-not $isProduct -and ($args -contains '--prod' -or $args -contains 'reinstall') -and
        $args -notcontains '--help' -and $args -notcontains '-h') {
        # Use Python's path resolution, including ~ and the install-dir override,
        # so PATH always points at the directory the installer actually used.
        $binDirectory = & $pythonExecutable @pythonArguments -c 'import os; from pathlib import Path; print(Path(os.environ.get(''CARRIER_DEV_INSTALL_DIR'', Path.home() / ''.local/bin'')).expanduser().resolve())'
        if ($LASTEXITCODE -ne 0) { throw 'Carrier is installed, but its command directory could not be resolved' }
        try { Add-CarrierToPath "$binDirectory" }
        catch { throw "Carrier is installed, but updating PATH failed: $($_.Exception.Message)" }
        Write-Output 'PATH is configured for this PowerShell process and future terminals. Run: carrier --help'
    }
}
catch {
    [Console]::Error.WriteLine("carrier dev installer: $($_.Exception.Message)")
    exit 1
}
