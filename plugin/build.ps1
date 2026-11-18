# Builds the DipTrace plugin into plugin\Dip2BoardView\ (Dip2BoardView.exe + settings.xml).
# Uses the C# compiler that ships with .NET Framework 4 in Windows; nothing to install.
# To install, copy that folder to C:\Program Files\DipTrace\Plugins\Pcb\ and restart PCB Layout.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$out = Join-Path $here 'Dip2BoardView'
New-Item -ItemType Directory -Force $out | Out-Null

& $csc /nologo /target:winexe /platform:anycpu /optimize+ /warnaserror+ `
    /reference:System.Numerics.dll /reference:System.Xml.dll /reference:System.Xml.Linq.dll `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    "/out:$out\Dip2BoardView.exe" "$here\Dip2BoardView.cs"
if ($LASTEXITCODE -ne 0) { throw "csc failed with exit code $LASTEXITCODE" }

Copy-Item "$here\settings.xml" $out -Force
Get-ChildItem $out | Select-Object Name, Length
