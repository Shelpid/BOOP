from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


@dataclass
class Candidate:
    mint: str
    symbol: str
    liquidity_usd: float
    fdv_usd: float
    age_min: float
    price_usd: float
    dex: str
    url: str


class Sniffer:
    """Finds fresh Solana tokens via DexScreener (latest profiles + boosts + your watchlist)."""

    def __init__(self, base: str, http: httpx.AsyncClient, watchlist: list[str] | None = None):
        self.base = base
        self.http = http
        self.watchlist = watchlist or []

    async def _get(self, path: str):
        r = await self.http.get(f"{self.base}{path}", timeout=15)
        r.raise_for_status()
        return r.json()

    async def fresh_mints(self) -> list[str]:
        mints: list[str] = list(self.watchlist)
        for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1"):
            try:
                data = await self._get(path)
            except httpx.HTTPError:
                continue
            for item in data if isinstance(data, list) else []:
                if item.get("chainId") == "solana" and item.get("tokenAddress"):
                    mints.append(item["tokenAddress"])
        seen, out = set(), []
        for m in mints:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    async def describe(self, mints: list[str]) -> list[Candidate]:
        out: list[Candidate] = []
        now_ms = time.time() * 1000
        for i in range(0, len(mints), 30):
            chunk = mints[i : i + 30]
            try:
                pairs = await self._get(f"/tokens/v1/solana/{','.join(chunk)}")
            except httpx.HTTPError:
                continue
            best: dict[str, dict] = {}
            for p in pairs if isinstance(pairs, list) else []:
                mint = p.get("baseToken", {}).get("address")
                if mint not in chunk:
                    continue
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                if mint not in best or liq > float((best[mint].get("liquidity") or {}).get("usd") or 0):
                    best[mint] = p
            for mint, p in best.items():
                created = p.get("pairCreatedAt") or now_ms
                out.append(
                    Candidate(
                        mint=mint,
                        symbol=(p.get("baseToken", {}).get("symbol") or "???")[:10],
                        liquidity_usd=float((p.get("liquidity") or {}).get("usd") or 0),
                        fdv_usd=float(p.get("fdv") or p.get("marketCap") or 0),
                        age_min=max(0.0, (now_ms - created) / 60000),
                        price_usd=float(p.get("priceUsd") or 0),
                        dex=p.get("dexId", "?"),
                        url=p.get("url", ""),
                    )
                )
        return out
