# Stock watch

Overvåker lagerstatus hos **norli.no**, **laboge.no** og **cardcenter.no** og sender
push-varsel til mobilen via [ntfy](https://ntfy.sh) i det øyeblikket noe blir tilgjengelig.

Sporer nå **61 mål**: Elite Trainer Box hos Norli (nettlager + 27 butikker), 11 produkter
hos Laboge og 22 hos Cardcenter. Japanske og kinesiske utgaver er utelatt.

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

## Ressursbruk

Målt, ikke anslått:

| | |
|---|---|
| Rutinekjøring | 7 sekunder, 0,6 s CPU, 17 MB minne, 72 KB nedlastet |
| Oppdagelse (hver time) | 21 sekunder, 1,7 MB nedlastet |
| **Til sammen** | **~77 MB i døgnet** |

Mellom kjøringene bruker den ingenting — prosessen avsluttes, og `launchd` starter den på nytt.
De 7 sekundene er nesten utelukkende venting på nettverk: 61 forespørsler etter hverandre.

## Justere hva som overvåkes

Konstanter øverst i `check_stock.py`:

```python
NORLI_SKU = "0196214144828"          # EAN-koden bakerst i produkt-URL-en
NORLI_STORES = {261: "...", ...}     # enkeltbutikker, ID fra --stores
NORLI_REGIONS = {"Oslo"}             # hele regioner, f.eks. også "Østfold"
SHOPIFY_SHOPS = [...]                # butikk + mønster for hva som følges
SHOPIFY_EXCLUDE = r"japansk|kinesisk|japanese|chinese"
DISCOVERY_MINUTES = 60               # hvor ofte hele katalogen skannes
```

## Forbehold

- **Macen må være våken.** Sover den, står sjekkene stille til den vekkes. Skal den overleve en
  lukket laptop, må den kjøre fra noe som står på hele døgnet — og det må ha norsk IP.
- **Shopify cacher svarene** i noen titalls sekunder, så et slipp kan bli oppdaget litt etter
  at det faktisk skjedde.
- **Helt nye produkter oppdages først ved neste katalogskanning**, altså inntil en time etter at
  de dukket opp. Produkter som allerede følges sjekkes hvert 3. minutt. Senk
  `DISCOVERY_MINUTES` hvis det er verdt båndbredden.
- **Livstegn er ikke en ekte dødmannsknapp.** Det sier at jobben lever *når du ser etter*.
  Vil du varsles automatisk når den stopper, er healthchecks.io riktig verktøy.
- **Husk å skru av** når du har handlet: `./install.sh --uninstall`.
