# Stock watch

Overvåker lagerstatus hos **norli.no**, **laboge.no**, **cardcenter.no** og **maxgaming.no**
og sender push-varsel til mobilen via [ntfy](https://ntfy.sh) i det øyeblikket noe blir
tilgjengelig.

Sporer nå **68 mål**: Elite Trainer Box hos Norli (nettlager + 27 butikker), 11 produkter hos
Laboge, 22 hos Cardcenter og 7 hos MaxGaming. Japanske og kinesiske utgaver er utelatt.

**Elite Trainer Box varsles for seg**, med egen tittel (`ELITE TRAINER BOX`), så du ser på
varselet hva det gjelder uten å åpne det. Styres av `PRIORITY_PATTERN`.

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

### Laboge og Cardcenter — Shopify

Begge slipper 30th Celebration til uannonserte tidspunkter. Hos Laboge finnes hvert produkt
i **to utgaver** — en placeholder til 1 kr og en «(Live)» til ekte pris — og det er ikke kjent
hvilken som åpnes ved slipp, så begge følges.

Overvåkingen går i to trinn, fordi en full katalogskanning er for dyr å gjøre hvert 3. minutt:

| Trinn | Hvor ofte | Hva | Kostnad |
|---|---|---|---|
| **Sjekk** | hver kjøring | `/products/<handle>.js` for hvert fulgt produkt | ~2 KB per produkt |
| **Oppdagelse** | hver time | hele katalogen, for å finne produkter som ikke fantes før | ~1,7 MB |

Oppdagelsen er nødvendig fordi et slipp kan opprette et **helt nytt produkt**, og Shopify har
ikke noe API for «list produkter som matcher X» — søke-API-et stopper på 10 treff, og Cardcenter
har flere enn det. Nye produkter varsles med lavere prioritet: et nytt produkt som ennå er
utsolgt betyr som regel at et slipp er nært.

Katalogene er større enn de ser ut: Laboge har over 5000 produkter, Cardcenter 2500.
Gzip er derfor påkrevd — en katalogside er 950 KB rå og 57 KB komprimert.

### MaxGaming — egen plattform

Ikke Shopify. Søkesiden `/sok?q=30th` gir alle treffene med lagerstatus i ett kall på 105 KB,
så her trengs ingen todeling. Kategorisiden hadde krevd fire sidehenting (460 KB), og
produktsidene er 108 KB hver.

Statusen leses fra CSS-klassen `Lager_<kode>_NO`, ikke fra teksten ved siden av — klassen er
det maskinlesbare, teksten står der for mennesker og kan endres uten forvarsel:

| Kode | Betyr |
|---|---|
| `Lager_1_NO` | på lager |
| `Lager_8_NO` | forhåndsbestilling |
| `Lager_10_NO` | utsolgt |

Både `1` og `8` regnes som tilgjengelig, siden forhåndsbestilling også er en måte å sikre seg
varen på. Statusteksten følger med i varselet, så du ser hvilken av dem det er.

Gir søket null treff, kastes det en feil i stedet for å rapportere «utsolgt». Tomt resultat
betyr nesten alltid at markupen er endret, og da er stillhet verre enn et feilvarsel.

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
2. `./install.sh <ntfy-topic>` — legg til `--always-on` på en maskin som skal stå på hele tiden

Skal den kjøre på en maskin som står på døgnet rundt, følg **[SETUP-MAC.md](SETUP-MAC.md)**.

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
- **Hvis oppslaget feiler:** ett varsel per sammenhengende feilperiode. Hver forespørsel
  prøves tre ganger med økende pause først, siden butikkene av og til kobler ned midt i en
  serie kall. Bare vedvarende feil varsles.

Sjekkene går hvert 3. minutt (`StartInterval` i `install.sh`). `state.json` holder forrige
status lokalt og er utenfor git.

## Ressursbruk

Målt, ikke anslått:

| | |
|---|---|
| Rutinekjøring | 10 sekunder, 0,6 s CPU, 19 MB minne, 175 KB nedlastet |
| Oppdagelse (hver time) | 21 sekunder, 1,7 MB nedlastet |
| **Til sammen** | **~127 MB i døgnet** |

Mellom kjøringene bruker den ingenting — prosessen avsluttes, og `launchd` starter den på nytt.
De 10 sekundene er nesten utelukkende venting på nettverk: 68 forespørsler etter hverandre.

## Justere hva som overvåkes

Konstanter øverst i `check_stock.py`:

```python
NORLI_SKU = "0196214144828"          # EAN-koden bakerst i produkt-URL-en
NORLI_STORES = {261: "...", ...}     # enkeltbutikker, ID fra --stores
NORLI_REGIONS = {"Oslo"}             # hele regioner, f.eks. også "Østfold"
SHOPIFY_SHOPS = [...]                # butikk + mønster for hva som følges
MAXGAMING_INCLUDE = r"30th[ -]*(anniversary[ -]*)?celebration"
EXCLUDE = r"japansk|kinesisk|japanese|chinese|simplified"
PRIORITY_PATTERN = r"elite trainer box|\betb\b"   # får eget varsel
DISCOVERY_MINUTES = 60               # hvor ofte hele katalogen skannes
```

## Kjent fallgruve

`launchd` kjører macOS' system-Python (3.9), ikke den `python3` du har i skallet. Der er
`socket.timeout` ikke en `TimeoutError`, og `ConnectionResetError` er ingen av delene — så
`except TimeoutError` slipper begge gjennom og jobben dør med en traceback i stedet for å
sende feilvarsel. Derfor fanges `OSError`, som dekker alle tre. Test med
`/Library/Developer/CommandLineTools/usr/bin/python3` før du stoler på en endring.

## Forbehold

- **Macen må være våken.** Sover den, står sjekkene stille til den vekkes. Løsningen er en maskin
  som står på hele tiden — se [SETUP-MAC.md](SETUP-MAC.md). Skyhosting er ikke et alternativ for
  Norli-delen, siden den blokkerer datasenter-IP-er.
- **Shopify cacher svarene** i noen titalls sekunder, så et slipp kan bli oppdaget litt etter
  at det faktisk skjedde.
- **Helt nye produkter oppdages først ved neste katalogskanning**, altså inntil en time etter at
  de dukket opp. Produkter som allerede følges sjekkes hvert 3. minutt. Senk
  `DISCOVERY_MINUTES` hvis det er verdt båndbredden.
- **Livstegn er ikke en ekte dødmannsknapp.** Det sier at jobben lever *når du ser etter*.
  Vil du varsles automatisk når den stopper, er healthchecks.io riktig verktøy.
- **Husk å skru av** når du har handlet: `./install.sh --uninstall`.
