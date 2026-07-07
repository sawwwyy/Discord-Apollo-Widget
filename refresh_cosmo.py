# cosmo objekt widget - scrapes apollo.cafe since there's no public api

import httpx
import re
import sys

from time import sleep
from pathlib import Path
from orjson import loads
from rich.console import Console
from datetime import datetime

if sys.stdout is not None:
    logger = Console(force_terminal=True)
else:
    log_file = open(Path(__file__).parent / "refresh_cosmo.log", "a", encoding="utf-8", buffering=1)
    logger = Console(file=log_file, force_terminal=False, width=120)

config = loads((Path(__file__).parent / "config_cosmo.json").read_text())
refresh_mins = config["refresh_mins"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def format_count(n):
    n = int(n)

    if n >= 1_000_000:
        val, suffix = n / 1_000_000, "M"
    elif n >= 1_000:
        val, suffix = n / 1_000, "K"
    else:
        return str(n)

    s = f"{val:.1f}"
    return s[:-2] + suffix if s.endswith(".0") else s + suffix


def get_total(html):
    # objekt totals show up as total:93,hasNext:... in the page state
    m = re.search(r"total:(\d+)\s*,\s*hasNext", html)
    if not m:
        raise ValueError("couldn't find a total on this page, apollo probably changed something")
    return int(m.group(1))


def get_como(html, label):
    # como balances are tucked into a react-query cache entry, gotta anchor
    # to the como-balances key or it'll grab random amount: fields from elsewhere
    idx = html.find("como-balances")
    if idx == -1:
        raise ValueError("como-balances query missing from page, did the layout change?")

    chunk = html[max(0, idx - 1500):idx]
    m = re.search(rf'id:"{label}"\s*,\s*owner:"[^"]*"\s*,\s*amount:(\d+)', chunk, re.IGNORECASE)
    if not m:
        raise ValueError(f"no como amount for {label}")
    return int(m.group(1))


def fetch(url):
    r = httpx.get(url, headers=HEADERS, follow_redirects=True)
    r.raise_for_status()
    return r.text


def get_cosmo_data(user):
    base = f"https://apollo.cafe/@{user['username']}"

    triples = fetch(f"{base}?artist=tripleS")
    first = fetch(f"{base}?artist=tripleS&class=First")
    double = fetch(f"{base}?artist=tripleS&class=Double")
    special = fetch(f"{base}?artist=tripleS&class=Special")
    premier = fetch(f"{base}?artist=tripleS&class=Premier")
    como = fetch(f"{base}/como")

    return {
        "total_objekts": get_total(triples),
        "first_class_objekts": get_total(first),
        "double_class_objekts": get_total(double),
        "special_class_objekts": get_total(special),
        "premier_class_objekts": get_total(premier),
        "triples_como": get_como(como, "tripleS"),
    }


def push_data_to_discord(user):
    data = get_cosmo_data(user)
    logger.print(f"[yellow]pushing to discord ({user['id']})[/]")

    r = httpx.patch(
        f"https://discord.com/api/v9/applications/{user['app_id']}/users/{user['id']}/identities/0/profile",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bot {user['token']}",
            "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 1.0.0)",
        },
        json={
            "data": {
                "dynamic": [
                    {"type": 1, "name": "total_objekts", "value": format_count(data["total_objekts"])},
                    {"type": 2, "name": "triples_como", "value": data["triples_como"]},
                    {"type": 1, "name": "first_class_objekts", "value": format_count(data["first_class_objekts"])},
                    {"type": 1, "name": "double_class_objekts", "value": format_count(data["double_class_objekts"])},
                    {"type": 1, "name": "special_class_objekts", "value": format_count(data["special_class_objekts"])},
                    {"type": 1, "name": "premier_class_objekts", "value": format_count(data["premier_class_objekts"])},
                ]
            }
        },
    )
    r.raise_for_status()


if __name__ == "__main__":
    while True:
        logger.print(f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/] [yellow]starting check[/]")

        for user in config["users"]:
            logger.print(f"[blue]checking [bold]{user['username']}[/][/]")
            try:
                push_data_to_discord(user)
                logger.print("[green]done[/]")
            except Exception as e:
                logger.print(f"[red]failed: {e}[/]")
                logger.print_exception()

        logger.print(f"[dim]sleeping {refresh_mins}m[/]")
        sleep(refresh_mins * 60)
