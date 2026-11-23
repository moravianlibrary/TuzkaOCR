function Install-TuzkaOCR {
    $ErrorActionPreference = 'Continue'
    $repo = 'moravianlibrary/TuzkaOCR'
    $pythonRequest = 'cpython-3.13-windows-x86_64-none'
    $docs = 'https://moravianlibrary.github.io/TuzkaOCR'

    function Fail([string]$message) {
        Write-Host ''
        Write-Host "TuzkaOCR install failed: $message" -ForegroundColor Red
        Write-Host "Help: $docs/troubleshooting/"
        throw 'TuzkaOCR install failed.'
    }

    function Find-Uv {
        $cmd = Get-Command uv -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
        $dirs = @()
        if ($env:XDG_BIN_HOME) { $dirs += $env:XDG_BIN_HOME }
        $dirs += (Join-Path $env:USERPROFILE '.local\bin')
        if ($env:CARGO_HOME) { $dirs += (Join-Path $env:CARGO_HOME 'bin') }
        $dirs += (Join-Path $env:USERPROFILE '.cargo\bin')
        foreach ($dir in $dirs) {
            $candidate = Join-Path $dir 'uv.exe'
            if (Test-Path $candidate) { return $candidate }
        }
        return $null
    }

    function Get-LatestTag {
        $request = [System.Net.HttpWebRequest]::Create("https://github.com/$repo/releases/latest")
        $request.Method = 'HEAD'
        $request.AllowAutoRedirect = $false
        $request.UserAgent = 'TuzkaOCR-installer'
        $response = $request.GetResponse()
        try { $location = $response.Headers['Location'] } finally { $response.Close() }
        if (-not $location) { return '' }
        return ($location -split '/')[-1]
    }

    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $uv = Find-Uv
    if (-not $uv) {
        Write-Host 'Installing uv, the tool that installs TuzkaOCR and its Python...'
        & powershell -NoProfile -ExecutionPolicy ByPass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        if ($LASTEXITCODE -ne 0) { Fail 'uv could not be installed.' }
        $uv = Find-Uv
        if (-not $uv) { Fail 'uv was installed but cannot be found. Open a new window and run this line again.' }
    }

    $tag = $env:TUZKAOCR_VERSION
    if (-not $tag) {
        try { $tag = Get-LatestTag } catch { Fail 'could not reach GitHub to find the latest TuzkaOCR release.' }
    }
    if ($tag -notmatch '^v[0-9]') { Fail "could not find the latest TuzkaOCR release (got '$tag')." }

    & $uv tool update-shell *> $null
    $bin = (& $uv tool dir --bin).Trim()
    $env:Path = "$bin;$env:Path"

    Write-Host "Installing TuzkaOCR $tag. This downloads a few hundred megabytes and takes a few minutes..."
    & $uv tool install --force --python $pythonRequest "https://github.com/$repo/archive/refs/tags/$tag.zip"
    if ($LASTEXITCODE -ne 0) { Fail "uv could not install TuzkaOCR $tag." }

    & (Join-Path $bin 'tuzkaocr.exe') --help *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'TuzkaOCR was installed but does not start.' }

    Write-Host ''
    Write-Host "TuzkaOCR $tag is installed." -ForegroundColor Green
    Write-Host 'Close this window, open a new one, and type:  tuzkaocr --help'
}

try {
    Install-TuzkaOCR
} catch {
    if ($_.Exception.Message -ne 'TuzkaOCR install failed.') { throw }
}
