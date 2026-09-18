# Norli stock watch

Overvåker lagerstatus på [norli.no](https://www.norli.no) og sender push-varsel til mobilen
via [ntfy](https://ntfy.sh) i det øyeblikket varen kommer i beholdning.

Overvåkes nå: **Pokémon 30th Celebration Elite Trainer Box** (SKU `0196214144828`, 1099 kr).

## Hvorfor dette ikke kjører i GitHub Actions

Planen var å kjøre sjekken i skyen på GitHub Actions. Det går ikke: **Norli svarer `403 Forbidden`
på alt som kommer fra GitHubs servere.** Det gjelder ikke bare API-kall — et helt vanlig GET-kall
på produktsiden får også 403. Blokkeringen er IP-basert (Azure/datasenter, utenfor Norge), ikke
noe som lar seg løse med User-Agent eller andre headere.

Derfor kjører sjekken i stedet som en `launchd`-jobb på Mac-en, som har norsk IP.
Workflowen ligger igjen i `.github/workflows/norli.yml`, men er deaktivert — den kan slås på
igjen hvis jobben en gang skal kjøre fra en vert med norsk IP.

## Hvorfor GraphQL og ikke tekstsøk i HTML-en

Produktsiden rendres i nettleseren. Rå HTML inneholder ingen lagertekst i det hele tatt —
verken «Forventes i salg» eller «Legg i handlekurv». Et script som varsler når «Forventes i salg»
*forsvinner* ville derfor slått ut som falskt positivt allerede ved første kjøring.

Scriptet spør i stedet Norlis Magento-GraphQL-endepunkt (`https://www.norli.no/graphql`) om feltet
`stock_status` — strukturerte data fra samme kilde som nettbutikken selv bruker.

## Oppsett

1. Installer ntfy-appen ([iOS](https://apps.apple.com/us/app/ntfy/id1625396347) /
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)) og abonner på topicet.
   Topicet er hele hemmeligheten — hvem som helst som kjenner navnet kan lese varslene dine.
2. Installer jobben:

   ```bash
   ./install.sh <ntfy-topic>
   ```

| Kommando | Hva den gjør |
|---|---|
| `launchctl list \| grep norli` | Ser om jobben lever |
| `tail -f ~/Library/Logs/norli-stock-watch/out.log` | Følger sjekkene |
| `NTFY_TOPIC=<topic> python3 check_norli.py` | Kjører én sjekk manuelt |
| `./install.sh --uninstall` | Skrur av overvåkingen |

## Varsling

- **Ved overgang utsolgt → på lager:** varsel med `urgent`-prioritet, som ringer gjennom
  stillemodus på de fleste telefoner. Trykk på varselet for å gå rett til produktsiden.
- **Mens varen fortsatt er på lager:** ett nytt ping hver 6. time, ikke hvert 5. minutt.
  Juster med `REPING_HOURS` i `check_norli.py`.
- **Hvis oppslaget feiler:** ett varsel per sammenhengende feilperiode, så nedetid hos Norli
  ikke spammer telefonen.

`state.json` holder forrige status lokalt og er utenfor git.

## Overvåke flere varer

Legg EAN-koden (tallet bakerst i produkt-URL-en) inn i `SKUS` i `check_norli.py`:

```python
SKUS = ["0196214144828", "0196214145528"]
```

## Forbehold

- **Macen må være våken.** Sover den, står sjekkene stille til den vekkes. `launchd` kjører
  jobben ved oppvåkning. Skal den overleve en lukket laptop, må den kjøre fra noe som står på
  hele døgnet — og det må ha norsk IP, se blokkeringen over.
- **Husk å skru av** når du har handlet: `./install.sh --uninstall`.
