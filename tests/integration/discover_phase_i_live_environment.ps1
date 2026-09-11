param(
    [string]$AutoCadFixturePath,
    [string]$RevitFixturePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "WINDOWS_REQUIRED: Phase I 真实 Host 环境探测只支持 Windows。"
}

$results = [System.Collections.Generic.List[object]]::new()

function Add-Result {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Status,

        [AllowEmptyString()]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [string]$Source,

        [AllowEmptyString()]
        [string]$Note = ""
    )

    [void]$results.Add([pscustomobject]@{
        Name = $Name
        Status = $Status
        Value = $Value
        Source = $Source
        Note = $Note
    })
}

function Add-DetectedValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [string]$Source
    )

    Add-Result -Name $Name -Status "DETECTED" -Value $Value -Source $Source
}

function Add-ManualValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Reason
    )

    $existing = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($existing)) {
        Add-Result `
            -Name $Name `
            -Status "EXISTING" `
            -Value $existing `
            -Source "当前进程环境" `
            -Note "脚本无法独立验证该身份，只原样显示已有值。"
        return
    }

    Add-Result `
        -Name $Name `
        -Status "MANUAL_REQUIRED" `
        -Value "" `
        -Source "人工确认" `
        -Note $Reason
}

function Add-PipeValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Processes,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$PipeNames,

        [Parameter(Mandatory = $true)]
        [scriptblock]$ExpectedNameFactory,

        [Parameter(Mandatory = $true)]
        [string]$HostLabel
    )

    $matches = @()
    foreach ($process in $Processes) {
        $expected = & $ExpectedNameFactory $process
        if ($PipeNames -contains $expected) {
            $matches += [pscustomobject]@{
                Pipe = $expected
                ProcessId = $process.Id
                Window = $process.MainWindowTitle
            }
        }
    }

    if ($matches.Count -eq 1) {
        $match = $matches[0]
        Add-DetectedValue `
            -Name $Name `
            -Value $match.Pipe `
            -Source "$HostLabel PID=$($match.ProcessId) 的实际 Named Pipe"
        return
    }

    $existing = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($existing)) {
        Add-Result `
            -Name $Name `
            -Status "EXISTING" `
            -Value $existing `
            -Source "当前进程环境" `
            -Note "未能唯一匹配活动 $HostLabel pipe；只读 Host probe 成功后才会升级为 DETECTED。"
        return
    }

    if ($matches.Count -gt 1) {
        $candidateText = ($matches | ForEach-Object { $_.Pipe }) -join ", "
        Add-Result `
            -Name $Name `
            -Status "MANUAL_REQUIRED" `
            -Value "" `
            -Source "Named Pipe 探测" `
            -Note "发现多个 $HostLabel AgentHost pipe：$candidateText。请按目标文档对应的进程选择。"
        return
    }

    Add-Result `
        -Name $Name `
        -Status "MANUAL_REQUIRED" `
        -Value "" `
        -Source "Named Pipe 探测" `
        -Note "没有发现与活动 $HostLabel 进程匹配的 AgentHost pipe；请确认插件已加载。"
}

function Add-FixtureValues {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathName,

        [Parameter(Mandatory = $true)]
        [string]$HashName,

        [AllowEmptyString()]
        [string]$ExplicitPath,

        [Parameter(Mandatory = $true)]
        [string]$HostLabel
    )

    $candidate = $ExplicitPath
    $source = "脚本参数"
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = [Environment]::GetEnvironmentVariable($PathName)
        $source = "当前进程环境"
    }

    if ([string]::IsNullOrWhiteSpace($candidate)) {
        Add-Result `
            -Name $PathName `
            -Status "MANUAL_REQUIRED" `
            -Value "" `
            -Source "fixture 路径" `
            -Note "无法从进程可靠推断 $HostLabel 当前受控 fixture 的绝对路径；可用脚本参数显式提供。"
        Add-Result `
            -Name $HashName `
            -Status "MANUAL_REQUIRED" `
            -Value "" `
            -Source "fixture SHA-256" `
            -Note "提供有效 fixture 路径后脚本才能计算 SHA-256。"
        return
    }

    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        Add-Result `
            -Name $PathName `
            -Status "MANUAL_REQUIRED" `
            -Value "" `
            -Source $source `
            -Note "$HostLabel fixture 路径不存在或不是文件：$candidate"
        Add-Result `
            -Name $HashName `
            -Status "MANUAL_REQUIRED" `
            -Value "" `
            -Source "fixture SHA-256" `
            -Note "fixture 文件不可访问，不能计算 SHA-256。"
        return
    }

    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolved).Hash.ToLowerInvariant()
    Add-DetectedValue -Name $PathName -Value $resolved -Source $source
    Add-DetectedValue -Name $HashName -Value $digest -Source "$HostLabel fixture 实际字节 SHA-256"
}

function Get-UsableResultValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $item = $results |
        Where-Object { $_.Name -eq $Name -and ($_.Status -eq "DETECTED" -or $_.Status -eq "EXISTING") } |
        Select-Object -Last 1
    if ($null -eq $item) {
        return ""
    }
    return [string]$item.Value
}

function Invoke-IdentityProbe {
    param(
        [AllowEmptyString()]
        [string]$AutoCadEndpoint,

        [AllowEmptyString()]
        [string]$RevitPipe
    )

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        Write-Host "identity probe 跳过：当前 PATH 中没有 python。"
        return $null
    }

    $probePath = Join-Path $PSScriptRoot "probe_phase_i_live_identity.py"
    if (-not (Test-Path -LiteralPath $probePath -PathType Leaf)) {
        Write-Host "identity probe 跳过：脚本不存在 $probePath"
        return $null
    }

    $arguments = @($probePath)
    if (-not [string]::IsNullOrWhiteSpace($AutoCadEndpoint)) {
        $arguments += @("--autocad-endpoint", $AutoCadEndpoint)
    }
    if (-not [string]::IsNullOrWhiteSpace($RevitPipe)) {
        $arguments += @("--revit-pipe", $RevitPipe)
    }

    $raw = & $python.Source @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "identity probe 失败：$($raw | Out-String)"
        return $null
    }

    try {
        return (($raw | Out-String).Trim() | ConvertFrom-Json)
    }
    catch {
        Write-Host "identity probe 输出不是有效 JSON：$($raw | Out-String)"
        return $null
    }
}

function Confirm-PipeFromProbe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$HostLabel,

        $HostProbe
    )

    if ($null -eq $HostProbe -or $HostProbe.ok -ne $true) {
        return
    }
    $item = $results | Where-Object { $_.Name -eq $Name } | Select-Object -Last 1
    if ($null -ne $item -and -not [string]::IsNullOrWhiteSpace([string]$item.Value)) {
        $item.Status = "DETECTED"
        $item.Source = "$HostLabel 只读 Host probe"
        $item.Note = "Named Pipe 已通过真实只读请求验证。"
    }
}

function Add-ProbeIdentityValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$HostLabel,

        $HostProbe,

        [Parameter(Mandatory = $true)]
        [string]$FallbackReason
    )

    if ($null -ne $HostProbe -and $HostProbe.ok -eq $true) {
        $property = $HostProbe.values.PSObject.Properties[$Name]
        if ($null -ne $property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            Add-DetectedValue -Name $Name -Value ([string]$property.Value) -Source "$HostLabel 只读 Host probe"
            return
        }
    }

    $detail = $FallbackReason
    if ($null -ne $HostProbe) {
        $code = [string]$HostProbe.code
        $message = [string]$HostProbe.message
        if (-not [string]::IsNullOrWhiteSpace($code) -or -not [string]::IsNullOrWhiteSpace($message)) {
            $detail = "$detail Probe=$code $message"
        }
    }
    $existing = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($existing)) {
        $detail = "$detail 当前环境已有值 '$existing'，但未被本次只读 probe 验证，因此不自动采纳。"
    }
    Add-Result -Name $Name -Status "MANUAL_REQUIRED" -Value "" -Source "$HostLabel identity probe" -Note $detail
}

$pipeNames = @(
    Get-ChildItem -LiteralPath "\\.\pipe\" -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Name }
)
$acadProcesses = @(Get-Process -Name "acad" -ErrorAction SilentlyContinue)
$revitProcesses = @(Get-Process -Name "Revit" -ErrorAction SilentlyContinue)

Write-Output "Phase I 真实双 Host 环境只读探测"
Write-Output "机器: $env:COMPUTERNAME"
Write-Output "AutoCAD 进程: $($acadProcesses.Count)"
foreach ($process in $acadProcesses) {
    Write-Output "  acad PID=$($process.Id) Window=$($process.MainWindowTitle)"
}
Write-Output "Revit 进程: $($revitProcesses.Count)"
foreach ($process in $revitProcesses) {
    Write-Output "  Revit PID=$($process.Id) Window=$($process.MainWindowTitle)"
}
Write-Output ""

Add-DetectedValue -Name "DSP_PHASE_I_LIVE" -Value "1" -Source "Task16 真实验收固定值"

Add-PipeValue `
    -Name "DSP_AUTOCAD_ENDPOINT" `
    -Processes $acadProcesses `
    -PipeNames $pipeNames `
    -ExpectedNameFactory { param($process) "EnterpriseDesignAgent.$env:COMPUTERNAME-$($process.Id)" } `
    -HostLabel "AutoCAD"
Add-PipeValue `
    -Name "DSP_REVIT_LIVE_PIPE" `
    -Processes $revitProcesses `
    -PipeNames $pipeNames `
    -ExpectedNameFactory { param($process) "EnterpriseDesignAgent.Revit.$env:COMPUTERNAME-$($process.Id)" } `
    -HostLabel "Revit"

$autocadEndpoint = Get-UsableResultValue -Name "DSP_AUTOCAD_ENDPOINT"
$revitPipe = Get-UsableResultValue -Name "DSP_REVIT_LIVE_PIPE"
$identity = Invoke-IdentityProbe -AutoCadEndpoint $autocadEndpoint -RevitPipe $revitPipe
$autocadIdentity = if ($null -ne $identity) { $identity.autocad } else { $null }
$revitIdentity = if ($null -ne $identity) { $identity.revit } else { $null }
Confirm-PipeFromProbe -Name "DSP_AUTOCAD_ENDPOINT" -HostLabel "AutoCAD" -HostProbe $autocadIdentity
Confirm-PipeFromProbe -Name "DSP_REVIT_LIVE_PIPE" -HostLabel "Revit" -HostProbe $revitIdentity

Add-ProbeIdentityValue `
    -Name "DSP_AUTOCAD_DOCUMENT_REF" `
    -HostLabel "AutoCAD" `
    -HostProbe $autocadIdentity `
    -FallbackReason "请在 AutoCAD 中打开受控 DWG，并只选中 1 个 LWPOLYLINE 墙体。"
Add-FixtureValues `
    -PathName "DSP_AUTOCAD_FIXTURE_PATH" `
    -HashName "DSP_AUTOCAD_FIXTURE_SHA256" `
    -ExplicitPath $AutoCadFixturePath `
    -HostLabel "AutoCAD"
Add-ProbeIdentityValue `
    -Name "DSP_AUTOCAD_NATIVE_ID" `
    -HostLabel "AutoCAD" `
    -HostProbe $autocadIdentity `
    -FallbackReason "目标 native handle 必须来自当前唯一选中的受控 LWPOLYLINE。"
Add-ProbeIdentityValue `
    -Name "DSP_AUTOCAD_HOST_INSTANCE_ID" `
    -HostLabel "AutoCAD" `
    -HostProbe $autocadIdentity `
    -FallbackReason "Host instance id 必须来自当前 AgentHost 的 normalized facts。"

Add-ProbeIdentityValue `
    -Name "DSP_REVIT_LIVE_DOCUMENT_REF" `
    -HostLabel "Revit" `
    -HostProbe $revitIdentity `
    -FallbackReason "请在 Revit 中打开受控 RVT，并只选中 1 个 Wall。"
Add-FixtureValues `
    -PathName "DSP_REVIT_LIVE_FIXTURE_PATH" `
    -HashName "DSP_REVIT_LIVE_FIXTURE_SHA256" `
    -ExplicitPath $RevitFixturePath `
    -HostLabel "Revit"
Add-ProbeIdentityValue `
    -Name "DSP_REVIT_LIVE_WALL_UNIQUE_ID" `
    -HostLabel "Revit" `
    -HostProbe $revitIdentity `
    -FallbackReason "必须由 Revit 当前唯一选中 Wall 返回 persistent Element.UniqueId。"
Add-ProbeIdentityValue `
    -Name "DSP_REVIT_LIVE_HOST_INSTANCE_ID" `
    -HostLabel "Revit" `
    -HostProbe $revitIdentity `
    -FallbackReason "Host instance id 必须来自当前 Revit AgentHost runtime。"

Add-DetectedValue -Name "DSP_REVIT_LIVE_VERSION" -Value "2027" -Source "Task16 冻结版本"
Add-DetectedValue -Name "DSP_REVIT_LIVE_TFM" -Value "net10.0-windows" -Source "Task16 冻结目标框架"

$defaultRevitApiDir = "C:\Program Files\Autodesk\Revit 2027"
$existingRevitApiDir = [Environment]::GetEnvironmentVariable("DSP_REVIT_LIVE_API_DIR")
if (-not [string]::IsNullOrWhiteSpace($existingRevitApiDir) -and (Test-Path -LiteralPath $existingRevitApiDir -PathType Container)) {
    Add-Result `
        -Name "DSP_REVIT_LIVE_API_DIR" `
        -Status "EXISTING" `
        -Value (Resolve-Path -LiteralPath $existingRevitApiDir).Path `
        -Source "当前进程环境"
}
elseif (Test-Path -LiteralPath $defaultRevitApiDir -PathType Container) {
    Add-DetectedValue `
        -Name "DSP_REVIT_LIVE_API_DIR" `
        -Value (Resolve-Path -LiteralPath $defaultRevitApiDir).Path `
        -Source "Revit 2027 默认安装目录"
}
else {
    Add-Result `
        -Name "DSP_REVIT_LIVE_API_DIR" `
        -Status "MANUAL_REQUIRED" `
        -Value "" `
        -Source "Revit 安装目录" `
        -Note "未找到 Revit 2027 默认安装目录，请填写实际 Revit API 目录。"
}

Add-ManualValue -Name "DSP_PHASE_I_SEMANTIC_ID" -Reason "semantic_id 必须由当前受控双 Host 映射关系确认，不能由 native identity 自动猜测。"

Write-Output "ENVIRONMENT_DISCOVERY"
$results |
    Select-Object Name, Status, Value, Source, Note |
    Format-Table -AutoSize |
    Out-String -Width 4096 |
    Write-Output

Write-Output "COPYABLE_ENV_COMMANDS"
foreach ($item in $results) {
    if ($item.Status -eq "DETECTED" -or $item.Status -eq "EXISTING") {
        $escaped = $item.Value.Replace("'", "''")
        Write-Output ('$env:{0}=''{1}''' -f $item.Name, $escaped)
    }
    else {
        Write-Output ('# MANUAL_REQUIRED: $env:{0}=''<填入真实值>''  # {1}' -f $item.Name, $item.Note)
    }
}
