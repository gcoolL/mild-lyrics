# Mild Lyrics installer for Windows. From PowerShell:
#     irm https://github.com/gcoolL/mild-lyrics/releases/latest/download/install.ps1 | iex
# Installs the latest release into %LOCALAPPDATA%\Programs\mild-lyrics with its
# own Python environment, Start menu and desktop shortcuts, and an entry in
# Settings > Apps. Run it again to repair; -Uninstall takes it all back out.
# Why it works this way: docs/notes/install.md
param([switch]$Uninstall, [string]$Dir = "")

$Repo = 'gcoolL/mild-lyrics'
$PyUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MildLyrics'
$Names = @{ 'mild-lyrics' = 'Mild Lyrics'; 'ttml-editor' = 'TTML Editor' }
$StemOf = @{ lyrics = 'mild-lyrics'; editor = 'ttml-editor' }

# Nothing at the top level but these functions and the last line: under
# `irm | iex` this runs in the caller's own session, where `exit` would close
# their window and a changed preference would outlive the install.

function Say($text) { Write-Host $text }
function Warn($text) { Write-Host "[ !!!! ] $text" -ForegroundColor Yellow }

function Ask($question, [bool]$default = $true) {
    $hint = if ($default) { 'Y/n' } else { 'y/N' }
    $got = (Read-Host "$question [$hint]").Trim().ToLower()
    if (-not $got) { return $default }
    return $got.StartsWith('y')
}

$DefaultDir = Join-Path $env:LOCALAPPDATA 'Programs\mild-lyrics'

function Test-Ours($dir) { return Test-Path (Join-Path $dir 'mild-lyrics\lyrics_gui.py') }

function Get-Asked { if ($Dir) { return $Dir } return $env:MILD_DIR }

function Get-Registered {
    $known = (Get-ItemProperty $UninstallKey -ErrorAction SilentlyContinue).InstallLocation
    if ($known -and (Test-Ours $known)) { return $known }
    return $null
}

function Get-InstallDir {
    # The install to remove: the one named, else the registered one, else the default.
    $asked = Get-Asked
    if ($asked) { return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($asked)) }
    $known = Get-Registered
    if ($known) { return $known }
    return $DefaultDir
}

function Resolve-Target($path) {
    # A writable install folder for what was typed, or $null after saying why.
    $path = [Environment]::ExpandEnvironmentVariables($path.Trim().Trim('"'))
    if ($path.StartsWith('~')) { $path = $HOME + $path.Substring(1) }
    try { $full = [IO.Path]::GetFullPath($path) } catch { Warn "Not a folder path: $path"; return $null }
    # Uninstalling deletes the whole folder, so a folder that already holds
    # other things gets a mild-lyrics folder of its own inside it.
    if ((Test-Path $full) -and -not (Test-Ours $full) -and (Get-ChildItem $full -Force | Select-Object -First 1)) {
        $full = Join-Path $full 'mild-lyrics'
        if ((Test-Path $full) -and -not (Test-Ours $full) -and (Get-ChildItem $full -Force | Select-Object -First 1)) {
            Warn "$full already has other files in it; pick another folder."
            return $null
        }
    }
    try {
        New-Item -ItemType Directory $full -Force | Out-Null
        $probe = Join-Path $full '.mild-write-test'
        Set-Content $probe 'x'
        Remove-Item $probe
    } catch {
        Warn "Cannot write to $full. Folders like Program Files need administrator rights; pick one in your user folder."
        return $null
    }
    return $full
}

function Select-Folder {
    # Explorer's folder picker, or $null (typed paths still work without it).
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $d = New-Object System.Windows.Forms.FolderBrowserDialog
        $d.Description = 'Choose where to install Mild Lyrics'
        $owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true }
        if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { return $d.SelectedPath }
    } catch {
        Warn "No folder picker here ($($_.Exception.Message)); type the folder instead."
    }
    return $null
}

function Read-InstallDir {
    # Where a first install goes: the default, a typed folder, or a browsed one.
    if ([Console]::IsInputRedirected) { return Resolve-Target $DefaultDir }
    while ($true) {
        Say "Mild Lyrics will be installed in $DefaultDir"
        $got = (Read-Host 'Press Enter for that, type another folder, or B to browse').Trim()
        if (-not $got) { $got = $DefaultDir }
        elseif ($got -ieq 'b') { $got = Select-Folder; if (-not $got) { continue } }
        $dir = Resolve-Target $got
        if ($dir) { return $dir }
    }
}

function Test-Python($exe, [string[]]$pre = @()) {
    # @(version, path) for a 64-bit 3.10+ that is not the Store's, else $null.
    $ErrorActionPreference = 'Continue'
    # No double quotes: Windows PowerShell 5.1 passes them to programs unescaped.
    $code = 'import sys; print(''%d.%d|%s'' % (sys.version_info[0], sys.version_info[1], sys.executable)) if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else None'
    try { $out = & $exe @pre -c $code 2>$null } catch { return $null }
    if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
    $ver, $path = "$out".Trim().Split('|', 2)
    # Store Python redirects new AppData files into its own package folder, so
    # a venv it made under %LOCALAPPDATA% would be invisible to the shortcuts.
    if (-not $path -or $path -match '\\WindowsApps\\') { return $null }
    return @($ver, $path)
}

function Find-Python {
    $paths = New-Object System.Collections.Generic.List[string]
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $ErrorActionPreference = 'Continue'
        foreach ($line in (& py -0p 2>$null)) {
            if ("$line" -match '([A-Za-z]:\\.*python\.exe)') { $paths.Add($Matches[1]) }
        }
    }
    foreach ($c in (Get-Command python, python3 -All -CommandType Application -ErrorAction SilentlyContinue)) {
        # The WindowsApps python.exe on a machine with no Python is a stub that
        # opens the Store when run, so it is never run.
        if ($c.Source -notmatch '\\WindowsApps\\') { $paths.Add($c.Source) }
    }
    Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe') -ErrorAction SilentlyContinue |
        ForEach-Object { $paths.Add($_.FullName) }

    $found = @{}
    foreach ($p in ($paths | Select-Object -Unique)) {
        $got = Test-Python $p
        if ($got -and -not $found.ContainsKey($got[0])) { $found[$got[0]] = $got[1] }
    }
    # Versions every dependency has wheels for first; the newest Python can
    # leave pip compiling something from source.
    foreach ($v in '3.12', '3.13', '3.11', '3.14', '3.10') {
        if ($found.ContainsKey($v)) { return $found[$v] }
    }
    foreach ($v in $found.Keys) { return $found[$v] }
    return $null
}

function Install-Python {
    $exe = Join-Path $env:TEMP 'python-3.12.10-amd64.exe'
    Say 'Downloading Python 3.12 from python.org ...'
    Invoke-WebRequest $PyUrl -OutFile $exe -UseBasicParsing
    Say 'Installing it for this user (no administrator needed) ...'
    $p = Start-Process $exe -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=0',
        'Include_test=0', 'Include_doc=0', 'Shortcuts=0')
    Remove-Item $exe -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) { throw "the Python installer stopped with code $($p.ExitCode)" }
    $py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (-not (Test-Path $py)) { throw "Python was installed, but $py is not there" }
    return $py
}

function Get-Release($tmp) {
    # The release unpacked under $tmp; its top folder.
    $headers = @{ 'User-Agent' = 'mild-lyrics-installer' }
    $zip = $env:MILD_ZIP                          # a zipball on disk, to try a build before release
    if ($zip) {
        Say "Unpacking Mild Lyrics from $zip ..."
    } else {
        $rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers $headers
        Say "Downloading Mild Lyrics $($rel.tag_name) ..."
        $zip = Join-Path $tmp 'release.zip'
        Invoke-WebRequest $rel.zipball_url -OutFile $zip -Headers $headers -UseBasicParsing
    }
    Expand-Archive $zip (Join-Path $tmp 'x')
    # GitHub puts everything under one "<owner>-<repo>-<sha>" folder.
    $top = Get-ChildItem (Join-Path $tmp 'x') -Directory | Select-Object -First 1
    if (-not $top -or -not (Test-Path (Join-Path $top.FullName 'mild-lyrics\lyrics_gui.py'))) {
        throw 'the download is not a Mild Lyrics release'
    }
    return $top.FullName
}

function Copy-Release($top, $dir) {
    # robocopy merges into an existing install; Copy-Item -Recurse can nest.
    & robocopy $top $dir /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "could not copy the release into $dir (robocopy $LASTEXITCODE)" }
    if (-not (Test-Path (Join-Path $dir 'install.ps1'))) {
        # Releases before the installer existed: Settings > Apps still needs a
        # copy of this script to uninstall with.
        Invoke-WebRequest "https://raw.githubusercontent.com/$Repo/main/install.ps1" `
            -OutFile (Join-Path $dir 'install.ps1') -UseBasicParsing
    }
}

function Show-Checklist($cat) {
    # The catalogue as a window of checkboxes: the comma list picked, or $null when cancelled.
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $ui = @{ busy = $false; quiet = $false; on = @{}; cats = @{} }
    foreach ($a in $cat.apps) { $ui.on[$a.id] = [bool]$a.on }
    foreach ($c in $cat.cats) {
        $ui.cats[$c.id] = $c
        foreach ($i in $c.items) { $ui.on[$i.id] = [bool]$i.on }
    }

    $form = New-Object System.Windows.Forms.Form -Property @{
        Text = 'Mild Lyrics installer'; Width = 720; Height = 680; TopMost = $true
        StartPosition = 'CenterScreen'; AutoScaleMode = 'Dpi'; MinimumSize = '520, 420'
        Font = New-Object System.Drawing.Font('Segoe UI', 9) }
    $intro = New-Object System.Windows.Forms.Label -Property @{
        Dock = 'Top'; Height = 58; Padding = '10, 10, 10, 4'
        Text = 'Choose what to install. An app brings its categories with it, and a category does all of its items. Select a row to read what it is for.' }
    $appsBox = New-Object System.Windows.Forms.GroupBox -Property @{
        Dock = 'Top'; Height = 78; Text = 'Apps'; Padding = '10, 4, 10, 4' }
    $boxes = @{}
    $y = 20
    foreach ($a in $cat.apps) {
        $b = New-Object System.Windows.Forms.CheckBox -Property @{
            Left = 12; Top = $y; AutoSize = $true; Checked = $ui.on[$a.id]
            Text = "$($a.name)  -  $($a.what)"; Tag = $a.id }
        $appsBox.Controls.Add($b)
        $boxes[$a.id] = $b
        $y += 26
    }
    # Rows are measured in the tree's font, so it is the bold one; items get the plain one.
    $plain = $form.Font
    $tree = New-Object System.Windows.Forms.TreeView -Property @{
        Dock = 'Fill'; CheckBoxes = $true; ShowNodeToolTips = $true; HideSelection = $false
        Font = New-Object System.Drawing.Font($plain, [System.Drawing.FontStyle]::Bold) }
    $about = New-Object System.Windows.Forms.Label -Property @{
        Dock = 'Bottom'; Height = 64; Padding = '10, 6, 10, 0'; Text = '' }
    $bar = New-Object System.Windows.Forms.FlowLayoutPanel -Property @{
        Dock = 'Bottom'; Height = 46; FlowDirection = 'RightToLeft'; Padding = '8, 6, 8, 6' }
    $cancel = New-Object System.Windows.Forms.Button -Property @{
        Text = 'Cancel'; Width = 96; Height = 30; DialogResult = 'Cancel' }
    $go = New-Object System.Windows.Forms.Button -Property @{ Text = 'Install'; Width = 96; Height = 30 }
    $bar.Controls.AddRange(@($cancel, $go))
    $form.Controls.AddRange(@($tree, $about, $bar, $appsBox, $intro))
    $tree.BringToFront()                          # the Fill control docks last
    $form.AcceptButton = $go
    $form.CancelButton = $cancel

    $appName = @{ lyrics = 'Mild Lyrics'; editor = 'TTML Editor' }
    $ui.busy = $true
    $tree.BeginUpdate()
    foreach ($c in $cat.cats) {
        $label = $c.title
        if ($c.app -ne 'both') { $label += "  ($($appName[$c.app]))" }
        if ($c.locked) { $label += '  (needed)' }
        $node = $tree.Nodes.Add($c.id, $label)
        $node.Tag = $c.id
        $node.ToolTipText = $c.use
        foreach ($i in $c.items) {
            $child = $node.Nodes.Add($i.id, "$($i.name)  -  $($i.what)")
            $child.Tag = $i.id
            $child.NodeFont = $plain
            $child.ToolTipText = $i.what
        }
        $node.Expand()
    }
    $tree.EndUpdate()
    $ui.busy = $false
    $sync = {
        # The ticks from $ui.on: an item as recorded, a category while any item is.
        $ui.busy = $true
        foreach ($node in $tree.Nodes) {
            $locked = $ui.cats[$node.Tag].locked
            $any = $false
            foreach ($n in $node.Nodes) {
                $n.Checked = $ui.on[$n.Tag] -or $locked
                if ($n.Checked) { $any = $true }
            }
            $node.Checked = $any
        }
        $ui.busy = $false
    }
    $appTick = {
        # mild-setup.py's app_tick: an app's own categories back to their defaults
        # or off, and shared ones too while the other app is off.
        param($app, $now)
        $ui.on["app:$app"] = $now
        $other = if ($app -eq 'lyrics') { $ui.on['app:editor'] } else { $ui.on['app:lyrics'] }
        foreach ($c in $cat.cats) {
            if ($c.locked -or ($c.app -ne $app -and $c.app -ne 'both')) { continue }
            if ($c.app -eq 'both' -and $other) { continue }
            foreach ($i in $c.items) { $ui.on[$i.id] = $now -and [bool]$i.default }
        }
    }
    $tree.Add_AfterCheck({
        param($s, $e)
        if ($ui.busy) { return }
        $node = $e.Node
        $catNode = if ($node.Parent) { $node.Parent } else { $node }
        $c = $ui.cats[$catNode.Tag]
        if ($c.locked) {
            $about.Text = "$($c.title) is needed by both apps, so it stays ticked."
        } elseif ($node.Parent) {
            $ui.on[$node.Tag] = $node.Checked
        } else {
            foreach ($n in $node.Nodes) { $ui.on[$n.Tag] = $node.Checked }
        }
        if ($node.Checked -and $c.app -ne 'both' -and -not $ui.on["app:$($c.app)"]) {
            # Something ticked for an app means that app; its other rows stay as they are.
            $ui.on["app:$($c.app)"] = $true
            $ui.quiet = $true
            $boxes["app:$($c.app)"].Checked = $true
            $ui.quiet = $false
        }
        & $sync
    })
    $tree.Add_AfterSelect({
        param($s, $e)
        $node = $e.Node
        if ($node.Parent) { $c = $ui.cats[$node.Parent.Tag]; $about.Text = "$($node.Text)`n$($c.use)" }
        else { $c = $ui.cats[$node.Tag]; $about.Text = "$($c.use)`n$($c.why)" }
    })
    foreach ($b in $boxes.Values) {
        $b.Add_CheckedChanged({
            param($s, $e)
            if ($ui.quiet) { return }
            & $appTick $s.Tag.Substring(4) $s.Checked
            & $sync
        })
    }
    $go.Add_Click({
        if (-not ($ui.on['app:lyrics'] -or $ui.on['app:editor'])) {
            $about.Text = 'Pick at least one of the apps.'
            return
        }
        $form.DialogResult = 'OK'
    })
    & $sync
    if ($tree.Nodes.Count) { $tree.Nodes[0].EnsureVisible() }
    $form.Add_Shown({ $form.Activate() })
    if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return $null }

    $picks = New-Object System.Collections.Generic.List[string]
    foreach ($a in $cat.apps) { if ($ui.on[$a.id]) { $picks.Add($a.id) } }
    foreach ($node in $tree.Nodes) {
        $app = $ui.cats[$node.Tag].app
        if ($app -ne 'both' -and -not $ui.on["app:$app"]) { continue }
        foreach ($n in $node.Nodes) { if ($n.Checked) { $picks.Add($n.Tag) } }
    }
    $form.Dispose()
    return ($picks -join ',')
}

function Select-Parts($py, $top, $dir) {
    # What to install, as setup's --pick list; '' for a release whose setup has no
    # checklist yet (it then installs everything, as before); $null when cancelled.
    $setup = Join-Path $top 'mild-setup.py'
    $last = @()
    $saved = Join-Path $dir '.install-picks.json'
    if (Test-Path $saved) { $last = @('--last', $saved) }
    $ErrorActionPreference = 'Continue'
    $json = & $py $setup --catalogue @last 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $json) { return '' }
    $cat = ($json -join "`n") | ConvertFrom-Json
    try {
        return Show-Checklist $cat
    } catch {
        Warn "No checklist window here ($($_.Exception.Message)); choose in this window instead."
    }
    $file = Join-Path $env:TEMP ("mild-picks-" + [guid]::NewGuid().ToString('N') + '.txt')
    # Straight to the console: a function returns whatever it prints, so `& $py` would
    # hand back the whole list along with the picks.
    $argv = (@($setup, '--choose', $file) + $last | ForEach-Object { "`"$_`"" }) -join ' '
    $p = Start-Process $py -ArgumentList $argv -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -ne 0 -or -not (Test-Path $file)) { return $null }
    $got = Get-Content $file -Raw
    Remove-Item $file -ErrorAction SilentlyContinue
    return $got.Trim()
}

function Remove-Links($dir, $folders) {
    # The app shortcuts in $folders that start this install.
    $shell = New-Object -ComObject WScript.Shell
    foreach ($folder in $folders) {
        foreach ($name in $Names.Values) {
            $link = Join-Path $folder "$name.lnk"
            if (-not (Test-Path $link)) { continue }
            $s = $shell.CreateShortcut($link)
            if ("$($s.TargetPath) $($s.Arguments)".Contains($dir)) { Remove-Item $link -Force }
        }
    }
}

function Remove-Empty($dir) {
    # A first install's folder, made before anything was picked.
    if ((Test-Path $dir) -and -not (Get-ChildItem $dir -Force | Select-Object -First 1)) {
        Remove-Item $dir -Force -ErrorAction SilentlyContinue
    }
}

function New-Shortcut($link, $target, $arguments, $workdir) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
    $s.TargetPath = $target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $workdir
    $s.Save()
}

function Install-MildLyrics {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'      # the 5.1 progress bar slows downloads to a crawl
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072

    Say "Mild Lyrics installer`n"
    $asked = Get-Asked
    $known = Get-Registered
    if ($asked) {
        $dir = Resolve-Target $asked
    } elseif ($known) {
        $dir = $known
        Say "Already installed in $dir, so it is updated there. To move it, uninstall it first."
    } else {
        $dir = Read-InstallDir
    }
    if (-not $dir) { return }
    Say "Installing into $dir`n"
    if (Test-Path (Join-Path $dir '.git')) {
        Warn "$dir is a git checkout. Update it with git and run setup.cmd in it instead."
        return
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        Warn 'Mild Lyrics needs 64-bit Windows (its Qt has no 32-bit build).'
        return
    }

    $py = Find-Python
    if ($py) {
        Say "Using Python at $py"
    } else {
        Say 'Mild Lyrics runs on Python 3.10 or newer, and none was found (the Microsoft Store one is skipped on purpose).'
        if (-not (Ask 'Install Python 3.12 from python.org for this user (about 25 MB, no administrator needed)?')) {
            Remove-Empty $dir
            Say 'Nothing was installed.'
            return
        }
        $py = Install-Python
    }

    $tmp = Join-Path $env:TEMP ("mild-install-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory $tmp | Out-Null
    try {
        $top = Get-Release $tmp
        $picks = Select-Parts $py $top $dir
        if ($null -eq $picks) {
            Remove-Empty $dir
            Say 'Cancelled. Nothing was installed.'
            return
        }
        Copy-Release $top $dir
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    $want = if ($picks) { $picks.Split(',') } else { @('app:lyrics', 'app:editor', 'shortcut:menu', 'shortcut:desktop') }
    $stems = @(foreach ($k in 'lyrics', 'editor') { if ($want -contains "app:$k") { $StemOf[$k] } })

    Say "`nInstalling what you picked into Mild Lyrics' own environment. This takes a few minutes the first time.`n"
    $setup = Join-Path $dir 'mild-setup.py'
    $args_ = @($setup, '--venv', '--no-doctor')
    if ($picks) { $args_ += @('--pick', $picks) } else { $args_ += @('--yes', '--for', 'both') }
    & $py @args_
    $setupCode = $LASTEXITCODE

    $vpy = Join-Path $dir '.venv\Scripts\python.exe'
    $vpyw = Join-Path $dir '.venv\Scripts\pythonw.exe'
    $ErrorActionPreference = 'Continue'
    & $vpy -c 'import PyQt6.QtWidgets' 2>$null
    $qtOk = $LASTEXITCODE -eq 0
    $ErrorActionPreference = 'Stop'
    if (-not (Test-Path $vpyw) -or -not $qtOk) {
        Warn 'The setup above did not finish: Mild Lyrics cannot start yet.'
        Say  '         Its own lines above say what went wrong. Running this installer again retries.'
        return
    }

    $programs = [Environment]::GetFolderPath('Programs')
    $desktop = [Environment]::GetFolderPath('Desktop')
    # A repair with less picked takes back the shortcuts it made before.
    Remove-Links $dir @($programs, $desktop)
    $made = @()
    if ($want -contains 'shortcut:menu') {
        foreach ($stem in $stems) {
            New-Shortcut (Join-Path $programs "$($Names[$stem]).lnk") $vpyw "`"$(Join-Path $dir "$stem.pyw")`"" $dir
        }
        $made += 'in the Start menu'
    }
    if ($want -contains 'shortcut:desktop') {
        $stem = $stems[0]
        New-Shortcut (Join-Path $desktop "$($Names[$stem]).lnk") $vpyw "`"$(Join-Path $dir "$stem.pyw")`"" $dir
        $made += "on the desktop ($($Names[$stem]))"
    }

    New-Item $UninstallKey -Force | Out-Null
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $props = @{
        DisplayName     = 'Mild Lyrics'
        Publisher       = 'gc'
        InstallLocation = $dir
        DisplayIcon     = $vpyw
        URLInfoAbout    = "https://github.com/$Repo"
        UninstallString = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $dir 'install.ps1')`" -Uninstall"
    }
    foreach ($k in $props.Keys) { Set-ItemProperty $UninstallKey $k $props[$k] }
    foreach ($k in 'NoModify', 'NoRepair') { Set-ItemProperty $UninstallKey $k 1 -Type DWord }

    Say ''
    if ($setupCode -ne 0) { Warn 'Setup left something to look at (above); Mild Lyrics itself is installed.' }
    $what = ($stems | ForEach-Object { $Names[$_] }) -join ' and '
    if ($made) { Say "Done. $what $(if ($stems.Count -gt 1) { 'are' } else { 'is' }) installed, with shortcuts $($made -join ' and ')." }
    else { Say "Done. $what $(if ($stems.Count -gt 1) { 'are' } else { 'is' }) installed in $dir (no shortcuts were picked)." }
    Say 'It updates itself. Run the installer again to change what is installed, and remove it from Settings > Apps.'
    $first = $Names[$stems[0]]
    if (Ask "Start $first now?") {
        Start-Process $vpyw -ArgumentList "`"$(Join-Path $dir "$($stems[0]).pyw")`"" -WorkingDirectory $dir
    }
}

function Remove-MildLyrics {
    $ErrorActionPreference = 'Stop'
    $dir = Get-InstallDir
    if (-not (Test-Ours $dir)) {
        Say "No Mild Lyrics installed at $dir."
        return
    }
    if (Test-Path (Join-Path $dir '.git')) {
        Warn "$dir is a git checkout, not an install; it is left alone."
        return
    }
    if (-not (Ask "Remove Mild Lyrics from $dir?")) { return }

    $running = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($dir) }
    if ($running) {
        if (-not (Ask 'Mild Lyrics is running. Close it now?')) { return }
        $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
    }

    Remove-Links $dir @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))
    $proto = 'HKCU:\Software\Classes\mild-lyrics'
    $cmd = (Get-ItemProperty "$proto\shell\open\command" -ErrorAction SilentlyContinue).'(default)'
    if ($cmd -and $cmd.Contains($dir)) { Remove-Item $proto -Recurse -Force }
    Remove-Item $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue

    $data = @((Join-Path $env:APPDATA 'mild-lyrics'), (Join-Path $env:LOCALAPPDATA 'mild-lyrics')) |
        Where-Object { Test-Path $_ }
    if ($data) {
        Say "`nSettings, history and caches are kept in:"
        $data | ForEach-Object { Say "    $_" }
        if (Ask 'Delete those too?' $false) {
            $data | ForEach-Object { Remove-Item $_ -Recurse -Force -ErrorAction SilentlyContinue }
        }
    }

    Set-Location $env:USERPROFILE
    Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $dir) { Warn "Some files in $dir are in use; delete the folder by hand once they are not." }
    else { Say 'Mild Lyrics is removed.' }
    Say "Spicetify's debug-port flag and its Spotify shortcut, if setup made them, are left as they are."
}

function Main {
    try {
        if ($Uninstall) { Remove-MildLyrics } else { Install-MildLyrics }
    } catch {
        Warn "Stopped: $($_.Exception.Message)"
    }
    # Launched from Settings > Apps or a double-click: the window closes on exit.
    if ($PSCommandPath) { Read-Host "`nPress Enter to close" | Out-Null }
}

Main
