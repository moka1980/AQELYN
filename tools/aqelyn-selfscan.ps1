# AQELYN self-scan for Windows. Read-only. Runs on your machine, writes two files locally,
# sends nothing. Built against real Windows 11 output. Run an ELEVATED PowerShell for the
# BitLocker and Defender checks to read true values.
#
#   powershell -ExecutionPolicy Bypass -File aqelyn-selfscan.ps1
#
[CmdletBinding()] param()
$ErrorActionPreference = "SilentlyContinue"
$subject = $env:COMPUTERNAME
$osName  = (Get-CimInstance Win32_OperatingSystem).Caption
$obs = New-Object System.Collections.ArrayList

function Add-Obs($h) { [void]$obs.Add($h) }
function Is-Public($addr) { return -not ($addr -like "127.*" -or $addr -eq "::1") }
function HtmlEnc($s) { if ($null -eq $s) { return "" }; return ([string]$s).Replace("&","&amp;").Replace("<","&lt;").Replace(">","&gt;").Replace([char]34,"&quot;") }

# --- 1. public listeners (mirrors the Linux listening_sockets_public check) ------------
$listen = Get-NetTCPConnection -State Listen
if ($null -ne $listen) {
  $pub = @($listen | Where-Object { Is-Public $_.LocalAddress })
  $ports = @($pub | Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
  if ($ports.Count -gt 0) {
    $wild = @($pub | Where-Object { $_.LocalAddress -eq "0.0.0.0" -or $_.LocalAddress -eq "::" } |
              Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
    $spec = @($ports | Where-Object { $wild -notcontains $_ })
    $high = $ports.Count -gt 3
    $detail = @()
    if ($wild.Count) { $detail += "on every interface: $($wild -join ', ')" }
    if ($spec.Count) { $detail += "on a specific routable address: $($spec -join ', ')" }
    Add-Obs @{
      observation_id = "obs-public-listeners"; subject = @{ kind = "host"; ref = $subject }
      check = "listening_sockets_public"
      severity = $(if ($high) { "high" } else { "medium" }); severity_score = $(if ($high) { 70.0 } else { 45.0 })
      what_happened   = "$($ports.Count) port(s) are reachable from beyond this machine - $($detail -join '; ')."
      why_it_matters  = "Anything not bound to loopback is reachable from the network this machine is on, not only from the machine itself. On Windows, ports 135/139/445 are RPC, NetBIOS and SMB file sharing."
      how_determined  = "Read listening sockets with Get-NetTCPConnection; loopback (127.0.0.0/8 and ::1) was excluded."
      risk_of_inaction= "Services intended for local use are exposed to everything that can route here."
      remediation = @{ summary = "Set the network profile to Public on untrusted networks, and turn off File and Printer Sharing / SMB where it is not needed."; difficulty = "low"; expected_outcome = "Only ports meant to be reachable stay reachable." }
      observed = @{ public_ports = $ports; all_interfaces = $wild; specific_address = $spec }
    }
  }
}

# --- 2. host firewall (all profiles must be enabled) -----------------------------------
$fw = Get-NetFirewallProfile
if ($null -eq $fw) {
  Add-Obs @{ observation_id="obs-firewall"; subject=@{kind="host";ref=$subject}; check="host_firewall_active"; severity="info"; severity_score=0.0; what_happened="This machine's firewall could not be read."; why_it_matters="Whether inbound traffic is filtered was not established."; how_determined="Get-NetFirewallProfile returned nothing."; risk_of_inaction="Unknown, and unknown is its own state."; remediation=@{summary="Run again from an elevated PowerShell.";difficulty="low";expected_outcome="The firewall state can be read."}; observed=@{unmeasured=$true;fact="firewall"} }
} else {
  $off = @($fw | Where-Object { -not $_.Enabled })
  if ($off.Count -gt 0) {
    Add-Obs @{ observation_id="obs-firewall"; subject=@{kind="host";ref=$subject}; check="host_firewall_active"; severity="medium"; severity_score=42.0; what_happened="The Windows Firewall is off for: $((@($off|ForEach-Object{$_.Name}) -join ', '))."; why_it_matters="Every listening service is reachable on that profile's networks, whether or not it was meant to be."; how_determined="Read Get-NetFirewallProfile; one or more profiles had Enabled = False."; risk_of_inaction="A service opened by accident is immediately reachable."; remediation=@{summary="Enable the firewall for all profiles (Domain, Private, Public).";difficulty="low";expected_outcome="Inbound traffic is denied unless a rule allows it."}; observed=@{disabled_profiles=@($off|ForEach-Object{$_.Name})} }
  }
}

# --- 3. disk encryption (BitLocker on the system drive) --------------------------------
$bl = Get-BitLockerVolume -MountPoint $env:SystemDrive
if ($null -eq $bl) {
  Add-Obs @{ observation_id="obs-disk-encryption"; subject=@{kind="host";ref=$subject}; check="disk_encryption_at_rest"; severity="info"; severity_score=0.0; what_happened="Disk encryption could not be read (BitLocker needs an elevated PowerShell)."; why_it_matters="Whether the drive is encrypted was not established."; how_determined="Get-BitLockerVolume returned nothing.";risk_of_inaction="Unknown, and unknown is its own state.";remediation=@{summary="Run again as administrator.";difficulty="low";expected_outcome="Encryption state can be read."};observed=@{unmeasured=$true;fact="disk_encryption"} }
} elseif ($bl.ProtectionStatus -ne "On") {
  Add-Obs @{ observation_id="obs-disk-encryption"; subject=@{kind="host";ref=$subject}; check="disk_encryption_at_rest"; severity="medium"; severity_score=55.0; what_happened="The system drive $($env:SystemDrive) is not protected by BitLocker (status: $($bl.VolumeStatus))."; why_it_matters="Every access control on this machine is enforced by the running system. A disk read on another machine - a stolen or disposed laptop - is subject to none of them."; how_determined="Read Get-BitLockerVolume for the system drive; ProtectionStatus was not On."; risk_of_inaction="Anyone who obtains the drive reads everything on it."; remediation=@{summary="Turn on BitLocker for the system drive.";difficulty="medium";expected_outcome="A drive removed from this machine is unreadable without the key."}; observed=@{protection_status="$($bl.ProtectionStatus)";volume_status="$($bl.VolumeStatus)"} }
}

# --- 4. antivirus / real-time protection (Windows-specific) ----------------------------
$def = Get-MpComputerStatus
if ($null -ne $def) {
  if (-not ($def.AntivirusEnabled -and $def.RealTimeProtectionEnabled)) {
    Add-Obs @{ observation_id="obs-antivirus"; subject=@{kind="host";ref=$subject}; check="antivirus_protection"; severity="high"; severity_score=65.0; what_happened="Antivirus or real-time protection is off (antivirus: $($def.AntivirusEnabled), real-time: $($def.RealTimeProtectionEnabled))."; why_it_matters="With real-time protection off, malicious files are not inspected as they arrive."; how_determined="Read Get-MpComputerStatus."; risk_of_inaction="Malware can run without being caught on access."; remediation=@{summary="Turn on Microsoft Defender real-time protection, or confirm another AV is active.";difficulty="low";expected_outcome="Files are inspected as they are written and run."}; observed=@{antivirus_enabled=$def.AntivirusEnabled;realtime=$def.RealTimeProtectionEnabled} }
  } elseif ($def.AntivirusSignatureAge -gt 7) {
    Add-Obs @{ observation_id="obs-antivirus-age"; subject=@{kind="host";ref=$subject}; check="antivirus_signatures_current"; severity="medium"; severity_score=40.0; what_happened="Antivirus signatures are $($def.AntivirusSignatureAge) days old."; why_it_matters="Old signatures miss recent threats."; how_determined="Read Get-MpComputerStatus AntivirusSignatureAge."; risk_of_inaction="Newly known malware is not recognised."; remediation=@{summary="Update Defender signatures (Windows Security > Virus & threat protection > Check for updates).";difficulty="low";expected_outcome="Detection reflects current threats."}; observed=@{signature_age_days=$def.AntivirusSignatureAge} }
  }
}

# --- 5. remote desktop exposure (Windows analog of the SSH check) ----------------------
$deny = (Get-ItemProperty "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections).fDenyTSConnections
if ($deny -eq 0) {
  $nla = (Get-ItemProperty "HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp" -Name UserAuthentication).UserAuthentication
  Add-Obs @{ observation_id="obs-rdp"; subject=@{kind="host";ref=$subject}; check="remote_desktop_exposed"; severity="high"; severity_score=68.0; what_happened="Remote Desktop (RDP) is enabled$(if($nla -ne 1){' and Network Level Authentication is off'} )."; why_it_matters="RDP accepts logins over the network; exposed to the internet it is a constant target for credential guessing."; how_determined="Read fDenyTSConnections (and NLA) from the Terminal Server registry keys."; risk_of_inaction="Remote access is open to guessing and known RDP flaws."; remediation=@{summary="Turn RDP off if unused; if needed, require Network Level Authentication and never expose it directly to the internet.";difficulty="medium";expected_outcome="Remote logins are limited and authenticated before a session starts."}; observed=@{rdp_enabled=$true;nla=$nla} }
}

# --- output: posture.json + report.html + console ---------------------------------------
$out = Join-Path (Get-Location) "aqelyn-scan"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$order = @{ critical=0; high=1; medium=2; low=3; info=4 }
$sorted = @($obs | Sort-Object @{ Expression = { $order[$_.severity] } })
(@{ observations = $sorted } | ConvertTo-Json -Depth 6) | Set-Content -Path (Join-Path $out "posture.json") -Encoding UTF8

$colors = @{ critical="#c62828"; high="#e08a00"; medium="#0b6fc4"; low="#657790"; info="#657790" }
$when = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm 'UTC'")
$cards = ""
foreach ($o in $sorted) {
  $c = $colors[$o.severity]; $fix = $o.remediation.summary
  $cards += "<article class='f'><div class='sv' style='--c:$c'>$($o.severity.ToUpper())</div><div><h3>$((HtmlEnc $o.what_happened))</h3><p class='w'>$((HtmlEnc $o.why_it_matters))</p><p class='d'>Determined by: $((HtmlEnc $o.how_determined))</p>$(if($fix){"<p class='fix'>Fix: $((HtmlEnc $fix))</p>"})</div></article>`n"
}
if (-not $cards) { $cards = "<p>Nothing was flagged.</p>" }
$report = @"
<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>AQELYN self-scan - $subject</title><style>
 body{margin:0;background:#060b15;color:#e7eef8;font:15px/1.6 system-ui,Segoe UI,Arial,sans-serif}
 .top{background:linear-gradient(160deg,#0b2440,#04182e);padding:26px 22px;border-bottom:2px solid #0b8ce0}
 .top h1{margin:0;font-size:22px} .top p{margin:4px 0 0;color:#8fb2d2;font-size:13px}
 main{max-width:820px;margin:0 auto;padding:22px}
 .f{display:grid;grid-template-columns:96px 1fr;gap:14px;padding:16px;border:1px solid #1e2f49;border-radius:10px;background:#0d1626;margin-bottom:12px}
 .sv{font:700 10px/1.7 ui-monospace,monospace;letter-spacing:.08em;color:var(--c);border:1px solid var(--c);border-radius:100px;text-align:center;padding:2px 0;align-self:start}
 h3{margin:0 0 5px;font-size:15.5px} .w{margin:0 0 6px;color:#aab9d0;font-size:13.5px}
 .d{margin:0;color:#7e8fa8;font-size:12px;font-family:ui-monospace,monospace} .fix{margin:8px 0 0;color:#3fc169;font-size:13px}
 footer{max-width:820px;margin:0 auto;padding:0 22px 30px;color:#7e8fa8;font-size:12.5px}
</style></head><body>
<div class='top'><h1>AQELYN self-scan - $subject</h1><p>$osName - $($sorted.Count) observations - $when - read-only, nothing left this machine</p></div>
<main>$cards</main>
<footer>Produced by the AQELYN Windows collector. Run again from an elevated PowerShell to read BitLocker and Defender. This report was generated entirely on your machine.</footer>
</body></html>
"@
Set-Content -Path (Join-Path $out "report.html") -Value $report -Encoding UTF8

Write-Host ""
Write-Host "  AQELYN self-scan - $subject"
Write-Host "  ============================================"
foreach ($o in $sorted) { Write-Host ("  [{0,-8}] {1}" -f $o.severity.ToUpper(), $o.what_happened) }
Write-Host ""
Write-Host "  Read-only. Nothing was sent anywhere."
Write-Host "  Findings : $(Join-Path $out 'posture.json')"
Write-Host "  Report   : open $(Join-Path $out 'report.html') in your browser"
Write-Host ""
