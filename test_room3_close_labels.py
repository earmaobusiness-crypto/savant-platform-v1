"""FIFO Alpaca closes must still get the next unused lot TF/letter."""

from room3_engine import lots


class _S:
    def __init__(self):
        self.room3_lot_close_labels = []
        self.room3_lots = []
        self.room3_trade_history = []
        self.room3_fill_meta_by_ticker = {}

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


def test_stamp_unlabeled_history_after_lot_close():
    """Pulse used to skip already-seen FIFO rows — retry after close_lot queues the letter."""
    ss = _S()
    ss.room3_trade_history = [
        {
            "id": "alpaca-fill-x",
            "ticker": "TNON",
            "timeframe": "—",
            "strategy": "Alpaca",
            "qty": 3,
            "status": "closed · alpaca",
            "exit_price": 4.12,
            "exit_time": "10:19:13",
        }
    ]
    lots.append_lot(
        ss,
        {
            "id": "lot-5a",
            "ticker": "TNON",
            "tf": "1m",
            "strategy": "5A (1M)",
            "qty": 3,
            "entry_px": 4.32,
        },
    )
    opens = lots.open_lots(ss, "TNON")
    assert opens
    lots.close_lot(ss, str(opens[0]["id"]))
    n = lots.stamp_unlabeled_closes(ss, peel_open=False)
    assert n == 1
    row = ss.room3_trade_history[0]
    assert row["timeframe"] == "1m"
    assert row["strategy"] == "5A (1M)"
    assert row["matrix_timeframe"] == "1m"
    assert row["matrix_strategy"] == "5A (1M)"


def test_stamp_close_row_from_entry_fill_cache():
    ss = _S()
    lots.remember_entry_fill(
        ss,
        {
            "ticker": "TNON",
            "tf": "15m",
            "strategy": "1C (15M)",
            "qty": 14,
            "lot_id": "lot-1c",
        },
    )
    stamped = lots.stamp_close_row(
        ss,
        {
            "id": "alpaca-fill-y",
            "ticker": "TNON",
            "timeframe": "—",
            "strategy": "Alpaca",
            "qty": 14,
            "status": "closed · alpaca",
            "exit_price": 4.12,
        },
        peel_open=False,
    )
    assert stamped["timeframe"] == "15m"
    assert stamped["strategy"] == "1C (15M)"


def test_open_lots_skips_qty_zero():
    ss = _S()
    lots.append_lot(
        ss,
        {
            "ticker": "TNON",
            "tf": "5m",
            "strategy": "8B (5M)",
            "qty": 0,
            "entry_px": 4.11,
            "id": "lot-zero",
        },
    )
    lots.append_lot(
        ss,
        {
            "ticker": "TNON",
            "tf": "1m",
            "strategy": "5A (1M)",
            "qty": 3,
            "entry_px": 4.32,
            "id": "lot-live",
        },
    )
    opens = lots.open_lots(ss, "TNON")
    assert [r["id"] for r in opens] == ["lot-live"]


def test_reconcile_ghost_lots_to_broker_pile():
    ss = _S()
    lots.append_lot(
        ss,
        {
            "ticker": "TNON",
            "tf": "5m",
            "strategy": "8B (5M)",
            "qty": 5,
            "entry_px": 4.11,
            "id": "lot-old",
        },
    )
    lots.append_lot(
        ss,
        {
            "ticker": "TNON",
            "tf": "1m",
            "strategy": "2D (1M)",
            "qty": 3,
            "entry_px": 5.29,
            "id": "lot-new",
        },
    )
    n = lots.reconcile_to_broker(ss, [{"ticker": "TNON", "qty": 3}])
    assert n >= 1
    opens = lots.open_lots(ss, "TNON")
    assert sum(float(r["qty"]) for r in opens) == 3
    assert opens[0]["id"] == "lot-new"


def test_stamp_leftover_fifo_by_entry_print():
    """Second Alpaca slice of the same buy still gets that lot's letter."""
    ss = _S()
    lots.remember_entry_fill(
        ss,
        {
            "ticker": "FTFT",
            "tf": "5m",
            "strategy": "2C (5M)",
            "qty": 10,
            "entry_time": "15:00:38",
            "entry_px": 7.46,
            "lot_id": "lot-2c",
        },
    )
    leftover = lots.stamp_close_row(
        ss,
        {
            "id": "fifo-leftover",
            "ticker": "FTFT",
            "timeframe": "—",
            "strategy": "Alpaca",
            "qty": 1,
            "entry_time": "15:00:56",
            "entry_price": 7.44,
            "status": "closed · alpaca",
        },
        peel_open=False,
    )
    assert leftover["strategy"] == "2C (5M)"
    assert leftover["timeframe"] == "5m"


def test_append_lot_remembers_fill_for_leftover():
    """Tab fills used to skip remember_entry_fill — leftover FIFO then came in as dashes."""
    ss = _S()
    lots.append_lot(
        ss,
        {
            "ticker": "PDSB",
            "tf": "1m",
            "strategy": "4A (1M)",
            "qty": 10,
            "entry_px": 0.608,
            "entry_time": "11:08:00",
        },
    )
    leftover = lots.stamp_close_row(
        ss,
        {
            "id": "pdsb-fifo",
            "ticker": "PDSB",
            "timeframe": "—",
            "strategy": "Alpaca",
            "qty": 1,
            "entry_time": "11:08:12",
            "entry_price": 0.607,
            "status": "closed · alpaca",
        },
        peel_open=False,
    )
    assert leftover["strategy"] == "4A (1M)"
    assert leftover["timeframe"] == "1m"


def test_stamp_from_closed_lot_without_fill_cache():
    ss = _S()
    lots.append_lot(
        ss,
        {
            "id": "lot-9a",
            "ticker": "SUGP",
            "tf": "15m",
            "strategy": "9A (15M)",
            "qty": 168,
            "entry_px": 0.7774,
            "entry_time": "11:43:08",
        },
    )
    ss.room3_fill_meta_by_ticker = {}
    closed = lots.close_lot(ss, "lot-9a")
    assert closed is not None
    ss.room3_lot_close_labels = []
    stamped = lots.stamp_close_row(
        ss,
        {
            "id": "sugp-fifo",
            "ticker": "SUGP",
            "timeframe": "—",
            "strategy": "Alpaca",
            "qty": 168,
            "entry_time": "11:43:08",
            "entry_price": 0.7774,
            "status": "closed · alpaca",
        },
        peel_open=False,
    )
    assert stamped["strategy"] == "9A (15M)"
    assert stamped["timeframe"] == "15m"


def test_heal_pads_single_lot_to_broker_pile():
    ss = _S()
    lots.append_lot(
        ss,
        {
            "ticker": "ADBT",
            "tf": "5m",
            "strategy": "2D (5M)",
            "qty": 113,
            "entry_px": 0.11,
        },
    )
    n = lots.heal_lots_from_watch(
        ss,
        {
            "lines": {
                "ADBT|5m": {
                    "ticker": "ADBT",
                    "timeframe": "5m",
                    "state": "in",
                    "entry_strategy": "2D (5M)",
                    "entry_qty": 113,
                }
            }
        },
        [{"ticker": "ADBT", "qty": 2533}],
    )
    assert n == 1
    opens = lots.open_lots(ss, "ADBT")
    assert len(opens) == 1
    assert abs(float(opens[0]["qty"]) - 2533) < 1e-9
    assert opens[0]["letter"] == "2D (5M)"


def test_heal_creates_lot_from_lone_in_line():
    ss = _S()
    n = lots.heal_lots_from_watch(
        ss,
        {
            "lines": {
                "MYSZ|15m": {
                    "ticker": "MYSZ",
                    "timeframe": "15m",
                    "state": "in",
                    "entry_strategy": "1A (15M)",
                    "entry_layout": "Layout 1",
                    "entry_qty": 45,
                    "entry_price": 2.3,
                    "entry_time": "13:00:28",
                }
            }
        },
        [{"ticker": "MYSZ", "qty": 45}],
    )
    assert n == 1
    opens = lots.open_lots(ss, "MYSZ")
    assert len(opens) == 1
    assert opens[0]["tf"] == "15m"
    assert "1A" in str(opens[0]["letter"])
    leftover = lots.stamp_close_row(
        ss,
        {
            "id": "mysz-flat",
            "ticker": "MYSZ",
            "timeframe": "—",
            "strategy": "Alpaca",
            "qty": 45,
            "entry_time": "13:00:29",
            "entry_price": 2.2985,
            "status": "closed · flatten",
        },
        peel_open=False,
    )
    assert leftover["timeframe"] == "15m"


def test_heal_does_not_guess_two_letters():
    ss = _S()
    n = lots.heal_lots_from_watch(
        ss,
        {
            "lines": {
                "ADBT|5m-8b": {
                    "ticker": "ADBT",
                    "timeframe": "5m",
                    "state": "in",
                    "entry_strategy": "8B (5M)",
                    "entry_qty": 10,
                },
                "ADBT|5m-2d": {
                    "ticker": "ADBT",
                    "timeframe": "5m",
                    "state": "in",
                    "entry_strategy": "2D (5M)",
                    "entry_qty": 100,
                },
            }
        },
        [{"ticker": "ADBT", "qty": 110}],
    )
    assert n == 0
    assert lots.open_lots(ss, "ADBT") == []


def test_stamp_does_not_borrow_an_earlier_letter():
    """A later BMGL entry is not yesterday's 2B just because the ticker matches."""
    ss = _S()
    lots.remember_entry_fill(
        ss,
        {
            "ticker": "BMGL",
            "tf": "5m",
            "strategy": "2B (5M)",
            "qty": 2,
            "entry_time": "12:44:44",
            "entry_px": 7.45,
        },
    )
    later = lots.stamp_close_row(
        ss,
        {
            "id": "bmgl-later",
            "ticker": "BMGL",
            "timeframe": "—",
            "strategy": "Alpaca",
            "qty": 7,
            "entry_time": "15:04:31",
            "entry_price": 7.4586,
            "status": "closed · flatten",
        },
        peel_open=False,
    )
    assert lots.row_needs_identity(later) is True


if __name__ == "__main__":
    test_take_close_label_ignores_alpaca_placeholder()
    test_stamp_unlabeled_history_after_lot_close()
    test_stamp_close_row_from_entry_fill_cache()
    test_open_lots_skips_qty_zero()
    test_reconcile_ghost_lots_to_broker_pile()
    test_stamp_leftover_fifo_by_entry_print()
    test_append_lot_remembers_fill_for_leftover()
    test_stamp_from_closed_lot_without_fill_cache()
    test_heal_pads_single_lot_to_broker_pile()
    test_heal_creates_lot_from_lone_in_line()
    test_heal_does_not_guess_two_letters()
    test_stamp_does_not_borrow_an_earlier_letter()
    print("ok")
