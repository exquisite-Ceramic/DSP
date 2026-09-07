param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("offline", "positive", "partial_commit")]
    [string]$Scenario,

    [switch]$ConfirmedRestoredFixture
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    Write-Host "> $FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "COMMAND_FAILED: $FilePath 退出码为 $LASTEXITCODE。"
    }
}

function Get-RequiredEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "ENVIRONMENT_MISSING: 缺少必需环境变量 $Name。"
    }
    return $value
}

function Assert-FixtureSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedHash,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "FIXTURE_NOT_FOUND: $Label fixture 不存在：$Path"
    }

    if ($ExpectedHash -notmatch '^[0-9a-fA-F]{64}$') {
        throw "FIXTURE_HASH_INVALID: $Label expected SHA-256 不是 64 位十六进制。"
    }

    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    $expectedNormalized = $ExpectedHash.ToLowerInvariant()
    if ($actualHash -ne $expectedNormalized) {
        throw "FIXTURE_HASH_MISMATCH: $Label fixture SHA-256 不匹配。expected=$expectedNormalized actual=$actualHash"
    }

    Write-Host "$Label fixture SHA-256 OK: $actualHash"
}

function Invoke-OfflineGate {
    $env:DSP_PHASE_I_LIVE = "0"
    Write-Host "运行 Phase I wrapper/Task16 离线契约门。"
    Invoke-CheckedCommand -FilePath "python" -Arguments @(
        "-m", "pytest",
        "tests/integration/test_phase_i_live_acceptance_script.py",
        "tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py",
        "-q", "-vv"
    )

    Write-Host "运行 Revit Core 回归。"
    Invoke-CheckedCommand -FilePath "dotnet" -Arguments @(
        "test",
        "hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj"
    )
}

function Assert-LivePreflight {
    if (-not $IsWindows) {
        throw "LIVE_WINDOWS_REQUIRED: 真实 AutoCAD + Revit 验收必须在 Windows 上运行。"
    }

    if ($env:DSP_PHASE_I_LIVE -ne "1") {
        throw "LIVE_GATE_DISABLED: 真实验收要求 DSP_PHASE_I_LIVE=1。"
    }

    $requiredNames = @(
        "DSP_AUTOCAD_ENDPOINT",
        "DSP_AUTOCAD_DOCUMENT_REF",
        "DSP_AUTOCAD_FIXTURE_PATH",
        "DSP_AUTOCAD_FIXTURE_SHA256",
        "DSP_AUTOCAD_NATIVE_ID",
        "DSP_AUTOCAD_HOST_INSTANCE_ID",
        "DSP_REVIT_LIVE_PIPE",
        "DSP_REVIT_LIVE_DOCUMENT_REF",
        "DSP_REVIT_LIVE_FIXTURE_PATH",
        "DSP_REVIT_LIVE_FIXTURE_SHA256",
        "DSP_REVIT_LIVE_WALL_UNIQUE_ID",
        "DSP_REVIT_LIVE_HOST_INSTANCE_ID",
        "DSP_REVIT_LIVE_VERSION",
        "DSP_REVIT_LIVE_TFM",
        "DSP_REVIT_LIVE_API_DIR",
        "DSP_PHASE_I_SEMANTIC_ID"
    )

    foreach ($name in $requiredNames) {
        [void](Get-RequiredEnvironmentValue -Name $name)
    }

    if ($env:DSP_REVIT_LIVE_VERSION -ne "2027") {
        throw "REVIT_VERSION_MISMATCH: DSP_REVIT_LIVE_VERSION 必须为 2027。"
    }
    if ($env:DSP_REVIT_LIVE_TFM -ne "net10.0-windows") {
        throw "REVIT_TFM_MISMATCH: DSP_REVIT_LIVE_TFM 必须为 net10.0-windows。"
    }

    Assert-FixtureSha256 `
        -Path $env:DSP_AUTOCAD_FIXTURE_PATH `
        -ExpectedHash $env:DSP_AUTOCAD_FIXTURE_SHA256 `
        -Label "AutoCAD"
    Assert-FixtureSha256 `
        -Path $env:DSP_REVIT_LIVE_FIXTURE_PATH `
        -ExpectedHash $env:DSP_REVIT_LIVE_FIXTURE_SHA256 `
        -Label "Revit"
}

function Build-Revit2027AgentHost {
    $project = Join-Path $RepoRoot "hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj"
    if (-not (Test-Path -LiteralPath $project -PathType Leaf)) {
        throw "REVIT_PROJECT_NOT_FOUND: $project"
    }

    # 冻结构建参数等价于：DspRevitVersion=\"2027\"，DspRevitTargetFramework=\"net10.0-windows\"。
    Invoke-CheckedCommand -FilePath "dotnet" -Arguments @(
        "build",
        $project,
        "-p:DspRevitVersion=2027",
        "-p:DspRevitTargetFramework=net10.0-windows",
        "-p:DspRevitApiDir=$($env:DSP_REVIT_LIVE_API_DIR)"
    )
}

function Invoke-PositiveScenario {
    $env:DSP_PHASE_I_SCENARIO = "positive"
    Write-Host "运行真实 positive：AutoCAD 200 mm -> 300 mm，随后 Revit 200 mm -> 300 mm。"
    Invoke-CheckedCommand -FilePath "python" -Arguments @(
        "-m", "pytest",
        "tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py",
        "-k", "real_positive_wall_thickness_acceptance",
        "-q", "-vv", "-s"
    )
    Write-Host "positive 完成后：关闭 AutoCAD/Revit 受控文档，选择 DO NOT SAVE，再重新打开原始 fixture。"
}

function Invoke-PartialCommitScenario {
    if (-not $ConfirmedRestoredFixture) {
        throw "FIXTURE_RESTORE_CONFIRMATION_REQUIRED: 先关闭两个受控文档并选择 DO NOT SAVE，重新打开原始 fixture，确认两边墙厚都是 200 mm，然后使用 -ConfirmedRestoredFixture 重跑。"
    }

    $env:DSP_PHASE_I_SCENARIO = "partial_commit"
    Write-Host "已声明 fixture 完成 DO NOT SAVE -> 重新打开 -> 200 mm 恢复；继续执行 partial_commit。"
    Invoke-CheckedCommand -FilePath "python" -Arguments @(
        "-m", "pytest",
        "tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py",
        "-k", "real_revit_post_readiness_race_is_partial_commit",
        "-q", "-vv", "-s"
    )
    Write-Host "partial_commit 完成后同样关闭受控文档并选择 DO NOT SAVE。"
}

Push-Location $RepoRoot
try {
    if ($Scenario -eq "offline") {
        Invoke-OfflineGate
        exit 0
    }

    Assert-LivePreflight
    Build-Revit2027AgentHost

    if ($Scenario -eq "positive") {
        Invoke-PositiveScenario
        exit 0
    }

    Invoke-PartialCommitScenario
}
finally {
    Pop-Location
}
