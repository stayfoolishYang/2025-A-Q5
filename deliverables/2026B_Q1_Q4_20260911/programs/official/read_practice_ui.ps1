$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$simulator = @(Get-Process -Name 'jammers-simulator-full' -ErrorAction Stop | Where-Object { $_.MainWindowHandle -ne 0 })
if ($simulator.Count -ne 1) { throw 'Expected exactly one official simulator window' }
$windowElement = [System.Windows.Automation.AutomationElement]::FromHandle($simulator[0].MainWindowHandle)
$documentCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)
$documentElement = $windowElement.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $documentCondition)
if ($null -eq $documentElement) { throw 'Simulator UI document unavailable' }
$documentText = ''
try {
    $textPattern = $documentElement.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
    $documentText = $textPattern.DocumentRange.GetText(-1)
} catch {
    $elements = $documentElement.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $lines = foreach ($element in $elements) {
        $kind = $element.Current.ControlType
        if ($kind -eq [System.Windows.Automation.ControlType]::Text -or $kind -eq [System.Windows.Automation.ControlType]::Header -or $kind -eq [System.Windows.Automation.ControlType]::Button) { $element.Current.Name }
    }
    $documentText = $lines -join "`n"
}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
@{ text = $documentText; pid = $simulator[0].Id; executable = $simulator[0].Path; observed_utc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json -Compress
