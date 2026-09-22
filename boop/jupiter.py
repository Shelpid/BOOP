from __future__ import annotations

import base64

import httpx


class Jupiter:
    """Jupiter Swap API v1: /quote + /swap."""

    def __init__(self, base: str, http: httpx.AsyncClient, api_key: str | None = None):
        self.base = base
        self.http = http
        self.headers = {"x-api-key": api_key} if api_key else {}

    async def quote(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> dict | None:
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount)),
            "slippageBps": str(slippage_bps),
            "restrictIntermediateTokens": "true",
            "maxAccounts": "33",
        }
        r = await self.http.get(f"{self.base}/quote", params=params, headers=self.headers, timeout=15)
        if r.status_code != 200:
            return None
        q = r.json()
        return q if q.get("outAmount") else None

    async def swap_tx(self, quote: dict, user_pubkey: str, priority_max_lamports: int) -> bytes:
        body = {
            "quoteResponse": quote,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "dynamicSlippage": True,
            "prioritizationFeeLamports": {
                "priorityLevelWithMaxLamports": {"priorityLevel": "veryHigh", "maxLamports": priority_max_lamports}
            },
        }
        r = await self.http.post(f"{self.base}/swap", json=body, headers=self.headers, timeout=20)
        r.raise_for_status()
        return base64.b64decode(r.json()["swapTransaction"])
