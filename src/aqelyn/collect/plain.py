"""Plain-language layer for the customer self-scan report.

Charter Principle 2 (Simplicity First): the output must be understandable by everyone,
non-technical included. The collector's observation text is written for an operator; this
maps each check to words a person with no security background can act on, and gives a
reassuring line for the checks that passed. The technical detail is kept — it just stops
being the first thing a customer reads.

Keyed by the ``check`` id each collector emits, so Linux and Windows share the wording.
"""

from __future__ import annotations

from typing import Any

# Friendly, non-alarmist severity words (Charter Principle 8: no scare language).
_SEVERITY_WORD = {
    "critical": "Fix this soon",
    "high": "Worth attention",
    "medium": "Worth improving",
    "low": "Minor",
    "info": "For information",
}


def severity_word(severity: str) -> str:
    return _SEVERITY_WORD.get(severity, "Note")


# For each check id: a plain headline + what it means + what to do (shown when it is a
# finding), and a short reassurance (shown when the check passed). Written for a person, not
# an admin. `good` is what a customer sees in the "Looking good" section.
PLAIN: dict[str, dict[str, str]] = {
    "listening_sockets_public": {
        "headline": "Some services on this computer can be reached over the network",
        "meaning": (
            "Programs on this computer are waiting for connections from other devices on the "
            "same network — not only from the computer itself. That is normal for things like "
            "file and printer sharing, but anything you do not actually use is safer turned off."
        ),
        "action": (
            "On a network you do not fully trust (a café, airport, or shared office), set that "
            "network to 'Public' in your settings. If you do not share files or printers from "
            "this computer, turn that sharing off."
        ),
        "good": "Nothing on this computer is needlessly open to the network.",
    },
    "host_firewall_active": {
        "headline": "The firewall is switched off",
        "meaning": (
            "A firewall turns away connections you did not ask for. With it off, other devices "
            "can reach services on this computer more freely."
        ),
        "action": "Switch the firewall on for every network type.",
        "good": "The firewall is on — it turns away connections you did not ask for.",
    },
    "disk_encryption_at_rest": {
        "headline": "The disk is not encrypted",
        "meaning": (
            "If this computer is lost or stolen, someone could take the drive out and read "
            "everything on it, because the files are not scrambled."
        ),
        "action": "Turn on disk encryption (BitLocker on Windows, or your system's encryption).",
        "good": (
            "The disk is encrypted — if the computer is lost or stolen, the files cannot be read."
        ),
    },
    "pending_package_updates": {
        "headline": "Some updates are waiting to be installed",
        "meaning": (
            "Updates fix flaws that are already public knowledge. Until they are installed, "
            "those flaws stay open on this computer."
        ),
        "action": "Install the pending updates.",
        "good": "The software is up to date.",
    },
    "automatic_security_updates": {
        "headline": "Security updates do not install by themselves",
        "meaning": (
            "If updates wait for someone to remember, they are often late. That gap is the time "
            "an attacker has to use a flaw that already has a fix."
        ),
        "action": "Turn on automatic security updates.",
        "good": "Security updates install themselves automatically.",
    },
    "ssh_password_authentication": {
        "headline": "This computer allows remote login with a password",
        "meaning": (
            "A password can be guessed at whatever speed the network allows; a key file cannot. "
            "Allowing password login over the network is a common way in for attackers."
        ),
        "action": "Use key files for remote login, and turn password login off.",
        "good": "Remote login does not accept guessable passwords.",
    },
    "antivirus_protection": {
        "headline": "Antivirus or real-time protection is off",
        "meaning": (
            "With real-time protection off, harmful files are not checked as they arrive, so "
            "malware can run without being caught."
        ),
        "action": (
            "Turn Microsoft Defender real-time protection on, or confirm another antivirus "
            "is active."
        ),
        "good": "Antivirus is on and watching for harmful files.",
    },
    "antivirus_signatures_current": {
        "headline": "Antivirus is out of date",
        "meaning": "Old antivirus data misses threats discovered since it was last updated.",
        "action": "Update your antivirus (check for updates in Windows Security).",
        "good": "Antivirus data is up to date.",
    },
    "remote_desktop_exposed": {
        "headline": "Remote Desktop is switched on",
        "meaning": (
            "Remote Desktop lets someone log in to this computer over the network. Left open, "
            "it is a constant target for people guessing passwords."
        ),
        "action": (
            "Turn Remote Desktop off if you do not use it; if you need it, do not expose it to "
            "the internet."
        ),
        "good": "Remote Desktop is off — nobody can log in to this computer over the network.",
    },
}

_FALLBACK = {
    "headline": "Something needs a look",
    "meaning": "A security check reported something worth reviewing.",
    "action": "Review this item.",
    "good": "This check passed.",
}


def plain_for(check: str) -> dict[str, str]:
    return PLAIN.get(check, _FALLBACK)


# The check ids the Linux collector can emit (used to compute which checks passed — a check
# that produced no observation passed). Kept in sync with checks.py by test_selfscan.
LINUX_CHECK_IDS: tuple[str, ...] = (
    "listening_sockets_public",
    "host_firewall_active",
    "pending_package_updates",
    "automatic_security_updates",
    "disk_encryption_at_rest",
    "ssh_password_authentication",
)


# --- Norwegian (bokmål) -----------------------------------------------------------------
# Charter Principle 2 applies in the reader's language. Auto-selected from the computer's
# locale; English is the fallback. Same keys as PLAIN, so the renderer is language-agnostic.
PLAIN_NB: dict[str, dict[str, str]] = {
    "listening_sockets_public": {
        "headline": "Noen tjenester på denne datamaskinen kan nås over nettverket",
        "meaning": (
            "Programmer på denne datamaskinen venter på tilkoblinger fra andre enheter på samme "
            "nettverk — ikke bare fra datamaskinen selv. Det er normalt for ting som fil- og "
            "skriverdeling, men alt du ikke faktisk bruker er tryggere slått av."
        ),
        "action": (
            "På et nettverk du ikke stoler helt på (en kafé, flyplass eller delt kontor), sett "
            "det nettverket til 'Offentlig' i innstillingene. Slå av fil- og skriverdeling hvis "
            "du ikke deler filer eller skrivere fra denne datamaskinen."
        ),
        "good": "Ingenting på denne datamaskinen er unødvendig åpent mot nettverket.",
    },
    "host_firewall_active": {
        "headline": "Brannmuren er slått av",
        "meaning": (
            "En brannmur avviser tilkoblinger du ikke ba om. Med den av kan andre enheter nå "
            "tjenester på denne datamaskinen lettere."
        ),
        "action": "Slå på brannmuren for alle nettverkstyper.",
        "good": "Brannmuren er på — den avviser tilkoblinger du ikke ba om.",
    },
    "disk_encryption_at_rest": {
        "headline": "Disken er ikke kryptert",
        "meaning": (
            "Hvis datamaskinen blir mistet eller stjålet, kan noen ta ut disken og lese alt på "
            "den, fordi filene ikke er kryptert."
        ),
        "action": "Slå på diskkryptering (BitLocker på Windows, eller systemets kryptering).",
        "good": "Disken er kryptert — hvis maskinen mistes eller stjeles, kan ikke filene leses.",
    },
    "pending_package_updates": {
        "headline": "Noen oppdateringer venter på å bli installert",
        "meaning": (
            "Oppdateringer tetter feil som allerede er offentlig kjent. Til de er installert står "
            "de feilene åpne på denne datamaskinen."
        ),
        "action": "Installer oppdateringene som venter.",
        "good": "Programvaren er oppdatert.",
    },
    "automatic_security_updates": {
        "headline": "Sikkerhetsoppdateringer installeres ikke av seg selv",
        "meaning": (
            "Hvis oppdateringer venter på at noen skal huske dem, kommer de ofte for sent. Det "
            "gapet er tiden en angriper har til å bruke en feil som allerede har en rettelse."
        ),
        "action": "Slå på automatiske sikkerhetsoppdateringer.",
        "good": "Sikkerhetsoppdateringer installeres automatisk.",
    },
    "ssh_password_authentication": {
        "headline": "Denne datamaskinen tillater fjerninnlogging med passord",
        "meaning": (
            "Et passord kan gjettes så raskt nettverket tillater; en nøkkelfil kan ikke. Å "
            "tillate passordinnlogging over nettverket er en vanlig vei inn for angripere."
        ),
        "action": "Bruk nøkkelfiler for fjerninnlogging, og slå av passordinnlogging.",
        "good": "Fjerninnlogging godtar ikke passord som kan gjettes.",
    },
    "antivirus_protection": {
        "headline": "Antivirus eller sanntidsbeskyttelse er av",
        "meaning": (
            "Med sanntidsbeskyttelse av blir ikke skadelige filer sjekket når de kommer inn, så "
            "skadevare kan kjøre uten å bli oppdaget."
        ),
        "action": (
            "Slå på sanntidsbeskyttelse i Microsoft Defender, eller bekreft at et annet "
            "antivirus er aktivt."
        ),
        "good": "Antivirus er på og følger med på skadelige filer.",
    },
    "antivirus_signatures_current": {
        "headline": "Antivirus er utdatert",
        "meaning": "Gamle antivirusdata går glipp av trusler oppdaget siden sist oppdatering.",
        "action": "Oppdater antiviruset ditt (se etter oppdateringer i Windows-sikkerhet).",
        "good": "Antivirusdata er oppdatert.",
    },
    "remote_desktop_exposed": {
        "headline": "Eksternt skrivebord (Remote Desktop) er slått på",
        "meaning": (
            "Eksternt skrivebord lar noen logge inn på denne datamaskinen over nettverket. Stående "
            "åpent er det et stadig mål for folk som gjetter passord."
        ),
        "action": (
            "Slå av Eksternt skrivebord hvis du ikke bruker det; trenger du det, ikke "
            "eksponer det mot internett."
        ),
        "good": (
            "Eksternt skrivebord er av — ingen kan logge inn på denne datamaskinen over "
            "nettverket."
        ),
    },
}

# Fixed UI text (section titles, labels) per language.
UI: dict[str, dict[str, Any]] = {
    "en": {
        "title": "Security check",
        "worth": "Worth a look",
        "good": "Looking good",
        "unknown": "Could not check",
        "action": "What to do:",
        "detail": "Show the technical detail",
        "readonly": "read-only, nothing left this computer",
        "s_good": "looking good",
        "s_worth": "worth a look",
        "s_unknown": "could not check",
        "cannot": "Could not check",
        "runadmin": "Run with more permission (administrator, or sudo) to read it.",
        "footer": (
            "This check only reads how your computer is set up — it changes nothing and sends "
            "nothing anywhere. The report was made entirely on your machine."
        ),
        "console_title": "AQELYN security check",
        "console_clean": "Nothing needs attention right now.",
        "severity": _SEVERITY_WORD,
    },
    "nb": {
        "title": "Sikkerhetssjekk",
        "worth": "Verdt å se på",
        "good": "Ser bra ut",
        "unknown": "Kunne ikke sjekke",
        "action": "Hva du bør gjøre:",
        "detail": "Vis tekniske detaljer",
        "readonly": "kun lesing, ingenting forlot denne datamaskinen",
        "s_good": "ser bra ut",
        "s_worth": "verdt å se på",
        "s_unknown": "kunne ikke sjekke",
        "cannot": "Kunne ikke sjekke",
        "runadmin": "Kjør med mer tilgang (administrator, eller sudo) for å lese den.",
        "footer": (
            "Denne sjekken leser bare hvordan datamaskinen din er satt opp — den endrer "
            "ingenting og sender ingenting noe sted. Rapporten ble laget helt på din maskin."
        ),
        "console_title": "AQELYN sikkerhetssjekk",
        "console_clean": "Ingenting trenger oppmerksomhet akkurat nå.",
        "severity": {
            "critical": "Rett snarest",
            "high": "Verdt oppmerksomhet",
            "medium": "Verdt å forbedre",
            "low": "Mindre",
            "info": "Til informasjon",
        },
    },
}


def pick_language(locale: str | None) -> str:
    """'nb' for a Norwegian locale, else 'en'. Fallback is always English."""

    low = (locale or "").lower()
    return "nb" if (low.startswith("nb") or low.startswith("nn") or low.startswith("no")) else "en"


def texts(lang: str) -> dict[str, dict[str, str]]:
    return PLAIN_NB if lang == "nb" else PLAIN


def plain_for_lang(check: str, lang: str) -> dict[str, str]:
    return texts(lang).get(check, _FALLBACK)
