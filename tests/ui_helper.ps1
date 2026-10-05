param([int]$ProcId, [string]$Action = "list", [string]$Name = "", [int]$Max = 60)
# Помощник UI Automation для тестовой копии 1С (только окна указанного процесса).
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$root = $A::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition($A::ProcessIdProperty, $ProcId)
$els = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)

if ($Action -eq "list") {
    $n = 0
    foreach ($e in $els) {
        $t = $e.Current.Name
        if ($t -and ($Name -eq "" -or $t -like "*$Name*")) {
            "[" + $e.Current.ControlType.ProgrammaticName.Replace("ControlType.", "") + "] " + $t.Substring(0, [Math]::Min(160, $t.Length)).Replace("`n", " ")
            $n++
            if ($n -ge $Max) { break }
        }
    }
}
elseif ($Action -eq "confirmsecurity") {
    # Подтверждает только «Предупреждение безопасности» об открытии тестовой обработки ШД_Тест.epf.
    $warning = $false
    foreach ($e in $els) { $t = $e.Current.Name; if ($t -and $t -like "*Предупреждение безопасности*" -and $t -like "*ШД_Тест*") { $warning = $true; break } }
    if (-not $warning) { "none"; exit 0 }
    foreach ($e in $els) {
        if ($e.Current.Name -and $e.Current.Name.Replace([string][char]160, " ").Trim() -eq "Да" -and $e.Current.ControlType.ProgrammaticName -eq "ControlType.Button") {
            $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke(); "confirmed"; exit 0
        }
    }
    "no-button"
}
elseif ($Action -eq "click") {
    foreach ($e in $els) {
        if ($e.Current.Name -and $e.Current.Name.Replace([string][char]160, " ").Trim() -eq $Name) {
            $type = $e.Current.ControlType.ProgrammaticName
            if ($type -match "Button|Hyperlink|TabItem|MenuItem|ListItem|DataItem") {
                try {
                    $p = $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
                    $p.Invoke(); "clicked: $Name ($type)"; exit 0
                } catch {
                    try { $e.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select(); "selected: $Name"; exit 0 } catch { "cannot click: $Name ($type) $_" }
                }
            }
        }
    }
    "not found: $Name"
}
