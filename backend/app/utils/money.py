"""Money handling. Internally everything is integer kopeks — no float math."""

from __future__ import annotations

RUB_SYMBOL = "₽"
SYMBOLS = {"RUB": RUB_SYMBOL, "USD": "$", "EUR": "€"}


def to_kopeks(amount: float | int | str) -> int:
    if isinstance(amount, str):
        amount = float(amount.replace(",", ".").replace(" ", ""))
    return round(float(amount) * 100)


def from_kopeks(kopeks: int) -> float:
    return kopeks / 100


def format_money(kopeks: int, currency: str = "RUB", *, with_decimals: bool = False) -> str:
    symbol = SYMBOLS.get(currency.upper(), "")
    amount = kopeks / 100
    if with_decimals or amount % 1:
        body = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    else:
        body = f"{int(amount):,}".replace(",", " ")
    return f"{body} {symbol}".strip()
