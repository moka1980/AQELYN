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
function HtmlEnc($s) { if ($null -eq $s) { return "" }; return ([string]$s).Replace("&","&amp;").Replace("<","&lt;").Replace(">","&gt;").Replace([string][char]34,"&quot;") }

# Plain-language layer (Charter Principle 2) - mirrors src/aqelyn/collect/plain.py.
$SEVWORD = @{ critical="Fix this soon"; high="Worth attention"; medium="Worth improving"; low="Minor"; info="For information" }
$WINDOWS_CHECK_IDS = @("listening_sockets_public","host_firewall_active","disk_encryption_at_rest","antivirus_protection","remote_desktop_exposed")
$PLAIN = @{
  listening_sockets_public = @{ headline="Some services on this computer can be reached over the network"; meaning="Programs on this computer are waiting for connections from other devices on the same network - not only from the computer itself. That is normal for things like file and printer sharing, but anything you do not actually use is safer turned off."; action="On a network you do not fully trust (a cafe, airport, or shared office), set that network to Public in your settings. If you do not share files or printers from this computer, turn that sharing off."; good="Nothing on this computer is needlessly open to the network." }
  host_firewall_active = @{ headline="The firewall is switched off"; meaning="A firewall turns away connections you did not ask for. With it off, other devices can reach services on this computer more freely."; action="Switch the firewall on for every network type."; good="The firewall is on - it turns away connections you did not ask for." }
  disk_encryption_at_rest = @{ headline="The disk is not encrypted"; meaning="If this computer is lost or stolen, someone could take the drive out and read everything on it, because the files are not scrambled."; action="Turn on disk encryption (BitLocker)."; good="The disk is encrypted - if the computer is lost or stolen, the files cannot be read." }
  antivirus_protection = @{ headline="Antivirus or real-time protection is off"; meaning="With real-time protection off, harmful files are not checked as they arrive, so malware can run without being caught."; action="Turn Microsoft Defender real-time protection on, or confirm another antivirus is active."; good="Antivirus is on and watching for harmful files." }
  antivirus_signatures_current = @{ headline="Antivirus is out of date"; meaning="Old antivirus data misses threats discovered since it was last updated."; action="Update your antivirus (check for updates in Windows Security)."; good="Antivirus data is up to date." }
  remote_desktop_exposed = @{ headline="Remote Desktop is switched on"; meaning="Remote Desktop lets someone log in to this computer over the network. Left open, it is a constant target for people guessing passwords."; action="Turn Remote Desktop off if you do not use it; if you need it, do not expose it to the internet."; good="Remote Desktop is off - nobody can log in to this computer over the network." }
}
$lang = if ((Get-Culture).TwoLetterISOLanguageName -in @('nb','nn','no')) { 'nb' } else { 'en' }
$PLAIN_NB = @{
  listening_sockets_public = @{ headline="Noen tjenester på denne datamaskinen kan nås over nettverket"; meaning="Programmer på denne datamaskinen venter på tilkoblinger fra andre enheter på samme nettverk - ikke bare fra datamaskinen selv. Det er normalt for ting som fil- og skriverdeling, men alt du ikke faktisk bruker er tryggere slått av."; action="På et nettverk du ikke stoler helt på (en kafe, flyplass eller delt kontor), sett det nettverket til Offentlig i innstillingene. Slå av fil- og skriverdeling hvis du ikke deler filer eller skrivere fra denne datamaskinen."; good="Ingenting på denne datamaskinen er unødvendig åpent mot nettverket." }
  host_firewall_active = @{ headline="Brannmuren er slått av"; meaning="En brannmur avviser tilkoblinger du ikke ba om. Med den av kan andre enheter nå tjenester på denne datamaskinen lettere."; action="Slå på brannmuren for alle nettverkstyper."; good="Brannmuren er på - den avviser tilkoblinger du ikke ba om." }
  disk_encryption_at_rest = @{ headline="Disken er ikke kryptert"; meaning="Hvis datamaskinen blir mistet eller stjålet, kan noen ta ut disken og lese alt på den, fordi filene ikke er kryptert."; action="Slå på diskkryptering (BitLocker)."; good="Disken er kryptert - hvis maskinen mistes eller stjeles, kan ikke filene leses." }
  antivirus_protection = @{ headline="Antivirus eller sanntidsbeskyttelse er av"; meaning="Med sanntidsbeskyttelse av blir ikke skadelige filer sjekket når de kommer inn, så skadevare kan kjøre uten å bli oppdaget."; action="Slå på sanntidsbeskyttelse i Microsoft Defender, eller bekreft at et annet antivirus er aktivt."; good="Antivirus er på og følger med på skadelige filer." }
  antivirus_signatures_current = @{ headline="Antivirus er utdatert"; meaning="Gamle antivirusdata går glipp av trusler oppdaget siden sist oppdatering."; action="Oppdater antiviruset ditt (se etter oppdateringer i Windows-sikkerhet)."; good="Antivirusdata er oppdatert." }
  remote_desktop_exposed = @{ headline="Eksternt skrivebord er slått på"; meaning="Eksternt skrivebord lar noen logge inn på denne datamaskinen over nettverket. Stående åpent er det et stadig mål for folk som gjetter passord."; action="Slå av Eksternt skrivebord hvis du ikke bruker det; trenger du det, ikke eksponer det mot internett."; good="Eksternt skrivebord er av - ingen kan logge inn på denne datamaskinen over nettverket." }
}
$UI = @{
  en = @{ title="Security check"; worth="Worth a look"; good="Looking good"; unknown="Could not check"; action="What to do:"; detail="Show the technical detail"; readonly="read-only, nothing left this computer"; s_good="looking good"; s_worth="worth a look"; s_unknown="could not check"; cannot="Could not check"; runadmin="Run as administrator to read it."; footer="$($U.footer)"; console="AQELYN security check"; clean="Nothing needs attention right now."; sev=@{critical="Fix this soon";high="Worth attention";medium="Worth improving";low="Minor";info="For information"} }
  nb = @{ title="Sikkerhetssjekk"; worth="Verdt å se på"; good="Ser bra ut"; unknown="Kunne ikke sjekke"; action="Hva du bør gjøre:"; detail="Vis tekniske detaljer"; readonly="kun lesing, ingenting forlot denne datamaskinen"; s_good="ser bra ut"; s_worth="verdt å se på"; s_unknown="kunne ikke sjekke"; cannot="Kunne ikke sjekke"; runadmin="Kjør som administrator for å lese den."; footer="Denne sjekken leser bare hvordan datamaskinen din er satt opp - den endrer ingenting og sender ingenting noe sted. Rapporten ble laget helt på din maskin."; console="AQELYN sikkerhetssjekk"; clean="Ingenting trenger oppmerksomhet akkurat nå."; sev=@{critical="Rett snarest";high="Verdt oppmerksomhet";medium="Verdt å forbedre";low="Mindre";info="Til informasjon"} }
}
$U = $UI[$lang]
function Plain($id) { $tbl = if ($lang -eq 'nb') { $PLAIN_NB } else { $PLAIN }; if ($tbl.ContainsKey($id)) { return $tbl[$id] } return @{ headline="Something needs a look"; meaning="A security check reported something worth reviewing."; action="Review this item."; good="This check passed." } }


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

# --- output: posture.json (technical) + plain-language report.html + console -----------
$out = Join-Path (Get-Location) "aqelyn-scan"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$order = @{ critical=0; high=1; medium=2; low=3; info=4 }
$sorted = @($obs | Sort-Object @{ Expression = { $order[$_.severity] } })
(@{ observations = $sorted } | ConvertTo-Json -Depth 6) | Set-Content -Path (Join-Path $out "posture.json") -Encoding UTF8

$findings = @($sorted | Where-Object { -not $_.observed.unmeasured })
$unknown  = @($sorted | Where-Object { $_.observed.unmeasured })
$seen     = @($sorted | ForEach-Object { $_.check })
$passed   = @($WINDOWS_CHECK_IDS | Where-Object { $seen -notcontains $_ })
$colors = @{ critical="#c62828"; high="#e08a00"; medium="#0b6fc4"; low="#657790"; info="#657790" }
$when = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm 'UTC'")

$sections = ""
if ($findings.Count) {
  $sections += "<h2>$($U.worth)</h2>"
  foreach ($o in $findings) {
    $p = Plain $o.check; $c = $colors[$o.severity]
    $tech = HtmlEnc ("" + $o.what_happened + "  Determined by: " + $o.how_determined)
    $sections += "<article class='card'><span class='chip' style='--c:$c'>$(HtmlEnc $U.sev[$o.severity])</span><p class='hl'>$(HtmlEnc $p.headline)</p><p class='mean'>$(HtmlEnc $p.meaning)</p><p class='act'><b>$($U.action)</b> $(HtmlEnc $p.action)</p><details><summary>$($U.detail)</summary><p class='tech'>$tech</p></details></article>"
  }
}
if ($passed.Count) {
  $sections += "<h2>$($U.good)</h2>"
  foreach ($id in $passed) { $p = Plain $id; $sections += "<article class='card good'><span class='tick'>&#10003;</span><span>$(HtmlEnc $p.good)</span></article>" }
}
if ($unknown.Count) {
  $sections += "<h2>$($U.unknown)</h2>"
  foreach ($o in $unknown) { $p = Plain $o.check; $sections += "<article class='card good'><span class='g3'>&#8226;</span><span class='g3'>$($U.cannot): $(HtmlEnc ($p.headline.ToLower())). $($U.runadmin)</span></article>" }
}
if (-not $sections) { $sections = "<p>Nothing to report.</p>" }
$ucount = if ($unknown.Count) { "<span class='u'>$($unknown.Count) $($U.s_unknown)</span>" } else { "" }
$summary = "<div class='sum'><span class='g'>$($passed.Count) $($U.s_good)</span><span class='a'>$($findings.Count) $($U.s_worth)</span>$ucount</div>"

$report = @"
<!doctype html><html lang='$lang'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>AQELYN - $($U.title) - $subject</title><style>
 body{margin:0;background:#060b15;color:#e7eef8;font:15px/1.6 system-ui,Segoe UI,Arial,sans-serif}
 .top{background:linear-gradient(160deg,#0b2440,#04182e);padding:26px 22px;border-bottom:2px solid #0b8ce0}
 .top h1{margin:0;font-size:23px} .top p{margin:6px 0 0;color:#8fb2d2;font-size:13.5px}
 .sum{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
 .sum span{font-size:12.5px;font-weight:700;padding:5px 12px;border-radius:100px}
 .sum .g{background:#0d2a1a;color:#3fc169} .sum .a{background:#2c2410;color:#eeae4a} .sum .u{background:#131f34;color:#8fb2d2}
 main{max-width:780px;margin:0 auto;padding:22px}
 h2{font-size:14px;letter-spacing:.04em;color:#8fb2d2;text-transform:uppercase;margin:26px 0 12px}
 .card{border:1px solid #1e2f49;border-radius:12px;background:#0d1626;padding:18px;margin-bottom:12px}
 .card.good{display:flex;gap:11px;align-items:flex-start;padding:14px 16px}
 .tick{color:#3fc169;font-weight:800;font-size:16px}
 .chip{font:700 10.5px/1.7 system-ui;letter-spacing:.05em;text-transform:uppercase;padding:2px 10px;border-radius:100px;color:var(--c);border:1px solid var(--c)}
 .hl{font-size:16.5px;font-weight:700;margin:10px 0 6px} .mean{color:#c7d4e6;margin:0 0 10px}
 .act{margin:0} .act b{color:#3fc169}
 details{margin-top:12px;border-top:1px solid #1e2f49;padding-top:10px} summary{cursor:pointer;color:#7e8fa8;font-size:12.5px}
 .tech{color:#7e8fa8;font-size:12px;font-family:ui-monospace,monospace;margin:8px 0 0;white-space:pre-wrap}
 .g3{color:#9fb0c6;font-size:13px}
 footer{max-width:780px;margin:0 auto;padding:6px 22px 30px;color:#7e8fa8;font-size:12.5px}
</style></head><body>
<div class='top'><h1>$($U.title) - $subject</h1><p>$osName - $when - $($U.readonly)</p>$summary</div>
<main>$sections</main>
<footer>$($U.footer)</footer>
</body></html>
"@
Set-Content -Path (Join-Path $out "report.html") -Value $report -Encoding UTF8

Write-Host ""
Write-Host "  $($U.console) - $subject"
Write-Host "  ============================================"
if (-not $findings.Count) { Write-Host "  $($U.clean)" }
foreach ($o in $findings) { $p = Plain $o.check; Write-Host ("  [{0,-16}] {1}" -f $U.sev[$o.severity], $p.headline) }
Write-Host ""
Write-Host "  Read-only. Nothing was sent anywhere."
Write-Host "  Report: open $(Join-Path $out 'report.html') in your browser"
Write-Host ""
