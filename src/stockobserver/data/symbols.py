"""Canonical symbols (``TICKER.MARKET``) and the provider router.

The ``MARKET`` suffix decides which provider owns a symbol, so adding a market
(e.g. Taiwan) is a router entry plus one provider — nothing downstream changes.
See ``docs/ARCHITECTURE.md`` §1 and §8.
"""

from __future__ import annotations

from dataclasses import dataclass

# Known markets and their reporting currency. Extend here when adding a market.
MARKET_CURRENCY: dict[str, str] = {
    "US": "USD",
    "TW": "TWD",  # TWSE (listed)
    "TWO": "TWD",  # TPEX / OTC
}


class SymbolError(ValueError):
    """Raised for a malformed or unknown canonical symbol."""


@dataclass(frozen=True, slots=True)
class Symbol:
    """A parsed canonical symbol, e.g. ``Symbol("AAPL", "US")``."""

    ticker: str
    market: str

    @property
    def canonical(self) -> str:
        return f"{self.ticker}.{self.market}"

    @property
    def currency(self) -> str:
        return MARKET_CURRENCY[self.market]

    def __str__(self) -> str:
        return self.canonical


def parse_symbol(symbol: str) -> Symbol:
    """Parse ``TICKER.MARKET`` into a :class:`Symbol`.

    Raises :class:`SymbolError` for bare tickers or unknown markets — surfacing
    schema violations loudly rather than guessing a market.
    """
    if "." not in symbol:
        raise SymbolError(f"{symbol!r} is not canonical; expected TICKER.MARKET (e.g. AAPL.US)")
    ticker, _, market = symbol.rpartition(".")
    ticker, market = ticker.strip().upper(), market.strip().upper()
    if not ticker:
        raise SymbolError(f"{symbol!r} has an empty ticker")
    if market not in MARKET_CURRENCY:
        raise SymbolError(
            f"unknown market {market!r} in {symbol!r}; known: {sorted(MARKET_CURRENCY)}"
        )
    return Symbol(ticker, market)
