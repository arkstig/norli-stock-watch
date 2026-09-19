# Stock watch

Overvåker lagerstatus hos **norli.no** og **laboge.no** og sender push-varsel til mobilen
via [ntfy](https://ntfy.sh) i det øyeblikket noe blir tilgjengelig.

Sporer nå **39 mål**: Pokémon 30th Celebration Elite Trainer Box hos Norli (nettlager +
27 butikker) og alle 11 forseglede 30th Celebration-produkter hos Laboge.

## Hva som overvåkes

### Norli — Magento GraphQL

| | Felt |
|---|---|
| **Nettlager** | `products.stock_status` |
| **27 butikker** (klikk og hent) | `pickupStores → products.qty_in_store` |

Skillet mellom de to er ikke teoretisk: 18. september viste siden «Ikke tilgjengelig på
nettlager» samtidig som den var «På lager hos 1 butikker». Overvåker du bare `stock_status`,
går du glipp av nettopp de tilfellene.

Butikkene er tre i Fredrikstad, to i Sarpsborg og alle 22 i Oslo. Se alle 197 med butikk-ID:

```bash
python3 check_stock.py --stores      # * = overvåkes
```

Merk at `all_in_stock` **ikke** holder alene — den er `false` selv når varen finnes.
Antallet ligger i `products.qty_in_store`.

### Laboge — Shopify

Butikken varslet at 30th Celebration-produktene slippes «med jevne mellomrom og til
uannonserte tidspunkter». Hvert produkt finnes i **to utgaver**: en placeholder til 1 kr og
en «(Live)» til ekte pris. Hvilken som åpnes ved slipp er ikke kjent, så begge overvåkes —
alt med handle som starter på `pokemon-30th-celebration-`.

Dukker det opp et *nytt* produkt med den prefiksen, varsles det også, med lavere prioritet.
Et nytt produkt som fortsatt er utsolgt betyr som regel at et slipp er nært.

## Hvorfor strukturerte data og ikke tekstsøk i HTML-en

Norlis produktside rendres i nettleseren. Rå HTML inneholder ingen lagertekst i det hele tatt —
verken «Forventes i salg» eller «Legg i handlekurv». Et script som varsler når «Forventes i salg»
*forsvinner*, ville slått ut som falskt positivt allerede ved første kjøring.

## Hvorfor dette ikke kjører i GitHub Actions

Planen var å kjøre i skyen på GitHub Actions. Det går ikke: **Norli svarer `403 Forbidden` på
alt som kommer fra GitHubs servere** — også et helt vanlig GET-kall på produktsiden. Blokkeringen
er IP-basert (Azure/datasenter, utenfor Norge), og lar seg ikke løse med headere.

Derfor kjører sjekken som en `launchd`-jobb på Mac-en, som har norsk IP. Workflowen ligger igjen
i `.github/workflows/norli.yml`, men er deaktivert.

## Oppsett

1. Installer ntfy-appen ([iOS](https://apps.apple.com/us/app/ntfy/id1625396347) /
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)) og abonner på topicet.
   Topicet er hele hemmeligheten — hvem som helst som kjenner navnet kan lese varslene dine.
2. `./install.sh <ntfy-topic>`

| Kommando | Hva den gjør |
|---|---|
| `python3 check_stock.py --targets` | Lister alt som overvåkes, med status nå |
| `python3 check_stock.py --stores` | Lister alle Norli-butikker med ID |
| `tail -f ~/Library/Logs/norli-stock-watch/out.log` | Følger sjekkene |
| `launchctl list \| grep norli` | Ser om jobben lever |
| `./install.sh --uninstall` | Skrur av overvåkingen |

## Varsling

- **Når noe blir tilgjengelig:** `urgent`-prioritet, som ringer gjennom stillemodus på de
  fleste telefoner. Varselet navngir butikk eller produkt og antall. Trykk for å gå til siden.
  Hvert mål varsles for seg, så ett varsel ikke skjuler et annet.
- **Nytt produkt hos Laboge:** `default`-prioritet.
- **Livstegn hver 30. minutt:** `min`-prioritet — uten lyd eller vibrasjon. Ligger i appen så du
  kan slå opp og se at jobben lever. Slutter de å komme, står overvåkingen.
- **Hvis oppslaget feiler:** ett varsel per sammenhengende feilperiode.

Sjekkene går hvert 3. minutt (`StartInterval` i `install.sh`). `state.json` holder forrige
status lokalt og er utenfor git.

## Justere hva som overvåkes

Konstanter øverst i `check_stock.py`:

```python
NORLI_SKU = "0196214144828"          # EAN-koden bakerst i produkt-URL-en
NORLI_STORES = {261: "...", ...}     # enkeltbutikker, ID fra --stores
NORLI_REGIONS = {"Oslo"}             # hele regioner, f.eks. også "Østfold"
LABOGE_HANDLE_PREFIX = "pokemon-30th-celebration-"
```

## Forbehold

- **Macen må være våken.** Sover den, står sjekkene stille til den vekkes. Skal den overleve en
  lukket laptop, må den kjøre fra noe som står på hele døgnet — og det må ha norsk IP.
- **Shopify cacher `products.json`** i noen titalls sekunder, så et Laboge-slipp kan bli
  oppdaget litt etter at det faktisk skjedde.
- **Livstegn er ikke en ekte dødmannsknapp.** Det sier at jobben lever *når du ser etter*.
  Vil du varsles automatisk når den stopper, er healthchecks.io riktig verktøy.
- **Husk å skru av** når du har handlet: `./install.sh --uninstall`.
