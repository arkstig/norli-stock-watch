#!/usr/bin/env python3
"""Overvaker lagerstatus i flere nettbutikker og varsler via ntfy.

Kilder:

  norli   Magento GraphQL. Nettlager (`stock_status`) og enkeltbutikker for
          klikk og hent (`pickupStores -> products.qty_in_store`) er to
          uavhengige ting: varen kan ligge i butikk uten a vare kjopbar pa nett.

  laboge  Shopify. Sjekker de forseglede 30th Celebration-produktene, som
          finnes i to utgaver: en placeholder til 1 kr og en "(Live)" til ekte
          pris. Hvilken av dem som apnes ved slipp er ikke kjent, sa begge
          overvakes. Nye produkter som dukker opp varsles ogsa, siden butikken
          har sagt at slippene skjer til uannonserte tidspunkter.

Begge steder spores strukturerte data framfor HTML: Norlis produktside rendres
i nettleseren og inneholder ingen lagertekst i det hele tatt.

Kjor `--targets` for a se alt som overvakes akkurat na.
"""

from __future__ import annotations

import json
import os
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

# ── Laboge ───────────────────────────────────────────────────────────────────
LABOGE_PRODUCTS = "https://laboge.no/products.json"
LABOGE_PRODUCT_URL = "https://laboge.no/products/{handle}"
LABOGE_HANDLE_PREFIX = "pokemon-30th-celebration-"

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
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = "https://www.norli.no"
        headers["Referer"] = "https://www.norli.no/"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


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


# ── Laboge ───────────────────────────────────────────────────────────────────
def laboge_targets(state: dict) -> list[Target]:
    products: list[dict] = []
    for page in range(1, 5):
        batch = http_json(f"{LABOGE_PRODUCTS}?limit=250&page={page}")["products"]
        if not batch:
            break
        products.extend(batch)

    if not products:
        raise RuntimeError("Tomt produktsvar fra Laboge")

    known = set(state.get("laboge_handles") or [])
    seen: list[str] = []
    targets: list[Target] = []

    for product in products:
        handle = product["handle"]
        if not handle.startswith(LABOGE_HANDLE_PREFIX):
            continue
        seen.append(handle)
        variant = (product.get("variants") or [{}])[0]
        available = any(v.get("available") for v in product.get("variants") or [])
        price = variant.get("price")
        targets.append(
            Target(
                key=f"laboge:{handle}",
                label="Laboge " + product["title"],
                available=available,
                url=LABOGE_PRODUCT_URL.format(handle=handle),
                detail=f" ({price} kr)" if price else "",
                # Forste kjoring kjenner ingen handles, og da er ingenting "nytt".
                new=bool(known) and handle not in known,
            )
        )

    state["laboge_handles"] = sorted(seen)
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
    return norli_targets() + laboge_targets(state)


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
