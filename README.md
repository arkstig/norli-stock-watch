# Norli stock watch

Overvåker lagerstatus på [norli.no](https://www.norli.no) og sender push-varsel til mobilen
via [ntfy](https://ntfy.sh) i det øyeblikket varen kommer i beholdning.

Overvåkes nå: **Pokémon 30th Celebration Elite Trainer Box** (SKU `0196214144828`, 1099 kr).

## Slik virker det

GitHub Actions kjører `check_norli.py` hvert 5. minutt. Scriptet spør Norlis
Magento-GraphQL-endepunkt (`https://www.norli.no/graphql`) om feltet `stock_status`
og varsler når det går fra `OUT_OF_STOCK` til `IN_STOCK`.

**Hvorfor GraphQL og ikke tekstsøk i HTML-en?** Produktsiden rendres i nettleseren.
Rå HTML fra `curl` inneholder ingen lagertekst i det hele tatt — verken «Forventes i salg»
eller «Legg i handlekurv». Et script som varsler når «Forventes i salg» *forsvinner* ville
derfor slått ut som falskt positivt allerede ved første kjøring. GraphQL-feltet er
strukturerte data fra samme kilde som nettbutikken selv bruker.

## Varsling

- **Ved overgang utsolgt → på lager:** varsel med `urgent`-prioritet (ringer gjennom
  stillemodus på de fleste telefoner). Trykk på varselet for å gå rett til produktsiden.
- **Mens varen fortsatt er på lager:** ett nytt ping hver 6. time, ikke hvert 5. minutt.
  Juster med `REPING_HOURS` i `check_norli.py`.
- **Hvis oppslaget feiler:** ett varsel per sammenhengende feilperiode, så nedetid hos
  Norli ikke spammer telefonen. GitHub sender i tillegg e-post om feilende kjøringer.

`state.json` holder forrige status og commites tilbake til repoet kun når noe faktisk endrer seg.

## Oppsett

1. Installer ntfy-appen ([iOS](https://apps.apple.com/us/app/ntfy/id1625396347) /
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)) og abonner på topicet
   som ligger i repo-secreten `NTFY_TOPIC`. Topicet er hemmeligheten — hvem som helst som kjenner
   navnet kan lese varslene dine.
2. Repoet må være **offentlig** for ubegrensede Actions-minutter. Et privat repo ville brukt opp
   gratiskvoten på under en uke med kjøring hvert 5. minutt.

## Overvåke flere varer

Legg EAN-koden (tallet bakerst i produkt-URL-en) inn i `SKUS` i `check_norli.py`:

```python
SKUS = ["0196214144828", "0196214145528"]
```

## Forbehold

- **Timing:** GitHubs cron er «best effort» og kjører sjelden helt presist. Regn med
  5–20 minutter mellom hver reelle kjøring i travle perioder. For en ettertraktet vare som
  selges ut på minutter er ikke dette en garanti — men det er raskere enn å sjekke selv.
- **60-dagersregelen:** GitHub deaktiverer planlagte workflows i repoer uten aktivitet på
  60 dager. Push en endring, eller trykk «Run workflow», innimellom hvis varen er langt unna.
- **Husk å skru av** workflowen når du har handlet — Actions-fanen → Norli stock watch →
  `...` → Disable workflow.
