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

## Hva som overvåkes

To ting, uavhengig av hverandre:

| | Felt | Hvorfor det er skilt |
|---|---|---|
| **Nettlager** | `products.stock_status` | Kan kjøpes og sendes hjem |
| **25 butikker** (klikk og hent) | `pickupStores → products.qty_in_store` | Varen kan ligge i butikk uten å være kjøpbar på nett |

Skillet er ikke teoretisk: 18. september viste siden «Ikke tilgjengelig på nettlager» samtidig
som den var «På lager hos 1 butikker». Overvåker du bare `stock_status`, går du glipp av
nettopp de tilfellene.

Butikkene som overvåkes er de tre i Fredrikstad (`WATCHED_STORES`) og alle i Oslo
(`WATCHED_REGIONS`). Se hele listen med butikk-ID-er:

```bash
python3 check_norli.py --stores      # * = overvåkes
```

Merk at `all_in_stock` **ikke** er nok alene — antallet ligger i `products.qty_in_store`.

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

- **Når noe blir tilgjengelig:** varsel med `urgent`-prioritet, som ringer gjennom stillemodus
  på de fleste telefoner. Varselet navngir hvilken butikk og hvor mange. Trykk for å gå rett
  til produktsiden. Nettlager og hver enkelt butikk varsles hver for seg, så et varsel om én
  butikk ikke skjuler et varsel om en annen.
- **Mens varen fortsatt er på lager:** ett nytt ping hver 6. time, ikke hvert 5. minutt.
  Juster med `REPING_HOURS` i `check_norli.py`.
- **Hvis oppslaget feiler:** ett varsel per sammenhengende feilperiode, så nedetid hos Norli
  ikke spammer telefonen.
- **Livstegn hver 30. minutt** med `min`-prioritet — uten lyd eller vibrasjon. Det ligger i
  ntfy-appen så du kan slå opp og se at jobben lever, ikke for å varsle deg. Slutter livstegnene
  å komme, står overvåkingen. Juster eller skru av med `HEARTBEAT_MINUTES` i `check_norli.py`
  (`0` = av).

`state.json` holder forrige status lokalt og er utenfor git.

## Justere hva som overvåkes

Alt ligger som konstanter øverst i `check_norli.py`:

```python
SKU = "0196214144828"          # EAN-koden bakerst i produkt-URL-en
WATCHED_STORES = {261: "...", 167: "...", 140: "..."}
WATCHED_REGIONS = {"Oslo"}     # hele regioner, f.eks. også "Østfold"
```

## Forbehold

Sjekkene går hvert 3. minutt. Endre `StartInterval` i `install.sh` og kjør den på nytt for å justere.

- **Macen må være våken.** Sover den, står sjekkene stille til den vekkes. `launchd` kjører
  jobben ved oppvåkning. Skal den overleve en lukket laptop, må den kjøre fra noe som står på
  hele døgnet — og det må ha norsk IP, se blokkeringen over.
- **Husk å skru av** når du har handlet: `./install.sh --uninstall`.
- **Livstegn er ikke en ekte dødmannsknapp.** Det forteller deg at jobben lever *når du ser
  etter*. Vil du bli varslet automatisk når den slutter å kjøre, er healthchecks.io riktig
  verktøy — scriptet pinger den ved hver kjøring, og den varsler deg når pingene uteblir.
