"""EIP-712 ticket signer for LfepMining.

Mirrors /root/aster_dashboard/aster_auth.py: load private key once from a file,
expose a sign_ticket(...) → dict that returns all fields needed for the
contract's claim() entrypoint.

Domain must match LfepMining contract verbatim:
  name    = "LfepMining"
  version = "1"
  chainId = 8453 (Base mainnet)
  verifyingContract = deployed mining contract address
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import to_checksum_address

KEY_FILE = os.environ.get("LFEP_SIGNER_KEY_FILE", "/root/.lfep_signer_key")
TICKET_TTL = int(os.environ.get("LFEP_TICKET_TTL", "300"))  # 5 min default

TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Claim": [
        {"name": "agent", "type": "address"},
        {"name": "questionId", "type": "uint256"},
        {"name": "amount", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
        {"name": "expiry", "type": "uint256"},
    ],
}


@dataclass
class TicketSigner:
    private_key: str
    signer_addr: str
    chain_id: int
    verifying_contract: str

    @classmethod
    def from_file(
        cls,
        path: str = KEY_FILE,
        verifying_contract: str | None = None,
        chain_id: int = 8453,
    ) -> "TicketSigner":
        pk = open(path).read().strip()
        if not pk.startswith("0x"):
            pk = "0x" + pk
        acct = Account.from_key(pk)
        vc = verifying_contract or os.environ.get("LFEP_MINING_CONTRACT", "")
        if not vc:
            raise RuntimeError(
                "verifying_contract must be set (constructor arg or "
                "LFEP_MINING_CONTRACT env var) before signing"
            )
        return cls(
            private_key=pk,
            signer_addr=acct.address,
            chain_id=chain_id,
            verifying_contract=vc,
        )

    def _domain(self) -> dict:
        return {
            "name": "LfepMining",
            "version": "1",
            "chainId": self.chain_id,
            "verifyingContract": self.verifying_contract,
        }

    def sign_ticket(self, agent: str, question_id: int, amount: int) -> dict:
        """Sign a Claim ticket and return all fields needed by the frontend.

        amount is in wei (uint256). Frontend submits the dict to the contract.
        """
        nonce = time.time_ns()
        expiry = int(time.time()) + TICKET_TTL
        message = {
            "agent": to_checksum_address(agent),
            "questionId": question_id,
            "amount": amount,
            "nonce": nonce,
            "expiry": expiry,
        }
        typed = {
            "types": TYPES,
            "primaryType": "Claim",
            "domain": self._domain(),
            "message": message,
        }
        encoded = encode_typed_data(full_message=typed)
        sig = Account.sign_message(encoded, private_key=self.private_key).signature.hex()
        if not sig.startswith("0x"):
            sig = "0x" + sig
        return {
            "agent": message["agent"],
            "questionId": question_id,
            "amount": str(amount),
            "nonce": str(nonce),
            "expiry": expiry,
            "signature": sig,
        }


if __name__ == "__main__":
    import json
    s = TicketSigner.from_file(
        verifying_contract="0x0000000000000000000000000000000000000000"
    )
    print(json.dumps({"signer": s.signer_addr}, indent=2))
    example = s.sign_ticket("0x67c8e84444abab63091f958dbe9f733ef52909c0", 42, 20_000 * 10**18)
    print(json.dumps(example, indent=2))
