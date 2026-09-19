#!/usr/bin/env python3
"""Overvaker lagerstatus i flere nettbutikker og varsler via ntfy.

Kilder:

  norli   Magento GraphQL. Nettlager (`stock_status`) og enkeltbutikker for
          klikk og hent (`pickupStores -> products.qty_in_store`) er to
          uavhengige ting: varen kan ligge i butikk uten a vare kjopbar pa nett.

  shopify laboge.no og cardcenter.no. Begge har sagt/vist at 30th Celebration
          slippes til uannonserte tidspunkter, sa bade tilgjengelighet og nye
          produkter varsles.

          To trinn, fordi en full katalogskanning er for dyr a gjore hvert
          3. minutt: Laboge har over 5000 produkter, Cardcenter 2500, og en
          full skann av begge er ca. 1,7 MB selv med gzip.

            1. Oppdagelse (hver DISCOVERY_MINUTES): skann hele katalogen og
               legg alle produkter som matcher butikkens monster inn i
               folgelisten. Nye produkter varsles.
            2. Sjekk (hver kjoring): hent hvert produkt i folgelisten fra
               /products/<handle>.js — ca. 2 KB gzippet per produkt.

Begge steder spores strukturerte data framfor HTML: Norlis produktside rendres
i nettleseren og inneholder ingen lagertekst i det hele tatt.

Kjor `--targets` for a se alt som overvakes akkurat na.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Norli ────────────────────────────────────────────────────────────────────
# WAF-en avviser datasenter-IP-er (GitHub Actions far 403), sa dette ma kjore
# fra norsk IP. Flere verter foran samme backend, sa den neste prøves ved feil.
NORLI_GRAPHQL = ["https://www.norli.no/graphql", "https://checkout.norli.no/graphql"]
NORLI_SKU = "0196214144828"
NORLI_URL = "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-elite-trainer-box-0196214144828"

# Butikker som varsles pa. Se alle med `--stores`.
NORLI_STORES = {
    261: "Værstetorvet, Fredrikstad",
    167: "Nygaardsgaten, Fredrikstad",
    140: "Østfoldhallene, Fredrikstad",
    115: "Storbyen Senter, Sarpsborg",
    152: "Thon Senter Borg, Sarpsborg",
}
NORLI_REGIONS = {"Oslo"}

# ── Shopify-butikker ─────────────────────────────────────────────────────────
# (visningsnavn, adresse, monster for hva som folges). Monsteret matches mot
# handle og tittel, uten hensyn til store/sma bokstaver.
SHOPIFY_SHOPS = [
    ("Laboge", "https://laboge.no", r"^pokemon-30th-celebration-"),
    # "30th Anniversary" alene fanger nokkelringer, mynter og annen merch, sa
    # mønsteret krever "celebration".
    ("Cardcenter", "https://cardcenter.no", r"30th[ -]*(anniversary[ -]*)?celebration"),
]

# Produkter som aldri folges, uansett butikk. Kun vestlige utgaver onskes.
SHOPIFY_EXCLUDE = r"japansk|kinesisk|japanese|chinese"

# Hvor ofte hele katalogen skannes for a finne nye produkter.
DISCOVERY_MINUTES = 60

# Stoppgrense for katalogskanning, sa en paginering som aldri tar slutt ikke
# kan lope lopsk.
MAX_CATALOG_PAGES = 40

# ── Felles ───────────────────────────────────────────────────────────────────
REPING_HOURS = 6          # gjenta varsel om noe fortsatt er tilgjengelig
HEARTBEAT_MINUTES = 30    # livstegn med min-prioritet; 0 slar av
STATE_FILE = Path(__file__).with_name("state.json")
STATE_VERSION = 3

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
}
NTFY_USER_AGENT = "stock-watch/3.0 (+https://github.com/arkstig/norli-stock-watch)"

NORLI_PRODUCT_QUERY = """
query Product($sku: String!) {
  products(filter: { sku: { eq: $sku } }) { items { id sku name stock_status } }
}
"""
NORLI_STORES_QUERY = """
query PickupStores($productIds: [Int]) {
  pickupStores(productIds: $productIds) {
    name
    stores { stockist_id name city region products { id qty_in_store } }
  }
}
"""


@dataclass
class Target:
    """Én ting som overvåkes, med egen varslingshistorikk."""

    key: str
    label: str
    available: bool
    url: str
    detail: str = ""
    new: bool = field(default=False)  # produktet fantes ikke ved forrige sjekk

    @property
    def text(self) -> str:
        return f"{self.label}{self.detail}"


def now() -> datetime:
    return datetime.now(timezone.utc)


def http_json(url: str, *, data: bytes | None = None) -> dict:
    headers = dict(BROWSER_HEADERS)
    # Gzip er ikke valgfritt her: Shopifys katalogsider er ca. 950 KB rå og
    # 57 KB komprimert. urllib pakker ikke ut selv, sa det gjores under.
    headers["Accept-Encoding"] = "gzip"
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = "https://www.norli.no"
        headers["Referer"] = "https://www.norli.no/"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


# ── Norli ────────────────────────────────────────────────────────────────────
def norli_graphql(query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    last_error: Exception | None = None
    for url in NORLI_GRAPHQL:
        try:
            body = http_json(url, data=payload)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"{url} feilet: {exc}", file=sys.stderr)
            last_error = exc
            continue
        if body.get("errors"):
            raise RuntimeError(f"GraphQL-feil: {body['errors']}")
        return body["data"]
    raise RuntimeError(f"Alle Norli-endepunkter feilet, siste: {last_error}")


def norli_stores(product_id: int) -> list[dict]:
    regions = norli_graphql(NORLI_STORES_QUERY, {"productIds": [product_id]})["pickupStores"]
    stores = []
    for region in regions:
        for store in region.get("stores") or []:
            # Antallet ligger i products.qty_in_store. all_in_stock alene er
            # ikke nok — den er false selv nar varen finnes.
            qty = sum((p.get("qty_in_store") or 0) for p in (store.get("products") or []))
            stores.append(
                {
                    "id": store["stockist_id"],
                    "name": store["name"],
                    "region": store.get("region") or region.get("name") or "",
                    "qty": qty,
                }
            )
    return stores


def norli_watched(store: dict) -> bool:
    return store["id"] in NORLI_STORES or store["region"] in NORLI_REGIONS


def norli_targets() -> list[Target]:
    items = norli_graphql(NORLI_PRODUCT_QUERY, {"sku": NORLI_SKU})["products"]["items"]
    if not items:
        raise RuntimeError(f"Fant ikke Norli-produkt med SKU {NORLI_SKU}")
    product = items[0]

    targets = [
        Target(
            key="norli:online",
            label="Norli nettlager",
            available=product["stock_status"] == "IN_STOCK",
            url=NORLI_URL,
        )
    ]
    for store in norli_stores(product["id"]):
        if not norli_watched(store):
            continue
        targets.append(
            Target(
                key=f"norli:store:{store['id']}",
                label="Norli " + NORLI_STORES.get(store["id"], store["name"]),
                available=store["qty"] > 0,
                url=NORLI_URL,
                detail=f" ({store['qty']} stk)" if store["qty"] > 1 else "",
            )
        )
    return targets


# ── Shopify ──────────────────────────────────────────────────────────────────
def shopify_catalog(base: str) -> list[dict]:
    """Alle produkter i butikken. Dyr — kalles bare ved oppdagelse."""
    products: list[dict] = []
    for page in range(1, MAX_CATALOG_PAGES + 1):
        batch = http_json(f"{base}/products.json?limit=250&page={page}")["products"]
        if not batch:
            break
        products.extend(batch)
    return products


def shopify_product(base: str, handle: str) -> dict | None:
    """Ett produkt, ca. 2 KB gzippet. None hvis det er fjernet fra butikken."""
    try:
        return http_json(f"{base}/products/{handle}.js")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def shopify_discover(name: str, base: str, pattern: str, state: dict) -> list[str]:
    """Skanner katalogen og returnerer handles som matcher butikkens mønster."""
    matcher = re.compile(pattern, re.IGNORECASE)
    blocked = re.compile(SHOPIFY_EXCLUDE, re.IGNORECASE)
    found = [
        product["handle"]
        for product in shopify_catalog(base)
        if (matcher.search(product["handle"]) or matcher.search(product["title"]))
        and not (blocked.search(product["handle"]) or blocked.search(product["title"]))
    ]
    state.setdefault("shops", {}).setdefault(name, {})["discovered"] = now().isoformat()
    return sorted(found)


def shopify_targets(state: dict) -> list[Target]:
    targets: list[Target] = []
    shops = state.setdefault("shops", {})

    for name, base, pattern in SHOPIFY_SHOPS:
        shop = shops.setdefault(name, {})
        known: list[str] = shop.get("handles") or []

        # Første kjøring, eller på tide med ny oppdagelse.
        if not known or older_than(shop.get("discovered"), timedelta(minutes=DISCOVERY_MINUTES)):
            found = shopify_discover(name, base, pattern, state)
            if found:
                # Før første oppdagelse er ingenting "nytt" — da hadde alt blitt varslet.
                shop["new"] = sorted(set(found) - set(known)) if known else []
                shop["handles"] = found
                known = found
        else:
            shop["new"] = []

        newly = set(shop.get("new") or [])

        for handle in known:
            product = shopify_product(base, handle)
            if product is None:
                continue
            variants = product.get("variants") or []
            available = any(v.get("available") for v in variants)
            price = variants[0].get("price") if variants else None
            targets.append(
                Target(
                    key=f"{name.lower()}:{handle}",
                    label=f"{name} {product['title']}",
                    available=available,
                    url=f"{base}/products/{handle}",
                    # Shopifys .js-endepunkt gir pris i ører, products.json i kroner.
                    detail=f" ({price / 100:.2f} kr)" if isinstance(price, int) else "",
                    new=handle in newly,
                )
            )

    return targets


# ── Varsling og tilstand ─────────────────────────────────────────────────────
def notify(topic: str, title: str, message: str, *, priority: str, tags: str, click: str | None = None) -> None:
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    headers = {
        "Title": title.encode("utf-8").decode("latin-1", "replace"),
        "Priority": priority,
        "Tags": tags,
        "User-Agent": NTFY_USER_AGENT,
    }
    if click:
        headers["Click"] = click
    request = urllib.request.Request(f"{server}/{topic}", data=message.encode("utf-8"), headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    if state.get("version") != STATE_VERSION:
        state = {"version": STATE_VERSION}  # eldre format: start rent
    state.setdefault("targets", {})
    return state


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def older_than(iso: str | None, delta: timedelta) -> bool:
    if not iso:
        return True
    try:
        return now() - datetime.fromisoformat(iso) > delta
    except ValueError:
        return True


def report_error(state: dict, topic: str, exc: Exception) -> None:
    """Varsler én gang per sammenhengende feilperiode, ikke ved hver kjøring."""
    if state.get("_error"):
        return
    state["_error"] = now().isoformat()
    save_state(state)
    try:
        notify(topic, "Overvaking feiler", f"Klarte ikke lese lagerstatus: {exc}", priority="default", tags="warning")
    except Exception as notify_exc:  # noqa: BLE001 - skal aldri maskere hovedfeilen
        print(f"Kunne ikke sende feilvarsel: {notify_exc}", file=sys.stderr)


def collect(state: dict) -> list[Target]:
    return norli_targets() + shopify_targets(state)


def dump_stores() -> int:
    items = norli_graphql(NORLI_PRODUCT_QUERY, {"sku": NORLI_SKU})["products"]["items"]
    for store in sorted(norli_stores(items[0]["id"]), key=lambda s: (s["region"], s["name"])):
        mark = "*" if norli_watched(store) else " "
        print(f"{mark} {store['id']:>4}  {store['region']:<18} {store['name']:<45} qty={store['qty']}")
    return 0


def dump_targets() -> int:
    state = load_state()
    for target in collect(state):
        print(f"{'TILGJ' if target.available else 'utsolgt':<8} {target.text}")
    return 0


def main() -> int:
    if "--stores" in sys.argv:
        return dump_stores()
    if "--targets" in sys.argv:
        return dump_targets()

    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC mangler", file=sys.stderr)
        return 2

    state = load_state()

    try:
        targets = collect(state)
    except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError, KeyError) as exc:
        report_error(state, topic, exc)
        print(f"FEIL: {exc}", file=sys.stderr)
        return 1

    state.pop("_error", None)

    available = [t for t in targets if t.available]
    in_stock_alerts: list[Target] = []
    new_alerts: list[Target] = []

    for target in targets:
        previous = state["targets"].get(target.key, {})
        entry = {"available": target.available, "label": target.label, "last_alert": previous.get("last_alert")}

        if target.available and (
            not previous.get("available") or older_than(previous.get("last_alert"), timedelta(hours=REPING_HOURS))
        ):
            in_stock_alerts.append(target)
            entry["last_alert"] = now().isoformat()
        elif target.new:
            new_alerts.append(target)

        state["targets"][target.key] = entry

    stamp = now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    summary = ", ".join(t.text for t in available) if available else "utsolgt overalt"
    print(f"{stamp}  {summary}  ({len(targets)} mål)", flush=True)

    if in_stock_alerts:
        notify(
            topic,
            "PÅ LAGER",
            "\n".join(f"• {t.text}" for t in in_stock_alerts) + f"\n\n{in_stock_alerts[0].url}",
            priority="urgent",
            tags="tada,shopping_cart",
            click=in_stock_alerts[0].url,
        )
        print(f"  -> varsel: {', '.join(t.text for t in in_stock_alerts)}", flush=True)

    if new_alerts:
        # Et nytt produkt som ennå er utsolgt betyr som regel at et slipp er nært.
        notify(
            topic,
            "Nytt produkt lagt ut",
            "\n".join(f"• {t.text}" for t in new_alerts) + f"\n\n{new_alerts[0].url}",
            priority="default",
            tags="eyes",
            click=new_alerts[0].url,
        )
        print(f"  -> nytt produkt: {', '.join(t.text for t in new_alerts)}", flush=True)

    if HEARTBEAT_MINUTES > 0 and older_than(state.get("_heartbeat"), timedelta(minutes=HEARTBEAT_MINUTES)):
        notify(
            topic,
            f"Overvaking lever ({now().astimezone():%H:%M})",
            f"{summary} ({len(targets)} mål)",
            priority="min",
            tags="green_circle",
        )
        state["_heartbeat"] = now().isoformat()

    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
