#!/usr/bin/env python3
"""Overvaker lagerstatus hos norli.no og varsler via ntfy nar varen dukker opp.

To ting overvakes uavhengig av hverandre:

  * Nettlageret, via feltet `stock_status` pa produktet.
  * Enkeltbutikker (klikk og hent), via `pickupStores { stores { products { qty_in_store } } }`.

Skillet er viktig: en vare kan ligge i en butikk uten a vare kjopbar pa nett, og
det var akkurat det som skjedde her. Nettsiden viste "Ikke tilgjengelig pa
nettlager" samtidig som den var "Pa lager hos 1 butikker".

Sporringene gar mot Magento-GraphQL-endepunktet i stedet for a skrape HTML,
fordi produktsiden rendres i nettleseren: ra HTML inneholder ingen lagertekst
i det hele tatt.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Norli har flere verter foran samme backend. WAF-en avviser forespørsler fra
# datasenter-IP-er (GitHub Actions far 403), sa dette ma kjore fra norsk IP.
GRAPHQL_URLS = ["https://www.norli.no/graphql", "https://checkout.norli.no/graphql"]

SKU = "0196214144828"
PRODUCT_URL = "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-elite-trainer-box-0196214144828"

# Butikker som varsles pa. Hent flere stockist_id med `python3 check_norli.py --stores`.
WATCHED_STORES = {
    261: "Værstetorvet, Fredrikstad",
    167: "Nygaardsgaten, Fredrikstad",
    140: "Østfoldhallene, Fredrikstad",
    115: "Storbyen Senter, Sarpsborg",
    152: "Thon Senter Borg, Sarpsborg",
}

# Hele regioner som overvakes i tillegg. Ma matche `region` i API-et.
WATCHED_REGIONS = {"Oslo"}

# Gjenta varselet hvis varen fortsatt er tilgjengelig sa mange timer etter forrige ping.
REPING_HOURS = 6

# Livstegn med min-prioritet, altsa uten lyd. 0 slar det av.
HEARTBEAT_MINUTES = 30

STATE_FILE = Path(__file__).with_name("state.json")
STATE_VERSION = 2

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://www.norli.no",
    "Referer": "https://www.norli.no/",
}
NTFY_USER_AGENT = "norli-stock-watch/2.0 (+https://github.com/arkstig/norli-stock-watch)"

PRODUCT_QUERY = """
query Product($sku: String!) {
  products(filter: { sku: { eq: $sku } }) {
    items { id sku name stock_status }
  }
}
"""

# Samme sporring som butikkvelgeren pa nettsiden bruker. Mengden ligger i
# products.qty_in_store — all_in_stock alene er ikke nok til a se antall.
STORES_QUERY = """
query PickupStores($productIds: [Int]) {
  pickupStores(productIds: $productIds) {
    name
    stores { stockist_id name city region products { id qty_in_store } }
  }
}
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def graphql(query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    last_error: Exception | None = None

    for url in GRAPHQL_URLS:
        request = urllib.request.Request(url, data=payload, headers=dict(BROWSER_HEADERS))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"{url} feilet: {exc}", file=sys.stderr)
            last_error = exc
            continue

        if body.get("errors"):
            raise RuntimeError(f"GraphQL-feil: {body['errors']}")
        return body["data"]

    raise RuntimeError(f"Alle endepunkter feilet, siste: {last_error}")


def fetch_product() -> dict:
    items = graphql(PRODUCT_QUERY, {"sku": SKU})["products"]["items"]
    if not items:
        raise RuntimeError(f"Fant ikke produkt med SKU {SKU}")
    return items[0]


def fetch_stores(product_id: int) -> list[dict]:
    """Flater ut regionene til én liste med {id, name, region, qty}."""
    regions = graphql(STORES_QUERY, {"productIds": [product_id]})["pickupStores"]
    stores = []
    for region in regions:
        for store in region.get("stores") or []:
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


def is_watched(store: dict) -> bool:
    return store["id"] in WATCHED_STORES or store["region"] in WATCHED_REGIONS


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
        # Eldre format: start rent heller enn a tolke det feil.
        state = {"version": STATE_VERSION}
    state.setdefault("targets", {})
    return state


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def stale(last_alert: str | None) -> bool:
    """Sant hvis det er lenge nok siden forrige ping til a gjenta varselet."""
    if not last_alert:
        return True
    try:
        return now() - datetime.fromisoformat(last_alert) > timedelta(hours=REPING_HOURS)
    except ValueError:
        return True


def due_for_heartbeat(state: dict) -> bool:
    if HEARTBEAT_MINUTES <= 0:
        return False
    last = state.get("_heartbeat")
    if not last:
        return True
    try:
        return now() - datetime.fromisoformat(last) > timedelta(minutes=HEARTBEAT_MINUTES)
    except ValueError:
        return True


def report_error(state: dict, topic: str, exc: Exception) -> None:
    """Varsler en gang per sammenhengende feilperiode, ikke ved hver kjoring."""
    if state.get("_error"):
        return
    state["_error"] = now().isoformat()
    save_state(state)
    try:
        notify(
            topic,
            "Norli-overvaking feiler",
            f"Klarte ikke lese lagerstatus: {exc}",
            priority="default",
            tags="warning",
        )
    except Exception as notify_exc:  # noqa: BLE001 - skal aldri maskere hovedfeilen
        print(f"Kunne ikke sende feilvarsel: {notify_exc}", file=sys.stderr)


def dump_stores() -> int:
    """`--stores` lister alle butikker med id, for a plukke ut nye a overvake."""
    product = fetch_product()
    for store in sorted(fetch_stores(product["id"]), key=lambda s: (s["region"], s["name"])):
        mark = "*" if is_watched(store) else " "
        print(f"{mark} {store['id']:>4}  {store['region']:<18} {store['name']:<45} qty={store['qty']}")
    return 0


def main() -> int:
    if "--stores" in sys.argv:
        return dump_stores()

    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC mangler", file=sys.stderr)
        return 2

    state = load_state()

    try:
        product = fetch_product()
        stores = fetch_stores(product["id"])
    except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        report_error(state, topic, exc)
        print(f"FEIL: {exc}", file=sys.stderr)
        return 1

    state.pop("_error", None)

    # Nettlager og hver overvakede butikk behandles som uavhengige mal, sa et
    # varsel om en butikk ikke undertrykker et varsel om en annen.
    targets: list[tuple[str, str, bool, str]] = [
        ("online", "Nettlager", product["stock_status"] == "IN_STOCK", "")
    ]
    for store in stores:
        if is_watched(store):
            label = WATCHED_STORES.get(store["id"], store["name"])
            suffix = f" ({store['qty']} stk)" if store["qty"] > 1 else ""
            targets.append((f"store:{store['id']}", label, store["qty"] > 0, suffix))

    available = [(label + suffix) for _, label, ok, suffix in targets if ok]
    fresh: list[str] = []

    for key, label, ok, suffix in targets:
        previous = state["targets"].get(key, {})
        entry = {"available": ok, "label": label}
        entry["last_alert"] = previous.get("last_alert")

        if ok and (not previous.get("available") or stale(previous.get("last_alert"))):
            fresh.append(label + suffix)
            entry["last_alert"] = now().isoformat()

        state["targets"][key] = entry

    stamp = now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    watched = sum(1 for _ in targets) - 1
    print(
        f"{stamp}  {'TILGJENGELIG: ' + ', '.join(available) if available else 'utsolgt'}"
        f"  (nettlager + {watched} butikker)",
        flush=True,
    )

    if fresh:
        notify(
            topic,
            "PÅ LAGER hos Norli",
            "\n".join([product["name"], "", *(f"• {f}" for f in fresh), "", PRODUCT_URL]),
            priority="urgent",
            tags="tada,shopping_cart",
            click=PRODUCT_URL,
        )
        print(f"  -> varsel sendt: {', '.join(fresh)}", flush=True)

    if due_for_heartbeat(state):
        summary = ", ".join(available) if available else f"utsolgt (nettlager + {watched} butikker)"
        notify(
            topic,
            f"Overvaking lever ({now().astimezone():%H:%M})",
            summary,
            priority="min",
            tags="green_circle",
        )
        state["_heartbeat"] = now().isoformat()

    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
