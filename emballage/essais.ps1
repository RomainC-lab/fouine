# Outils des essais de Fouine.exe sous Windows (utilisés par .github/workflows/fouine.yml) :
#   . emballage\essais.ps1
#
# Fouine.exe n'a pas de console : PowerShell ne l'attendrait pas et ne verrait ni ce qu'il
# écrit ni son code de retour. Cette fonction le lance, l'attend (avec un délai) et rend les deux.

function Lancer-Fouine {
    param(
        [Parameter(Mandatory)] [string] $Programme,
        [string[]] $Arguments = @(),
        [int] $DelaiSecondes = 120
    )
    $depart = New-Object System.Diagnostics.ProcessStartInfo
    $depart.FileName = (Resolve-Path $Programme).Path
    $depart.WorkingDirectory = (Get-Location).Path
    $depart.Arguments = ($Arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
    $depart.UseShellExecute = $false
    $depart.RedirectStandardOutput = $true
    $depart.RedirectStandardError = $true
    $depart.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $depart.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $processus = [System.Diagnostics.Process]::Start($depart)
    $sortie = $processus.StandardOutput.ReadToEndAsync()
    $erreurs = $processus.StandardError.ReadToEndAsync()
    if (-not $processus.WaitForExit($DelaiSecondes * 1000)) {
        $processus.Kill()
        $processus.WaitForExit()
        Write-Host $sortie.Result
        Write-Host $erreurs.Result
        throw "$Programme $Arguments : toujours pas fini après $DelaiSecondes secondes, arrêté de force"
    }
    $processus.WaitForExit()
    [pscustomobject]@{
        Code    = $processus.ExitCode
        Sortie  = $sortie.Result.Trim()
        Erreurs = $erreurs.Result.Trim()
    }
}

# Affiche un journal de Fouine s'il existe (utile quand un essai échoue).
function Montrer-Journal {
    param([Parameter(Mandatory)] [string] $Dossier)
    $journal = Join-Path $Dossier "fouine.log"
    if (Test-Path $journal) {
        Write-Host "--- $journal"
        Get-Content $journal -Encoding UTF8 | ForEach-Object { Write-Host $_ }
        Write-Host "---"
    } else {
        Write-Host "(pas de journal dans $Dossier)"
    }
}

# Où pointe un raccourci (.lnk).
function Cible-Raccourci {
    param([Parameter(Mandatory)] [string] $Raccourci)
    (New-Object -ComObject WScript.Shell).CreateShortcut($Raccourci).TargetPath
}
