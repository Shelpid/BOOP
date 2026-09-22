from __future__ import annotations

import asyncio
import base64

import httpx


class RpcError(RuntimeError):
    pass


class Rpc:
    """Minimal async Solana JSON-RPC client (only what BOOP needs)."""

    def __init__(self, url: str, http: httpx.AsyncClient):
        self.url = url
        self.http = http
        self._id = 0

    async def call(self, method: str, params: list | None = None):
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []}
        r = await self.http.post(self.url, json=body, timeout=20)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RpcError(f"{method}: {data['error']}")
        return data["result"]

    async def balance(self, pubkey: str) -> int:
        res = await self.call("getBalance", [pubkey, {"commitment": "confirmed"}])
        return int(res["value"])

    async def account_data(self, pubkey: str) -> bytes | None:
        res = await self.call("getAccountInfo", [pubkey, {"encoding": "base64", "commitment": "confirmed"}])
        if not res or not res.get("value"):
            return None
        return base64.b64decode(res["value"]["data"][0])

    async def token_balance(self, owner: str, mint: str) -> int:
        res = await self.call(
            "getTokenAccountsByOwner",
            [owner, {"mint": mint}, {"encoding": "jsonParsed", "commitment": "confirmed"}],
        )
        total = 0
        for acc in res.get("value", []):
            info = acc["account"]["data"]["parsed"]["info"]
            total += int(info["tokenAmount"]["amount"])
        return total

    async def send(self, raw_tx: bytes) -> str:
        return await self.call(
            "sendTransaction",
            [base64.b64encode(raw_tx).decode(), {"encoding": "base64", "skipPreflight": True, "maxRetries": 3}],
        )

    async def confirm(self, sig: str, timeout: float = 60) -> bool:
        waited = 0.0
        while waited < timeout:
            res = await self.call("getSignatureStatuses", [[sig], {"searchTransactionHistory": False}])
            st = res["value"][0]
            if st:
                if st.get("err"):
                    raise RpcError(f"tx {sig[:8]}… failed: {st['err']}")
                if st.get("confirmationStatus") in ("confirmed", "finalized"):
                    return True
            await asyncio.sleep(1.5)
            waited += 1.5
        return False
