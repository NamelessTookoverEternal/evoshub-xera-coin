"""Global ledger: confirmed on-chain claims are listed with Pure XERA transfers (masked IDs only)."""
import sys
import types
import unittest
from unittest import mock


class _Q:
    def __init__(self, data, fail=False):
        self.data, self.fail = data, fail
    def select(self, *a, **k): return self
    def order(self, *a, **k): return self
    def range(self, *a, **k): return self
    def execute(self):
        if self.fail:
            raise RuntimeError("relation does not exist")
        return types.SimpleNamespace(data=self.data)


class _SB:
    def __init__(self, tables): self.tables = tables
    def table(self, name): return self.tables[name]


ACTIVITY = [
    {"kind": "onchain", "ref": 7, "sender": "XR-7…P2Q", "recipient": None, "amount": 1000, "status": "CONFIRMED", "created_at": "2026-11-29T10:00:00Z"},
    {"kind": "p2p", "ref": 3, "sender": "XR-A…H79", "recipient": "XR-B…K22", "amount": 10, "status": "COMPLETED", "created_at": "2026-11-29T09:00:00Z"},
]


class GlobalLedgerOnchain(unittest.TestCase):
    def _call(self, tables):
        from xera import p2p
        with mock.patch.object(p2p, "supabase", _SB(tables)):
            fn = getattr(p2p.p2p_public_ledger, "__wrapped__", p2p.p2p_public_ledger)
            return fn(mock.Mock(), 50, 0)

    def test_onchain_and_p2p_rows(self):
        out = self._call({"xera_public_activity": _Q(ACTIVITY)})
        rows = out["transfers"]
        self.assertEqual(rows[0]["kind"], "onchain")
        self.assertEqual(rows[0]["amount"], 1000)
        self.assertIsNone(rows[0]["recipient"])
        self.assertEqual(rows[1]["kind"], "p2p")
        for r in rows:
            self.assertEqual(set(r), {"id", "kind", "sender", "recipient", "amount", "status", "created_at"})

    def test_falls_back_to_transfers_when_view_missing(self):
        old = [{"id": 1, "sender": "XR-A…H79", "recipient": "XR-B…K22", "amount": 5, "status": "COMPLETED", "created_at": "x"}]
        out = self._call({"xera_public_activity": _Q([], fail=True), "xera_p2p_public_ledger": _Q(old)})
        self.assertEqual(out["transfers"][0]["kind"], "p2p")


if __name__ == "__main__":
    unittest.main()
