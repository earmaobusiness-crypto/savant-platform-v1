"""FIFO Alpaca closes must still get the next unused lot TF/letter."""

from room3_engine import lots


class _S:
    def __init__(self):
        self.room3_lot_close_labels = []

    def get(self, k, default=None):
        return getattr(self, k, default)


def test_take_close_label_ignores_alpaca_placeholder():
    ss = _S()
    lots.queue_close_label(
        ss,
        {
            "ticker": "TNON",
            "tf": "1m",
            "letter": "5A (1M)",
            "strategy": "5A (1M)",
            "qty": 3,
            "entry_px": 4.32,
            "id": "lot-5a",
        },
    )
    lots.queue_close_label(
        ss,
        {
            "ticker": "TNON",
            "tf": "15m",
            "letter": "1C (15M)",
            "strategy": "1C (15M)",
            "qty": 14,
            "entry_px": 4.44,
            "id": "lot-1c",
        },
    )
    first = lots.take_close_label(
        ss, "TNON", qty=3, letter="Alpaca", tf="—"
    )
    assert first is not None
    assert first["letter"] == "5A (1M)"
    assert first["tf"] == "1m"
    second = lots.take_close_label(
        ss, "TNON", qty=14, letter="Alpaca", tf="—"
    )
    assert second is not None
    assert second["letter"] == "1C (15M)"
    assert second["tf"] == "15m"


if __name__ == "__main__":
    test_take_close_label_ignores_alpaca_placeholder()
    print("ok")
