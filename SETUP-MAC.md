# Sette opp på en Mac som står på hele tiden

Tenkt for en gammel maskin som får stå i fred — for eksempel en MacBook Pro med ødelagt skjerm,
koblet til strøm og nett. Den trenger ikke fungerende skjerm etter at oppsettet er gjort.

Regn med 15 minutter.

---

## 1. Forberedelser på den gamle Macen

Koble til **strøm** og **nett**. Kablet nett er å foretrekke — Wi-Fi kan falle ut etter en
oppstart uten at noen oppdager det.

Åpne Terminal og sjekk at Python finnes:

```bash
python3 --version
```

Får du «command not found», installer utviklingsverktøyene og prøv igjen:

```bash
xcode-select --install
```

Versjon 3.7 eller nyere holder. Systemets egen Python er god nok — du trenger ikke installere noe fra Homebrew.

## 2. Hent koden

```bash
cd ~
git clone https://github.com/arkstig/norli-stock-watch.git
cd norli-stock-watch
```

Mangler `git`, kommer den med `xcode-select --install` i steget over.

## 3. Installer

Bruk **samme ntfy-topic** som i dag, så havner varslene i samme kanal i appen:

```bash
./install.sh <ntfy-topic> --always-on
```

`--always-on` ber om administratorpassordet og setter tre ting:

| Innstilling | Hva den gjør |
|---|---|
| `sleep 0` | maskinen sovner aldri når den står i strøm |
| `disablesleep 1` | den holder seg våken med lokket lukket, uten ekstern skjerm |
| `autorestart 1` | den starter igjen av seg selv etter strømbrudd |

## 4. Slå på automatisk innlogging

**Dette steget er lett å glemme, og uten det stopper alt ved første omstart.** Jobben kjører som
en brukerjobb, og brukeren må være logget inn for at den skal starte.

Systeminnstillinger → **Brukere og grupper** → Automatisk innlogging → velg brukeren din.

Krever at FileVault er slått av. Er FileVault på, må noen skrive passordet ved hver oppstart —
og da nytter ikke automatisk innlogging.

## 5. Sjekk at det virker

```bash
launchctl list | grep norli                          # skal vise jobben
tail -f ~/Library/Logs/norli-stock-watch/out.log     # en linje hvert 3. minutt
python3 check_stock.py --targets                     # alle 68 mål med status
```

Du skal få et stille livstegn i ntfy-appen innen en halvtime. Kommer det, er oppsettet ferdig.

## 6. Skru av på den gamle maskinen din

Ellers sjekker to maskiner det samme, og du får varslene dobbelt:

```bash
cd ~/Customers/norli-stock-watch && ./install.sh --uninstall
```

## 7. Test at den overlever en omstart

Verdt de to minuttene, for dette er det som faktisk feiler i praksis:

```bash
sudo reboot
```

Etter oppstart skal maskinen logge seg inn selv, og det skal komme nye linjer i loggen uten at du
gjør noe. Skjer det ikke, er automatisk innlogging (steg 4) nesten alltid årsaken.

---

## Etterpå

Lukk lokket og sett maskinen vekk. Den trenger bare strøm og nett.

**Slik vet du at den lever:** livstegnet i ntfy hver halvtime. Slutter det å komme, står
overvåkingen — sjekk strøm og nett.

**Endre hva som overvåkes:** rediger `check_stock.py` på den maskinen, eller push til GitHub og
kjør `git pull` der. Jobben plukker opp endringen ved neste kjøring, uten omstart.

**Hvis maskinen sovner likevel:** noen eldre modeller ignorerer `disablesleep` med lokket lukket.
Hold da lokket åpent — skjermen trenger ikke virke. Sjekk innstillingene med:

```bash
pmset -g custom
```
