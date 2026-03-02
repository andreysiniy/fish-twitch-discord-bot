param(
    [string]$SuitePath = (Join-Path $PSScriptRoot "items_endpoints_manual_tests.json"),
    [switch]$StopOnFail,
    [switch]$ListOnly,
    [string[]]$OnlyIds
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Web.Extensions

function Parse-JsonText {
    param([Parameter(Mandatory = $true)][string]$Text)

    $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
    $serializer.MaxJsonLength = [int]::MaxValue
    return $serializer.DeserializeObject($Text)
}

function ConvertTo-Hashtable {
    param([AllowNull()][object]$InputObject)

    if ($null -eq $InputObject) {
        return $null
    }

    if ($InputObject -is [System.Collections.IDictionary]) {
        $hash = @{}
        foreach ($key in $InputObject.Keys) {
            $hash[$key] = ConvertTo-Hashtable -InputObject $InputObject[$key]
        }
        return $hash
    }

    if ($InputObject -is [System.Collections.IEnumerable] -and -not ($InputObject -is [string])) {
        $list = @()
        foreach ($item in $InputObject) {
            $list += ,(ConvertTo-Hashtable -InputObject $item)
        }
        return $list
    }

    if ($InputObject -is [pscustomobject]) {
        $hash = @{}
        foreach ($prop in $InputObject.PSObject.Properties) {
            $hash[$prop.Name] = ConvertTo-Hashtable -InputObject $prop.Value
        }
        return $hash
    }

    return $InputObject
}

function Resolve-StringTemplate {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][hashtable]$Context
    )

    return [System.Text.RegularExpressions.Regex]::Replace(
        $Text,
        "\{\{([A-Za-z0-9_]+)\}\}",
        {
            param($match)
            $name = $match.Groups[1].Value
            if (-not $Context.ContainsKey($name)) {
                throw "Template variable '$name' not found while resolving '$Text'"
            }
            return [string]$Context[$name]
        }
    )
}

function Resolve-Templates {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][hashtable]$Context
    )

    if ($null -eq $Value) {
        return $null
    }

    if ($Value -is [string]) {
        return Resolve-StringTemplate -Text $Value -Context $Context
    }

    if ($Value -is [System.Collections.IDictionary]) {
        $resolvedHash = @{}
        foreach ($key in $Value.Keys) {
            $resolvedHash[$key] = Resolve-Templates -Value $Value[$key] -Context $Context
        }
        return $resolvedHash
    }

    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $resolvedArray = @()
        foreach ($item in $Value) {
            $resolvedArray += ,(Resolve-Templates -Value $item -Context $Context)
        }
        return $resolvedArray
    }

    if ($Value -is [pscustomobject]) {
        $resolvedObj = @{}
        foreach ($prop in $Value.PSObject.Properties) {
            $resolvedObj[$prop.Name] = Resolve-Templates -Value $prop.Value -Context $Context
        }
        return $resolvedObj
    }

    return $Value
}

function Try-ParseJson {
    param([string]$Content)

    if ([string]::IsNullOrWhiteSpace($Content)) {
        return $null
    }

    try {
        return ConvertTo-Hashtable -InputObject (Parse-JsonText -Text $Content)
    }
    catch {
        return $null
    }
}

function Invoke-TestHttpRequest {
    param(
        [Parameter(Mandatory = $true)][hashtable]$RequestSpec
    )

    $method = [string]$RequestSpec.method
    $url = [string]$RequestSpec.url

    $headers = @{}
    if ($RequestSpec.ContainsKey("headers") -and $null -ne $RequestSpec.headers) {
        foreach ($k in $RequestSpec.headers.Keys) {
            $headers[[string]$k] = [string]$RequestSpec.headers[$k]
        }
    }

    $body = $null
    if ($RequestSpec.ContainsKey("body")) {
        $body = $RequestSpec.body
    }

    $contentType = $null
    if ($headers.ContainsKey("Content-Type")) {
        $contentType = $headers["Content-Type"]
        $headers.Remove("Content-Type")
    }

    try {
        if ($null -eq $body) {
            $response = Invoke-WebRequest -Method $method -Uri $url -Headers $headers -UseBasicParsing
        }
        else {
            $bodyJson = ConvertTo-Json -InputObject $body -Depth 100
            if ([string]::IsNullOrWhiteSpace($contentType)) {
                $contentType = "application/json"
            }
            $response = Invoke-WebRequest -Method $method -Uri $url -Headers $headers -Body $bodyJson -ContentType $contentType -UseBasicParsing
        }

        return @{
            status_code = [int]$response.StatusCode
            raw_content = [string]$response.Content
            json = Try-ParseJson -Content ([string]$response.Content)
        }
    }
    catch {
        $statusCode = 0
        $rawContent = ""

        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }

        try {
            $stream = $_.Exception.Response.GetResponseStream()
            if ($null -ne $stream) {
                $reader = New-Object System.IO.StreamReader($stream)
                $rawContent = $reader.ReadToEnd()
                $reader.Dispose()
            }
        }
        catch {
            $rawContent = ""
        }

        if ([string]::IsNullOrWhiteSpace($rawContent) -and $_.ErrorDetails -and $_.ErrorDetails.Message) {
            $rawContent = [string]$_.ErrorDetails.Message
        }

        return @{
            status_code = $statusCode
            raw_content = [string]$rawContent
            json = Try-ParseJson -Content ([string]$rawContent)
        }
    }
}

function Assert-JsonSubset {
    param(
        [AllowNull()]$Expected,
        [AllowNull()]$Actual,
        [string]$Path = "$"
    )

    if ($Expected -is [System.Collections.IDictionary]) {
        if (-not ($Actual -is [System.Collections.IDictionary])) {
            throw "Expected object at $Path"
        }

        foreach ($k in $Expected.Keys) {
            if (-not $Actual.ContainsKey($k)) {
                throw "Missing key '$k' at $Path"
            }
            Assert-JsonSubset -Expected $Expected[$k] -Actual $Actual[$k] -Path "$Path.$k"
        }
        return
    }

    if (($Expected -is [System.Collections.IEnumerable] -and -not ($Expected -is [string]))) {
        if (-not ($Actual -is [System.Collections.IEnumerable] -and -not ($Actual -is [string]))) {
            throw "Expected array at $Path"
        }

        $expectedArr = @($Expected)
        $actualArr = @($Actual)
        if ($expectedArr.Count -ne $actualArr.Count) {
            throw "Array length mismatch at $Path (expected $($expectedArr.Count), got $($actualArr.Count))"
        }

        for ($i = 0; $i -lt $expectedArr.Count; $i++) {
            Assert-JsonSubset -Expected $expectedArr[$i] -Actual $actualArr[$i] -Path "$Path[$i]"
        }
        return
    }

    if ($Expected -is [double] -or $Expected -is [float] -or $Expected -is [decimal]) {
        $expectedNum = [double]$Expected
        $actualNum = [double]$Actual
        if ($expectedNum -ne $actualNum) {
            throw "Value mismatch at $Path (expected $expectedNum, got $actualNum)"
        }
        return
    }

    if ([string]$Expected -ne [string]$Actual) {
        throw "Value mismatch at $Path (expected '$Expected', got '$Actual')"
    }
}

function Get-ItemIdsFromArray {
    param([AllowNull()]$ArrayValue)

    $ids = @()
    foreach ($obj in @($ArrayValue)) {
        if ($obj -is [System.Collections.IDictionary] -and $obj.ContainsKey("item_id")) {
            $ids += [string]$obj.item_id
        }
    }
    return $ids
}

function Test-TitleExists {
    param(
        [AllowNull()]$Json,
        [Parameter(Mandatory = $true)][string]$Title
    )

    if ($null -eq $Json) {
        return $false
    }

    if ($Json -is [System.Collections.IDictionary]) {
        foreach ($k in $Json.Keys) {
            if ($k -eq "title" -and [string]$Json[$k] -eq $Title) {
                return $true
            }
            if (Test-TitleExists -Json $Json[$k] -Title $Title) {
                return $true
            }
        }
        return $false
    }

    if ($Json -is [System.Collections.IEnumerable] -and -not ($Json -is [string])) {
        foreach ($entry in $Json) {
            if (Test-TitleExists -Json $entry -Title $Title) {
                return $true
            }
        }
    }

    return $false
}

function Assert-Expectations {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Expect,
        [Parameter(Mandatory = $true)][hashtable]$Response
    )

    if ($Expect.ContainsKey("status")) {
        $expectedStatus = [int]$Expect.status
        if ($Response.status_code -ne $expectedStatus) {
            throw "Status mismatch: expected $expectedStatus, got $($Response.status_code)"
        }
    }

    if ($Expect.ContainsKey("status_one_of")) {
        $allowed = @($Expect.status_one_of | ForEach-Object { [int]$_ })
        if (-not ($allowed -contains [int]$Response.status_code)) {
            throw "Status mismatch: got $($Response.status_code), allowed: $($allowed -join ', ')"
        }
    }

    if ($Expect.ContainsKey("json_contains")) {
        if ($null -eq $Response.json) {
            throw "Expected JSON body but response body is not JSON"
        }
        Assert-JsonSubset -Expected $Expect.json_contains -Actual $Response.json
    }

    if ($Expect.ContainsKey("array_contains_item_ids")) {
        if (-not ($Response.json -is [System.Collections.IEnumerable] -and -not ($Response.json -is [string]))) {
            throw "Expected top-level JSON array for array_contains_item_ids"
        }

        $actualIds = Get-ItemIdsFromArray -ArrayValue $Response.json
        foreach ($requiredId in @($Expect.array_contains_item_ids)) {
            if (-not ($actualIds -contains [string]$requiredId)) {
                throw "Missing item_id '$requiredId' in response array"
            }
        }
    }

    if ($Expect.ContainsKey("items_array_contains_item_ids")) {
        if ($null -eq $Response.json -or -not ($Response.json -is [System.Collections.IDictionary])) {
            throw "Expected JSON object with items[]"
        }
        if (-not $Response.json.ContainsKey("items")) {
            throw "Response JSON does not contain 'items'"
        }

        $actualIds = Get-ItemIdsFromArray -ArrayValue $Response.json.items
        foreach ($requiredId in @($Expect.items_array_contains_item_ids)) {
            if (-not ($actualIds -contains [string]$requiredId)) {
                throw "Missing item_id '$requiredId' in response items[]"
            }
        }
    }

    if ($Expect.ContainsKey("json_should_not_contain_title")) {
        if ($null -eq $Response.json) {
            throw "Expected JSON body for json_should_not_contain_title"
        }
        $forbiddenTitle = [string]$Expect.json_should_not_contain_title
        if (Test-TitleExists -Json $Response.json -Title $forbiddenTitle) {
            throw "Forbidden title '$forbiddenTitle' found in response"
        }
    }
}

if (-not (Test-Path -Path $SuitePath)) {
    throw "Suite file not found: $SuitePath"
}

$suite = ConvertTo-Hashtable -InputObject (Parse-JsonText -Text (Get-Content -Path $SuitePath -Raw))

if (-not $suite.ContainsKey("tests")) {
    throw "Invalid suite: 'tests' not found"
}

$context = @{}
if ($suite.ContainsKey("variables")) {
    foreach ($k in $suite.variables.Keys) {
        $context[$k] = $suite.variables[$k]
    }
}
if ($suite.ContainsKey("auth")) {
    foreach ($k in $suite.auth.Keys) {
        $context[$k] = $suite.auth[$k]
    }
}
if ($ListOnly) {
    Write-Host "Suite: $($suite.suite)"
    $idx = 1
    foreach ($t in @($suite.tests)) {
        Write-Host ("{0}. {1}" -f $idx, $t.id)
        $idx++
    }
    exit 0
}

$total = 0
$passed = 0
$failed = 0
$failedTests = @()

Write-Host "Running suite: $($suite.suite)"

$testsToRun = @($suite.tests)
if ($OnlyIds -and $OnlyIds.Count -gt 0) {
    $normalizedOnlyIds = @()
    foreach ($rawId in $OnlyIds) {
        foreach ($part in ([string]$rawId -split ',')) {
            $trimmed = [string]$part
            if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
                $normalizedOnlyIds += $trimmed.Trim()
            }
        }
    }

    $set = @{}
    foreach ($id in $normalizedOnlyIds) {
        if (-not [string]::IsNullOrWhiteSpace($id)) {
            $set[[string]$id] = $true
        }
    }
    $testsToRun = @($suite.tests | Where-Object { $set.ContainsKey([string]$_.id) })
}

foreach ($test in $testsToRun) {
    $total++
    $testId = [string]$test.id
    $response = $null

    try {
        $requestSpec = Resolve-Templates -Value $test.request -Context $context
        $expectSpec = Resolve-Templates -Value $test.expect -Context $context

        $response = Invoke-TestHttpRequest -RequestSpec $requestSpec
        Assert-Expectations -Expect $expectSpec -Response $response

        $passed++
        Write-Host ("[PASS] {0} -> HTTP {1}" -f $testId, $response.status_code) -ForegroundColor Green
    }
    catch {
        $failed++
        $message = $_.Exception.Message
        $failedTests += @{
            id = $testId
            error = $message
        }

        Write-Host ("[FAIL] {0} -> {1}" -f $testId, $message) -ForegroundColor Red
        if ($null -ne $response) {
            $bodyPreview = [string]$response.raw_content
            if ($bodyPreview.Length -gt 800) {
                $bodyPreview = $bodyPreview.Substring(0, 800) + "..."
            }
            if (-not [string]::IsNullOrWhiteSpace($bodyPreview)) {
                Write-Host ("       status={0} body={1}" -f $response.status_code, $bodyPreview) -ForegroundColor DarkYellow
            }
        }

        if ($StopOnFail) {
            break
        }
    }
}

Write-Host ""
Write-Host ("Summary: total={0}, passed={1}, failed={2}" -f $total, $passed, $failed)

if ($failed -gt 0) {
    Write-Host "Failed tests:"
    foreach ($f in $failedTests) {
        Write-Host ("- {0}: {1}" -f $f.id, $f.error)
    }
    exit 1
}

exit 0
