#!/usr/bin/env python3
"""Overvaker lagerstatus pa norli.no og varsler via ntfy nar noe kommer i beholdning.

Sporringen gar mot Norlis Magento GraphQL-endepunkt i stedet for a skrape HTML,
fordi produktsiden rendres i nettleseren: den rase HTML-en inneholder ingen
lagertekst i det hele tatt. Et tekstsok etter "Forventes i salg" ville derfor
aldri funnet noe, og slatt ut som falskt positivt ved forste kjoring.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Norli har flere verter foran samme Magento-backend. WAF-en avviser tidvis
# forespørsler fra datasenter-IP-er, så vi prøver den neste hvis den første svarer 403.
GRAPHQL_URLS = ["https://www.norli.no/graphql", "https://checkout.norli.no/graphql"]
PRODUCT_URL = "https://www.norli.no/{url_key}"

# Legg til flere SKU-er (EAN-koden bakerst i produkt-URL-en) for a overvake flere varer.
SKUS = ["0196214144828"]

# Nar varen er pa lager: gjenta varselet hvis det er mer enn sa mange timer
# siden forrige ping. Ellers varsles det bare pa overgangen utsolgt -> pa lager.
REPING_HOURS = 6

STATE_FILE = Path(__file__).with_name("state.json")
# WAF-en slipper bare gjennom det som ser ut som en ekte nettleser. En ærlig
# bot-User-Agent ga 403 fra GitHubs runnere selv om den virket fra hjemmenett.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en-US;q=0.7,en;q=0.6",
    "Content-Type": "application/json",
    "Origin": "https://www.norli.no",
    "Referer": "https://www.norli.no/",
    "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}
NTFY_USER_AGENT = "norli-stock-watch/1.0 (+https://github.com/arkstig/norli-stock-watch)"

QUERY = """
query Stock($skus: [String]!) {
  products(filter: { sku: { in: $skus } }) {
    items {
      sku
      name
      url_key
      stock_status
      only_x_left_in_stock
      price_range { minimum_price { final_price { value currency } } }
    }
  }
}
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_products(skus: list[str]) -> list[dict]:
    payload = json.dumps({"query": QUERY, "variables": {"skus": skus}}).encode("utf-8")
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

        items = (body.get("data") or {}).get("products", {}).get("items")
        if not items:
            raise RuntimeError(f"Ingen produkter i svaret for {skus}")
        return items

    raise RuntimeError(f"Alle endepunkter feilet, siste: {last_error}")


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

    request = urllib.request.Request(
        f"{server}/{topic}",
        data=message.encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def should_alert(previous: dict, status: str) -> bool:
    if status != "IN_STOCK":
        return False
    if previous.get("stock_status") != "IN_STOCK":
        return True  # overgangen utsolgt -> pa lager
    last = previous.get("last_alert")
    if not last:
        return True
    try:
        sent_at = datetime.fromisoformat(last)
    except ValueError:
        return True
    return now() - sent_at > timedelta(hours=REPING_HOURS)


def main() -> int:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC mangler", file=sys.stderr)
        return 2

    state = load_state()

    try:
        products = fetch_products(SKUS)
    except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        # Varsle om feil, men bare en gang per sammenhengende feilperiode, sa en
        # lengre nedetid hos Norli ikke spammer telefonen hvert femte minutt.
        if not state.get("_error"):
            state["_error"] = now().isoformat()
            save_state(state)
            try:
                notify(
                    topic,
                    "Norli-overvaking feiler",
                    f"Klarte ikke lese lagerstatus: {exc}\nSjekk Actions-loggen.",
                    priority="default",
                    tags="warning",
                )
            except Exception as notify_exc:  # noqa: BLE001 - feilvarsel skal aldri maskere hovedfeilen
                print(f"Kunne ikke sende feilvarsel: {notify_exc}", file=sys.stderr)
        print(f"FEIL: {exc}", file=sys.stderr)
        return 1

    state.pop("_error", None)

    for product in products:
        sku = product["sku"]
        status = product.get("stock_status", "UNKNOWN")
        name = product.get("name", sku)
        previous = state.get(sku, {})
        link = PRODUCT_URL.format(url_key=product.get("url_key", ""))

        print(f"{name} [{sku}]: {status}")

        entry = {"stock_status": status, "name": name, "checked_at": now().isoformat()}
        entry["last_alert"] = previous.get("last_alert")

        if should_alert(previous, status):
            price = product["price_range"]["minimum_price"]["final_price"]
            left = product.get("only_x_left_in_stock")
            lines = [
                name,
                f"{price['value']:.0f} {price['currency']}",
            ]
            if left:
                lines.append(f"Kun {int(left)} igjen")
            lines.append(link)

            notify(
                topic,
                "PA LAGER hos Norli",
                "\n".join(lines),
                priority="urgent",
                tags="tada,shopping_cart",
                click=link,
            )
            entry["last_alert"] = now().isoformat()
            print(f"  -> varsel sendt til ntfy-topic {topic}")

        state[sku] = entry

    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
