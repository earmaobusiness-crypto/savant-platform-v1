"""
Room 3 matrix DNA matching — live map slices vs saved layout vectors.

Self-contained (no Room 2 imports). Uses repertoire from room3_bridge.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, time as dtime
from typing import Any

import room3_engine
import room3_recipes
import room3_review_learn

room3_lots = room3_engine.lots

MATCH_THRESHOLD_PCT = 85
CHILD_READY_PCT = 84  # show a strategy sub-lane; fire still waits for MATCH_THRESHOLD
EXIT_MATCH_FLOOR_PCT = 65
STOP_LOSS_PCT = 2.5
# 1m lookback-low cannot sit deeper than this from fill (operator 2026-09-19).
# Floor (2% / 3A 3.5%) still blocks a tighter-than-floor stop. Targets unchanged.
ONE_M_STOP_CAP_PCT = 3.5
# 5B (1M) execution — DNA still detects; this is the shot.
# Belt replay (Yahoo 1m, 2026-09-02..11): dump ≥6% + RVOL≥3, first of day,
# lookback-low stop, half of ~33% pack structural. Not a next-ticket promise.
FIVE_B_DUMP_RANGE_PCT = 6.0
FIVE_B_VOL_MULT = 2.0
FIVE_B_RVOL_MIN = 3.0
FIVE_B_LOOKBACK_BARS = 5
FIVE_B_STOP_FLOOR_PCT = 2.0
FIVE_B_TARGET_FRAC = 0.165  # half of stored ~33% structural
FIVE_B_HOLD_SEC = 8 * 60  # only leftover 1R lots (5b_range_1r)
FIVE_B_COOL_SEC = 15 * 60
FIVE_B_SKIP_UNTIL = dtime(9, 45)
FIVE_B_EXIT_STYLE = "5b_pack_half"
FIVE_B_EXIT_STYLE_LEGACY = "5b_range_1r"
# 2A (1M) — still the up-window gene; live tape must look like the packs
# (window still going up, fat bar, RVOL), then dip/pack tactics.
# Belt replay Yahoo 1m 2026-09-02..11. Not a next-ticket promise.
TWO_A_VEL_PCT = 10.0
TWO_A_BAR_RANGE_PCT = 5.0
TWO_A_RVOL_MIN = 2.0
TWO_A_DIP_FRAC = 0.01
TWO_A_TARGET_FRAC = 0.10  # clipped for WR ≥51% on the Sep belt
TWO_A_SKIP_UNTIL = dtime(10, 0)
TWO_A_EXIT_STYLE = "2a_pack_half"
TWO_A_COOL_SEC = 15 * 60
# 2B (1M) — 9-bar window still up ≥10%, last bar range ≥2%. Not 2A
# (no RVOL/green/5% bar). Yahoo 1m belt 2026-09-02..11.
TWO_B_VEL9_PCT = 10.0
TWO_B_BAR_RANGE_PCT = 2.0
TWO_B_DIP_FRAC = 0.02
TWO_B_TARGET_FRAC = 0.06
TWO_B_SKIP_UNTIL = dtime(9, 45)
TWO_B_EXIT_STYLE = "2b_pack"
TWO_B_COOL_SEC = 15 * 60
# 2C (1M) — slower than 2B: 5-bar ≥4%, 9-bar ≥4%, last bar range ≥3%.
# No RVOL gate (2C almost never prints ≥2). Yahoo 1m belt 2026-09-02..11.
TWO_C_VEL5_PCT = 4.0
TWO_C_VEL9_PCT = 4.0
TWO_C_BAR_RANGE_PCT = 3.0
TWO_C_DIP_FRAC = 0.01
TWO_C_TARGET_FRAC = 0.10
TWO_C_SKIP_UNTIL = dtime(10, 0)
TWO_C_EXIT_STYLE = "2c_pack"
TWO_C_COOL_SEC = 15 * 60
# 3A (1M) — under VWAP + RVOL≥1.5 + last bar ≥1.5%. Wallpaper 3A is tiny bars.
# Noon cut + green reclaim + 3.5% stop floor. Yahoo 1m belt 2026-09-02..11.
THREE_A_RVOL_MIN = 1.5
THREE_A_BAR_RANGE_PCT = 1.5
THREE_A_DIP_FRAC = 0.015
THREE_A_TARGET_FRAC = 0.10
THREE_A_STOP_FLOOR_PCT = 3.5
THREE_A_SKIP_UNTIL = dtime(10, 0)
THREE_A_UNTIL = dtime(12, 0)
THREE_A_EXIT_STYLE = "3a_pack"
THREE_A_COOL_SEC = 15 * 60
# 1A (1M) — one gene, three Handles. Classify the live tape; do not apply
# one recipe to every 1A ≥85% print. Yahoo 1m belt 2026-09-02..11.
ONE_A_RVOL_MIN = 2.0
ONE_A_DIP_FRAC = 0.02
ONE_A_MILD_VEL5 = 8.0
ONE_A_MILD_RNG_PCT = 3.0
ONE_A_MILD_TARGET_FRAC = 0.08
ONE_A_VIOLENT_VEL20 = 20.0
ONE_A_VIOLENT_RNG_PCT = 3.0
ONE_A_VIOLENT_TARGET_FRAC = 0.12
ONE_A_TRIP_VEL20 = 25.0
ONE_A_TRIP_RNG_PCT = 5.0
ONE_A_TRIP_ARM_FRAC = 0.12
ONE_A_TRIP_TRAIL_FRAC = 0.12
ONE_A_SKIP_UNTIL = dtime(9, 45)
ONE_A_LONG_PAUSE = dtime(10, 0)  # trip + mild wait past the open
ONE_A_COOL_SEC = 15 * 60
ONE_A_EXIT_MILD = "1a_mild"
ONE_A_EXIT_VIOLENT = "1a_violent"
ONE_A_EXIT_TRIP = "1a_trip"
ONE_A_EXIT_STYLES = (ONE_A_EXIT_MILD, ONE_A_EXIT_VIOLENT, ONE_A_EXIT_TRIP)
# 2D (1M) — still the 2D gene; Hunt extra is RVOL/green/range + match ≥91.
# Fill now (no dip). Yahoo 1m belt 2026-09-02..11. Not a next-ticket promise.
TWO_D_RVOL_MIN = 3.0
TWO_D_BAR_RANGE_PCT = 3.0
TWO_D_MATCH_MIN = 91
TWO_D_TARGET_FRAC = 0.065
TWO_D_SKIP_UNTIL = dtime(9, 45)
TWO_D_EXIT_STYLE = "2d_pack"
TWO_D_COOL_SEC = 15 * 60
# 4A (1M) — middle 5-bar 3–8%, last bar ≥2%, RVOL <1.5. Not 2A/1A.
# Yahoo 1m belt 2026-09-02..11 WR push. Fill now.
FOUR_A_VEL5_MIN = 3.0
FOUR_A_VEL5_MAX = 8.0
FOUR_A_BAR_RANGE_PCT = 2.0
FOUR_A_RVOL_MAX = 1.5
FOUR_A_TARGET_FRAC = 0.06
FOUR_A_SKIP_UNTIL = dtime(9, 45)
FOUR_A_EXIT_STYLE = "4a_pack"
FOUR_A_COOL_SEC = 15 * 60
# 3B (1M) — under VWAP, last bar ≥2%, RVOL <1.5 (complement of 3A ≥1.5).
# No 3A noon cut. Stop floor 3.5%. Yahoo 1m belt 2026-09-02..11.
THREE_B_BAR_RANGE_PCT = 2.0
THREE_B_RVOL_MAX = 1.5
THREE_B_TARGET_FRAC = 0.16
THREE_B_STOP_FLOOR_PCT = 3.5
THREE_B_SKIP_UNTIL = dtime(10, 0)
THREE_B_EXIT_STYLE = "3b_pack"
THREE_B_COOL_SEC = 15 * 60
# 5A (1M) — 5-bar and 9-bar still down ≥4%, last bar green range ≥2%.
# Not 5B climax. Yahoo 1m belt 2026-09-02..11. Fill now.
FIVE_A_VEL5_PCT = -4.0
FIVE_A_VEL9_PCT = -4.0
FIVE_A_BAR_RANGE_PCT = 2.0
FIVE_A_TARGET_FRAC = 0.10
FIVE_A_SKIP_UNTIL = dtime(9, 45)
FIVE_A_EXIT_STYLE = "5a_pack"
FIVE_A_COOL_SEC = 15 * 60
# 7A (1M) — quiet green, last bar ≥3%, strong close, body ≥1.5%, vel5 −1..3%, RVOL <1.5. Not 2A/4A.
# Yahoo 1m belt 2026-09-02..11 WR + $ push. Fill now. Stop floor 3.5%. Target 8%.
SEVEN_A_VEL5_MIN = -1.0
SEVEN_A_VEL5_MAX = 3.0
SEVEN_A_BAR_RANGE_PCT = 3.0
SEVEN_A_CLOSE_LOC_MIN = 0.55
SEVEN_A_BODY_PCT_MIN = 1.5
SEVEN_A_RVOL_MAX = 1.5
SEVEN_A_TARGET_FRAC = 0.08
SEVEN_A_STOP_FLOOR_PCT = 3.5
SEVEN_A_SKIP_UNTIL = dtime(9, 45)
SEVEN_A_EXIT_STYLE = "7a_pack"
SEVEN_A_COOL_SEC = 15 * 60
# 3C (1M) — above VWAP, last bar ≥4%, RVOL <1.5. Not 3A/3B. Last-green not required.
# No 3A noon cut. Stop floor 3.5%. Target 16%. Yahoo 1m belt $ push.
THREE_C_BAR_RANGE_PCT = 4.0
THREE_C_RVOL_MAX = 1.5
THREE_C_TARGET_FRAC = 0.16
THREE_C_STOP_FLOOR_PCT = 3.5
THREE_C_SKIP_UNTIL = dtime(9, 45)
THREE_C_EXIT_STYLE = "3c_pack"
THREE_C_COOL_SEC = 15 * 60
# 4D (1M) — 5-bar 3–10%, last bar green ≥5%, RVOL ≥1.5, session still up vs first printed open.
# Not 2A/1A/4A. Yahoo 1m belt 2026-09-02..11. Fill now. Stop floor 2%. Target 8%.
FOUR_D_VEL5_MIN = 3.0
FOUR_D_VEL5_MAX = 10.0
FOUR_D_BAR_RANGE_PCT = 5.0
FOUR_D_RVOL_MIN = 1.5
FOUR_D_SESS_UP_MIN = 0.0
FOUR_D_TARGET_FRAC = 0.08
FOUR_D_SKIP_UNTIL = dtime(9, 45)
FOUR_D_EXIT_STYLE = "4d_pack"
FOUR_D_COOL_SEC = 15 * 60
# 4B (1M) — fatter than 4A, not 4D's 5% bar. Vel5 4–9%, last green ≥3%, RVOL ≥1.5, session up ≥8%.
# Skip 10:00. Target 16%. Yahoo 1m belt 2026-09-02..11.
FOUR_B_VEL5_MIN = 4.0
FOUR_B_VEL5_MAX = 9.0
FOUR_B_BAR_RANGE_PCT = 3.0
FOUR_B_RVOL_MIN = 1.5
FOUR_B_SESS_UP_MIN = 8.0
FOUR_B_TARGET_FRAC = 0.16
FOUR_B_SKIP_UNTIL = dtime(10, 0)
FOUR_B_EXIT_STYLE = "4b_pack"
FOUR_B_COOL_SEC = 15 * 60
# 6A (1M) — down-window bounce under VWAP. Vel5 ≤−3%, vel9 ≤−2%, last green ≥2.5%. Not 5A/5B.
# Floor 3.5%. Target 16%. Yahoo 1m belt 2026-09-02..11.
SIX_A_VEL5_MAX = -3.0
SIX_A_VEL9_MAX = -2.0
SIX_A_BAR_RANGE_PCT = 2.5
SIX_A_TARGET_FRAC = 0.16
SIX_A_STOP_FLOOR_PCT = 3.5
SIX_A_SKIP_UNTIL = dtime(9, 45)
SIX_A_EXIT_STYLE = "6a_pack"
SIX_A_COOL_SEC = 15 * 60
# 4C (1M) — calmer than 4A, not 7A strong-close. Vel5 0.5–<3%, last green ≥3%,
# close loc ≥0.40, RVOL <1.5. Target 6%. Yahoo 1m belt 2026-09-02..11.
FOUR_C_VEL5_MIN = 0.5
FOUR_C_VEL5_MAX = 3.0
FOUR_C_BAR_RANGE_PCT = 3.0
FOUR_C_CLOSE_LOC_MIN = 0.40
FOUR_C_RVOL_MAX = 1.5
FOUR_C_TARGET_FRAC = 0.06
FOUR_C_SKIP_UNTIL = dtime(9, 45)
FOUR_C_EXIT_STYLE = "4c_pack"
FOUR_C_COOL_SEC = 15 * 60
# 4E (1M) — quiet fatter window than 4A. Vel5 9–12%, last green ≥4%, RVOL <1.5, session up.
# Not 4B/4D (those need RVOL ≥1.5). Target 8.5%. Yahoo 1m belt 2026-09-02..11.
FOUR_E_VEL5_MIN = 9.0
FOUR_E_VEL5_MAX = 12.0
FOUR_E_BAR_RANGE_PCT = 4.0
FOUR_E_RVOL_MAX = 1.5
FOUR_E_SESS_UP_MIN = 0.0
FOUR_E_TARGET_FRAC = 0.085
FOUR_E_SKIP_UNTIL = dtime(9, 45)
FOUR_E_EXIT_STYLE = "4e_pack"
FOUR_E_COOL_SEC = 15 * 60
# 6B (1M) — milder dump bounce than 6A. Vel5 ≤−2.5%, vel9 ≤0, last green ≥2%, under VWAP.
# Not 6A (that letter is vel5 ≤−3 and vel9 ≤−2). Floor 3.5%. Target 15.5%.
SIX_B_VEL5_MAX = -2.5
SIX_B_VEL9_MAX = 0.0
SIX_B_BAR_RANGE_PCT = 2.0
SIX_B_TARGET_FRAC = 0.155
SIX_B_STOP_FLOOR_PCT = 3.5
SIX_B_SKIP_UNTIL = dtime(9, 45)
SIX_B_EXIT_STYLE = "6b_pack"
SIX_B_COOL_SEC = 15 * 60
# 3D (1M) — quiet above-VWAP sliver under 3C's 4% bar. Last green 3.5–<4%, loc ≥0.55, RVOL <1.5.
# Floor 3.5%. Target 14%. Yahoo 1m belt 2026-09-02..11.
THREE_D_BAR_RANGE_MIN = 3.5
THREE_D_BAR_RANGE_MAX = 4.0
THREE_D_CLOSE_LOC_MIN = 0.55
THREE_D_RVOL_MAX = 1.5
THREE_D_TARGET_FRAC = 0.14
THREE_D_STOP_FLOOR_PCT = 3.5
THREE_D_SKIP_UNTIL = dtime(9, 45)
THREE_D_EXIT_STYLE = "3d_pack"
THREE_D_COOL_SEC = 15 * 60
# 7B (1M) — 7A's smaller last bar. Last green 2.5–<3%, loc ≥0.55, body ≥1.5%, vel5 0–<3%, RVOL <1.5.
# Floor 3.5%. Target 12.5%. Yahoo 1m belt 2026-09-02..11.
SEVEN_B_VEL5_MIN = 0.0
SEVEN_B_VEL5_MAX = 3.0
SEVEN_B_BAR_RANGE_MIN = 2.5
SEVEN_B_BAR_RANGE_MAX = 3.0
SEVEN_B_CLOSE_LOC_MIN = 0.55
SEVEN_B_BODY_PCT_MIN = 1.5
SEVEN_B_RVOL_MAX = 1.5
SEVEN_B_TARGET_FRAC = 0.125
SEVEN_B_STOP_FLOOR_PCT = 3.5
SEVEN_B_SKIP_UNTIL = dtime(9, 45)
SEVEN_B_EXIT_STYLE = "7b_pack"
SEVEN_B_COOL_SEC = 15 * 60
# 3G (1M) — loud above-VWAP. Last bar ≥4%, RVOL ≥1.5, session up ≥8%. Not 3C (quiet) / 4B / 4D.
# Floor 3.5%. Target 10%. Yahoo 1m belt 2026-09-02..11.
THREE_G_BAR_RANGE_PCT = 4.0
THREE_G_RVOL_MIN = 1.5
THREE_G_SESS_UP_MIN = 8.0
THREE_G_TARGET_FRAC = 0.10
THREE_G_STOP_FLOOR_PCT = 3.5
THREE_G_SKIP_UNTIL = dtime(9, 45)
THREE_G_EXIT_STYLE = "3g_pack"
THREE_G_COOL_SEC = 15 * 60
# 3F (1M) — quiet above-VWAP smaller than 3D. Last green 2–<3.5%, RVOL <1.5, session up ≥8%.
# Floor 3.5%. Target 12.5%. Skip 10:00. Yahoo 1m belt 2026-09-02..11.
THREE_F_BAR_RANGE_MIN = 2.0
THREE_F_BAR_RANGE_MAX = 3.5
THREE_F_RVOL_MAX = 1.5
THREE_F_SESS_UP_MIN = 8.0
THREE_F_TARGET_FRAC = 0.125
THREE_F_STOP_FLOOR_PCT = 3.5
THREE_F_SKIP_UNTIL = dtime(10, 0)
THREE_F_EXIT_STYLE = "3f_pack"
THREE_F_COOL_SEC = 15 * 60
# 8A (1M) — leftover loud loc-strong bar after a cooled window. Last green ≥2%,
# loc ≥0.60, vel5 −2–<2%, RVOL ≥1.5, session up ≥5%. Skip 10:00. Floor 3.5%. Target 12.5%.
# Yahoo 1m belt 2026-09-02..11. Not 1A / 2A / 4* / 3* / 5A / 5B / 6A / 6B / 7A / 7B.
EIGHT_A_VEL5_MIN = -2.0
EIGHT_A_VEL5_MAX = 2.0
EIGHT_A_BAR_RANGE_PCT = 2.0
EIGHT_A_CLOSE_LOC_MIN = 0.60
EIGHT_A_RVOL_MIN = 1.5
EIGHT_A_SESS_UP_MIN = 5.0
EIGHT_A_TARGET_FRAC = 0.125
EIGHT_A_STOP_FLOOR_PCT = 3.5
EIGHT_A_SKIP_UNTIL = dtime(10, 0)
EIGHT_A_EXIT_STYLE = "8a_pack"
EIGHT_A_COOL_SEC = 15 * 60
# 7C (1M) — 7B's smaller last bar. Last green 2–<2.5%, loc ≥0.70, vel5 −1–<2%, RVOL <1.5.
# Skip 10:00. Floor 3.5%. Target 18%. Yahoo 1m belt 2026-09-02..11. Not 7A / 7B.
SEVEN_C_VEL5_MIN = -1.0
SEVEN_C_VEL5_MAX = 2.0
SEVEN_C_BAR_RANGE_MIN = 2.0
SEVEN_C_BAR_RANGE_MAX = 2.5
SEVEN_C_CLOSE_LOC_MIN = 0.70
SEVEN_C_RVOL_MAX = 1.5
SEVEN_C_TARGET_FRAC = 0.18
SEVEN_C_STOP_FLOOR_PCT = 3.5
SEVEN_C_SKIP_UNTIL = dtime(10, 0)
SEVEN_C_EXIT_STYLE = "7c_pack"
SEVEN_C_COOL_SEC = 15 * 60
# 3E (1M) — quiet above-VWAP leftover of 3F. Last bar 2–<3.5%, loc ≥0.50, RVOL <1.5, session up ≥0.
# Last-green not required. Floor 3.5%. Target 17%. Skip 10:00. Not 3F / 4A.
THREE_E_BAR_RANGE_MIN = 2.0
THREE_E_BAR_RANGE_MAX = 3.5
THREE_E_CLOSE_LOC_MIN = 0.50
THREE_E_RVOL_MAX = 1.5
THREE_E_SESS_UP_MIN = 0.0
THREE_E_TARGET_FRAC = 0.17
THREE_E_STOP_FLOOR_PCT = 3.5
THREE_E_SKIP_UNTIL = dtime(10, 0)
THREE_E_EXIT_STYLE = "3e_pack"
THREE_E_COOL_SEC = 15 * 60
# 6C (1M) — milder dump bounce than 6B. Last green ≥2%, vel5 −2 to −0.3%, under VWAP.
# Skip 10:00. Floor 3.5%. Target 14%. Not 6A / 6B / 5A / 5B.
SIX_C_VEL5_MIN = -2.0
SIX_C_VEL5_MAX = -0.3
SIX_C_BAR_RANGE_PCT = 2.0
SIX_C_TARGET_FRAC = 0.14
SIX_C_STOP_FLOOR_PCT = 3.5
SIX_C_SKIP_UNTIL = dtime(10, 0)
SIX_C_EXIT_STYLE = "6c_pack"
SIX_C_COOL_SEC = 15 * 60
# 1A (5M) — fat 5m rip. vel5 ≥10%, last green, last range ≥5%. Fill now. Skip 9:45.
# Floor 2%, no 3.5 cap (cap broke the 5m book). Target 16%. 18% broke WR.
ONE_A_5M_VEL5_MIN = 10.0
ONE_A_5M_BAR_RANGE_PCT = 5.0
ONE_A_5M_TARGET_FRAC = 0.16
ONE_A_5M_STOP_FLOOR_PCT = 2.0
ONE_A_5M_SKIP_UNTIL = dtime(9, 45)
ONE_A_5M_EXIT_STYLE = "1a_5m_pack"
ONE_A_5M_COOL_SEC = 15 * 60
ONE_A_5M_LOOKBACK = 3
# 1B (5M) — medium up, not 1A. vel5 5–<10, last green, last range ≥4%.
# Skip 9:45. Floor 3.5%, no cap. Target 8%.
ONE_B_5M_VEL5_MIN = 5.0
ONE_B_5M_VEL5_MAX = 10.0
ONE_B_5M_BAR_RANGE_PCT = 4.0
ONE_B_5M_TARGET_FRAC = 0.08
ONE_B_5M_STOP_FLOOR_PCT = 3.5
ONE_B_5M_SKIP_UNTIL = dtime(9, 45)
ONE_B_5M_EXIT_STYLE = "1b_5m_pack"
ONE_B_5M_COOL_SEC = 15 * 60
# 5A (5M) — dump bounce. vel5 ≤−2, last green ≥2%, under VWAP. Not 1A / 1B / 5B climax.
# Skip 10:00. Floor 3.5%, no cap. Target 6.5%. 8% broke WR.
FIVE_A_5M_VEL5_MAX = -2.0
FIVE_A_5M_BAR_RANGE_PCT = 2.0
FIVE_A_5M_TARGET_FRAC = 0.065
FIVE_A_5M_STOP_FLOOR_PCT = 3.5
FIVE_A_5M_SKIP_UNTIL = dtime(10, 0)
FIVE_A_5M_EXIT_STYLE = "5a_5m_pack"
FIVE_A_5M_COOL_SEC = 15 * 60
# 1C (5M) — quieter Layout 1 up. vel5 0–<5%, last green ≥3.5%, RVOL <1.5. Not 1A / 1B / 5A.
ONE_C_5M_VEL5_MIN = 0.0
ONE_C_5M_VEL5_MAX = 5.0
ONE_C_5M_BAR_RANGE_PCT = 3.5
ONE_C_5M_RVOL_MAX = 1.5
ONE_C_5M_TARGET_FRAC = 0.14
ONE_C_5M_STOP_FLOOR_PCT = 2.0
ONE_C_5M_SKIP_UNTIL = dtime(9, 45)
ONE_C_5M_EXIT_STYLE = "1c_5m_pack"
ONE_C_5M_COOL_SEC = 15 * 60
# 9A (5M) — dump bounce above VWAP. vel5 ≤−2, last green ≥2.5%. Not 5A (under VWAP).
NINE_A_5M_VEL5_MAX = -2.0
NINE_A_5M_BAR_RANGE_PCT = 2.5
NINE_A_5M_LOC_MIN = 0.50
NINE_A_5M_TARGET_FRAC = 0.075
NINE_A_5M_STOP_FLOOR_PCT = 2.0
NINE_A_5M_SKIP_UNTIL = dtime(9, 45)
NINE_A_5M_EXIT_STYLE = "9a_5m_pack"
NINE_A_5M_COOL_SEC = 15 * 60
# 5B (5M) — dump climax subset of 5A. 5A plus last green ≥4% loc ≥0.50. Skip 10:00. Floor 2%, no cap. Target 8%. 10% broke WR.
FIVE_B_5M_BAR_RANGE_PCT = 4.0
FIVE_B_5M_LOC_MIN = 0.50
FIVE_B_5M_TARGET_FRAC = 0.08
FIVE_B_5M_STOP_FLOOR_PCT = 2.0
FIVE_B_5M_SKIP_UNTIL = dtime(10, 0)
FIVE_B_5M_EXIT_STYLE = "5b_5m_pack"
FIVE_B_5M_COOL_SEC = 15 * 60
# 2B (5M) — leftover 9-bar up. vel9 ≥8%, last green ≥2.5%. Not 1A / 1B / 1C / 5A / 9A / 5B.
# Skip 9:45. Floor 2%, no cap. Target 10%. 12% broke WR.
TWO_B_5M_VEL9_PCT = 8.0
TWO_B_5M_BAR_RANGE_PCT = 2.5
TWO_B_5M_TARGET_FRAC = 0.10
TWO_B_5M_STOP_FLOOR_PCT = 2.0
TWO_B_5M_SKIP_UNTIL = dtime(9, 45)
TWO_B_5M_EXIT_STYLE = "2b_5m_pack"
TWO_B_5M_COOL_SEC = 15 * 60
# 5C (5M) — milder dump than 5A. vel5 −1.5 to under −2, last green ≥2%, under VWAP. Skip 9:45. Floor 3.5%, no cap. Target 8%.
FIVE_C_5M_VEL5_MIN = -2.0
FIVE_C_5M_VEL5_MAX = -1.5
FIVE_C_5M_BAR_RANGE_PCT = 2.0
FIVE_C_5M_TARGET_FRAC = 0.08
FIVE_C_5M_STOP_FLOOR_PCT = 3.5
FIVE_C_5M_SKIP_UNTIL = dtime(9, 45)
FIVE_C_5M_EXIT_STYLE = "5c_5m_pack"
FIVE_C_5M_COOL_SEC = 15 * 60
# 8A (5M) — loud leftover flat-up. vel5 −2–<2, last green ≥2%, loc ≥0.50, RVOL ≥1.5, session ≥8%. Skip 9:45. Floor 2%, no cap. Target 8%. 9% broke WR.
EIGHT_A_5M_VEL5_MIN = -2.0
EIGHT_A_5M_VEL5_MAX = 2.0
EIGHT_A_5M_BAR_RANGE_PCT = 2.0
EIGHT_A_5M_LOC_MIN = 0.50
EIGHT_A_5M_RVOL_MIN = 1.5
EIGHT_A_5M_SESS_PCT = 8.0
EIGHT_A_5M_TARGET_FRAC = 0.08
EIGHT_A_5M_STOP_FLOOR_PCT = 2.0
EIGHT_A_5M_SKIP_UNTIL = dtime(9, 45)
EIGHT_A_5M_EXIT_STYLE = "8a_5m_pack"
EIGHT_A_5M_COOL_SEC = 15 * 60
# 6A (5M) — tighter dump subset of 5A. vel5 ≤−3.5, last green ≥2%, loc ≥0.40, under VWAP. Not 5B. Skip 10:00. Floor 3.5%, no cap. Target 9%.
SIX_A_5M_VEL5_MAX = -3.5
SIX_A_5M_LOC_MIN = 0.40
SIX_A_5M_TARGET_FRAC = 0.09
SIX_A_5M_STOP_FLOOR_PCT = 3.5
SIX_A_5M_SKIP_UNTIL = dtime(10, 0)
SIX_A_5M_EXIT_STYLE = "6a_5m_pack"
SIX_A_5M_COOL_SEC = 15 * 60
# 2C (5M) — origin June–Aug packs. Last-green is not required. Range ≥1.9%, RVOL ≥1.5.
# Not 1A/1B/1C/2B/8A/5A/5B/5C/9A/6A. Skip 9:45. Floor 2%, no cap. Target 8%.
TWO_C_5M_BAR_RANGE_PCT = 1.9
TWO_C_5M_RVOL_MIN = 1.5
TWO_C_5M_TARGET_FRAC = 0.08
TWO_C_5M_STOP_FLOOR_PCT = 2.0
TWO_C_5M_SKIP_UNTIL = dtime(9, 45)
TWO_C_5M_EXIT_STYLE = "2c_5m_pack"
TWO_C_5M_COOL_SEC = 15 * 60
# 2D (5M) — origin June–Aug packs. Last-green is not required. Range ≥0.9%, RVOL ≥1.5.
# Not 2C / 1A/1B/1C/2B/8A/5A/5B/5C/9A/6A. Skip 9:45. Floor 2%, no cap. Target 8%.
TWO_D_5M_BAR_RANGE_PCT = 0.9
TWO_D_5M_RVOL_MIN = 1.5
TWO_D_5M_TARGET_FRAC = 0.08
TWO_D_5M_STOP_FLOOR_PCT = 2.0
TWO_D_5M_SKIP_UNTIL = dtime(9, 45)
TWO_D_5M_EXIT_STYLE = "2d_5m_pack"
TWO_D_5M_COOL_SEC = 15 * 60
# 2A (5M) — origin June–Aug packs. Last-green is not required. Range ≥2%, RVOL ≥1.5.
# Not 1A/1B/1C/2B/8A/5A/5B/5C/9A/6A. Skip 9:45. Floor 2%, no cap. Target 8%.
TWO_A_5M_BAR_RANGE_PCT = 2.0
TWO_A_5M_RVOL_MIN = 1.5
TWO_A_5M_TARGET_FRAC = 0.08
TWO_A_5M_STOP_FLOOR_PCT = 2.0
TWO_A_5M_SKIP_UNTIL = dtime(9, 45)
TWO_A_5M_EXIT_STYLE = "2a_5m_pack"
TWO_A_5M_COOL_SEC = 15 * 60
# 1D (5M) — origin June–Aug packs. Last-green is not required. Range ≥1%, RVOL ≥1.5, vel5 under 3%.
# Not 1A/1B/1C/2C. Skip 9:45. Floor 2%, no cap. Target 8%.
ONE_D_5M_BAR_RANGE_PCT = 1.0
ONE_D_5M_RVOL_MIN = 1.5
ONE_D_5M_VEL5_MAX = 3.0
ONE_D_5M_TARGET_FRAC = 0.08
ONE_D_5M_STOP_FLOOR_PCT = 2.0
ONE_D_5M_SKIP_UNTIL = dtime(9, 45)
ONE_D_5M_EXIT_STYLE = "1d_5m_pack"
ONE_D_5M_COOL_SEC = 15 * 60
# 4A (5M) — origin June–Aug packs. Last-green is not required. vel5 3–<8, range ≥1.5%, RVOL ≥1.5.
# Not 1A/1B/1C. Skip 9:45. Floor 2%, no cap. Target 8%.
FOUR_A_5M_VEL5_MIN = 3.0
FOUR_A_5M_VEL5_MAX = 8.0
FOUR_A_5M_BAR_RANGE_PCT = 1.5
FOUR_A_5M_RVOL_MIN = 1.5
FOUR_A_5M_TARGET_FRAC = 0.08
FOUR_A_5M_STOP_FLOOR_PCT = 2.0
FOUR_A_5M_SKIP_UNTIL = dtime(9, 45)
FOUR_A_5M_EXIT_STYLE = "4a_5m_pack"
FOUR_A_5M_COOL_SEC = 15 * 60
# 6B (5M) — origin June–Aug packs. Last-green is not required. Range ≥2%, RVOL ≥1.5.
SIX_B_5M_BAR_RANGE_PCT = 2.0
SIX_B_5M_RVOL_MIN = 1.5
SIX_B_5M_TARGET_FRAC = 0.08
SIX_B_5M_STOP_FLOOR_PCT = 2.0
SIX_B_5M_SKIP_UNTIL = dtime(9, 45)
SIX_B_5M_EXIT_STYLE = "6b_5m_pack"
SIX_B_5M_COOL_SEC = 15 * 60
# 8B (5M) — origin June–Aug packs. Last-green is not required (origin starts were last red). Range ≥2%, RVOL ≥1.5.
EIGHT_B_5M_BAR_RANGE_PCT = 2.0
EIGHT_B_5M_RVOL_MIN = 1.5
EIGHT_B_5M_TARGET_FRAC = 0.08
EIGHT_B_5M_STOP_FLOOR_PCT = 2.0
EIGHT_B_5M_SKIP_UNTIL = dtime(9, 45)
EIGHT_B_5M_EXIT_STYLE = "8b_5m_pack"
EIGHT_B_5M_COOL_SEC = 15 * 60
# 3A (5M) — origin June–Aug packs. Last-green is not required. Range ≥2%, RVOL ≥1.5.
THREE_A_5M_BAR_RANGE_PCT = 2.0
THREE_A_5M_RVOL_MIN = 1.5
THREE_A_5M_TARGET_FRAC = 0.08
THREE_A_5M_STOP_FLOOR_PCT = 2.0
THREE_A_5M_SKIP_UNTIL = dtime(9, 45)
THREE_A_5M_EXIT_STYLE = "3a_5m_pack"
THREE_A_5M_COOL_SEC = 15 * 60
# 9B (5M) — origin June–Aug packs. Last-green is not required. Range ≥4%. No RVOL gate (origin rvol sat under 1.5).
NINE_B_5M_BAR_RANGE_PCT = 4.0
NINE_B_5M_TARGET_FRAC = 0.08
NINE_B_5M_STOP_FLOOR_PCT = 2.0
NINE_B_5M_SKIP_UNTIL = dtime(9, 45)
NINE_B_5M_EXIT_STYLE = "9b_5m_pack"
NINE_B_5M_COOL_SEC = 15 * 60
# 1A (15M) — leftover Sep 2–11 belt. Last-green is not required. vel5 ≥12%, last range ≥2%. No open skip.
ONE_A_15M_VEL5_MIN = 12.0
ONE_A_15M_BAR_RANGE_PCT = 2.0
ONE_A_15M_TARGET_FRAC = 0.08
ONE_A_15M_STOP_FLOOR_PCT = 2.0
ONE_A_15M_SKIP_UNTIL = dtime(9, 30)
ONE_A_15M_EXIT_STYLE = "1a_15m_pack"
ONE_A_15M_COOL_SEC = 15 * 60
# Other specialized 15m — origin June–Aug packs. Last-green is not required. Range ≥3%. Not 1A. No open skip.
FIFTEEN_M_ORIGIN_BAR_RANGE_PCT = 3.0
FIFTEEN_M_ORIGIN_TARGET_FRAC = 0.12
FIFTEEN_M_ORIGIN_STOP_FLOOR_PCT = 2.0
FIFTEEN_M_ORIGIN_SKIP_UNTIL = dtime(9, 30)
ONE_B_15M_EXIT_STYLE = "1b_15m_pack"
ONE_C_15M_EXIT_STYLE = "1c_15m_pack"
ONE_D_15M_EXIT_STYLE = "1d_15m_pack"
TWO_A_15M_EXIT_STYLE = "2a_15m_pack"
TWO_B_15M_EXIT_STYLE = "2b_15m_pack"
SIX_A_15M_EXIT_STYLE = "6a_15m_pack"
NINE_A_15M_EXIT_STYLE = "9a_15m_pack"
# Placeholder Handle for every other live letter (not 5B / 2A / 1A / 2D / 2B / 2C / 3A / 4A / 3B / 5A / 7A / 3C / 4D / 4B / 6A / 4C / 4E / 6B / 3D / 7B / 3G / 3F / 8A / 7C / 3E / 6C).
# 5m specialized: all live 5m. 15m specialized: 1A / 1B / 1C / 1D / 2A / 2B / 6A / 9A (not 8A / 8B). Gene stays nearest ≥85% same TF.
# Remaining 1m: fill-now at ≥85% (2026-09-17). Other 5m/15m hold after a small dip.
PH_EXIT_STYLE = "ph_pack"
PH_5M_EXIT_STYLE = "ph_5m_trail"
PH_RVOL_MIN = 0.0
PH_DIP_FRAC_1M = 0.01
PH_DIP_FRAC_5M = 0.006
PH_DIP_FRAC_15M = 0.008
PH_5M_STRUCT_FRAC = 0.75  # tag sooner than full structural
PH_5M_TRAIL_FRAC = 0.08  # middle of 5 / 10
PH_15M_TARGET_FRAC = 0.12  # 12% hard clip — Friday never tagged 15/20
PH_SKIP_UNTIL = dtime(9, 45)
PH_COOL_SEC = 15 * 60
# Volatile-day grind: Hunt extras can print several 1m letters on one name.
# Cap shared across letters. Second letter may still add until this count.
ONE_M_NAME_SHOT_MAX = 3
MIN_SLICES = {"1m": 5, "5m": 4, "15m": 3}
PLACEHOLDER_LAYOUTS = frozenset(
    {"NEW_LAYOUT", "PURGATORY_PENDING", "Purgatory", "PURGATORY", "—", "-", ""}
)

# Day book split — these three add to 100% of Trading today.
TF_BUCKET_FRAC: dict[str, float] = {"15m": 0.50, "5m": 0.30, "1m": 0.20}
# Expected fills (opening reservation). Caps stay under ~50 combined max.
TF_PROJECTED_PRIOR: dict[str, int] = {"15m": 3, "5m": 6, "1m": 5}
TF_PROJECTED_CAP: dict[str, int] = {"15m": 6, "5m": 12, "1m": 10}
SCALE_IN_MAX = 1  # one add onto a live winner
SCALE_IN_TARGET_FRAC = 0.50  # add only while P/L is still under half the layout move
SIZE_AT_THRESHOLD = 0.80  # 85% match → 80% of that TF's slot
WARMING_MATCH_PCT = 70  # sticky / warming Err floor (not an entry)


def size_explain(session_state: Any | None = None) -> str:
    snap = tf_budget_snapshot(session_state) if session_state is not None else None
    tradable = float((snap or {}).get("tradable") or 0)
    book_txt = (
        f"Trading today is ${tradable:,.0f}. "
        if tradable > 0
        else "Trading today is the day’s deployable cash. "
    )
    p = (snap or {}).get("projected") or TF_PROJECTED_PRIOR
    n15 = max(1, int(p.get("15m") or 4))
    slot_frac = 1.0 / n15
    return (
        f"{book_txt}"
        "That cash is split into timeframe buckets that add to 100%: "
        f"15m {TF_BUCKET_FRAC['15m']:.0%} · 5m {TF_BUCKET_FRAC['5m']:.0%} · "
        f"1m {TF_BUCKET_FRAC['1m']:.0%}. "
        f"Layouts project about {p.get('15m', 3)} fifteen-minute fills, "
        f"{p.get('5m', 6)} five-minute, {p.get('1m', 5)} one-minute today — "
        f"each full-match 15m therefore starts at 1/{n15} of the 15m bucket "
        f"({slot_frac:.0%} of that 50%). "
        "Those percents are the opening reservation, not walls. "
        "If a TF prints more than expected, it collects leftover from buckets that are "
        "not hot (live < projected). A live 15m that is still in the move can add once "
        "from that same idle cash. If 5m or 1m is the hot book, leftover flows there "
        "instead of sitting in 15m. "
        "Weaker match uses less of its slot. "
        "Uniqueness still cuts size when two strategies are almost equally close. "
        "Match uses median/MAD z-scores (clip ±5) then weighted cosine "
        "(velocity + volume dims lead). "
        "Watch-book Size $ is the planned amount, not a fill."
    )


SIZE_EXPLAIN = (
    "Trading today opens 50% 15m / 30% 5m / 20% 1m. "
    "Leftover is fluid: extra fills and a still-moving 15m collect idle cash "
    "from buckets that are not hot. A hot 5m/1m keeps its pot and can pull quiet 15m leftover."
)


ADAPTIVE_STD_FLOOR = 1e-6
ZSCORE_CLIP = 5.0
# Static DNA weights: velocity (0–2) and volume (3–4) lead. VWAP/Pearson sit back. SEC slot is dead live.
FEATURE_MATCH_WEIGHTS: tuple[float, ...] = (
    1.6,  # 0 session velocity
    1.4,  # 1 peak bar
    1.2,  # 2 mean bar
    1.5,  # 3 log volume σ
    1.3,  # 4 volume z
    0.5,  # 5 last-vs-mean close
    0.0,  # 6 SEC / FinBERT — live is always 0
    0.4,  # 7 Pearson
)


def cosine_similarity(vec_a: list[float], vec_b: list[float], weights: list[float] | None = None) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    w = weights if weights and len(weights) == len(vec_a) else [1.0] * len(vec_a)
    dot = sum(wa * a * b for wa, a, b in zip(w, vec_a, vec_b))
    norm_a = math.sqrt(sum(wa * a * a for wa, a in zip(w, vec_a)))
    norm_b = math.sqrt(sum(wa * b * b for wa, b in zip(w, vec_b)))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(x) for x in values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _adaptive_feature_moments(
    vectors: list[list[float]], dim: int
) -> tuple[list[float], list[float]]:
    """Live-library median + MAD per DNA dim. Near-zero MAD → dim is dropped (z=0)."""
    centers = [0.0] * dim
    scales = [1.0] * dim
    if dim <= 0:
        return centers, scales
    cols: list[list[float]] = [[] for _ in range(dim)]
    for raw in vectors:
        if not raw or len(raw) != dim:
            continue
        for i, x in enumerate(raw):
            cols[i].append(float(x))
    if not cols or len(cols[0]) < 2:
        return centers, scales
    out_c: list[float] = []
    out_s: list[float] = []
    for vals in cols:
        med = _median(vals)
        mad = _median([abs(x - med) for x in vals])
        out_c.append(med)
        out_s.append(mad if mad >= ADAPTIVE_STD_FLOOR else 0.0)
    return out_c, out_s


def _zscore_vec(
    vec: list[float], centers: list[float], scales: list[float]
) -> list[float]:
    out: list[float] = []
    clip = float(ZSCORE_CLIP)
    for x, center, scale in zip(vec, centers, scales):
        if scale <= 0:
            out.append(0.0)
            continue
        z = (float(x) - center) / scale
        if z > clip:
            z = clip
        elif z < -clip:
            z = -clip
        out.append(z)
    return out


def _wallpaper_weights(layouts: list[dict[str, Any]], dim: int) -> list[float]:
    """Inverse-std from the live library. Dead (zero-std) dims get weight 0."""
    vectors = [
        [float(x) for x in (e.get("vector") or [])]
        for e in (layouts or [])
        if (e.get("vector") or []) and len(e.get("vector") or []) == dim
    ]
    _centers, scales = _adaptive_feature_moments(vectors, dim)
    weights: list[float] = []
    for scale in scales:
        if scale <= 0:
            weights.append(0.0)
        else:
            weights.append(max(0.20, min(2.4, 1.0 / scale)))
    return weights if weights else [1.0] * dim


def _pearson_r(values: list[float]) -> float:
    n = len(values)
    if n < 3:
        return 0.0
    mean = sum(values) / n
    num = sum((x - mean) * (i - (n - 1) / 2.0) for i, x in enumerate(values))
    den_x = math.sqrt(sum((i - (n - 1) / 2.0) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((x - mean) ** 2 for x in values))
    if den_x <= 0 or den_y <= 0:
        return 0.0
    return max(-1.0, min(1.0, num / (den_x * den_y)))


def build_live_feature_vector(line: dict[str, Any]) -> list[float] | None:
    """Approximate Room 2 eight-dim DNA vector from watcher bar slices."""
    slices = list(line.get("slices") or [])
    tf = str(line.get("timeframe") or "1m")
    if len(slices) < int(MIN_SLICES.get(tf, 4)):
        return None

    rets = [float(s.get("ret") or 0) for s in slices]
    vols = [float(s.get("v") or 0) for s in slices]
    closes = [float(s.get("c") or 0) for s in slices if float(s.get("c") or 0) > 0]
    if not closes:
        return None

    session_velocity = ((closes[-1] - closes[0]) / closes[0] * 100.0) if closes[0] else 0.0
    peak_bar = max(abs(r) for r in rets) * 100.0
    mean_bar = (sum(abs(r) for r in rets) / len(rets)) * 100.0

    vol_sigma = 0.0
    vol_z = 0.0
    pos_vols = [v for v in vols if v > 0]
    if len(pos_vols) > 1:
        avg_v = sum(pos_vols) / len(pos_vols)
        var_v = sum((v - avg_v) ** 2 for v in pos_vols) / len(pos_vols)
        vol_sigma = math.sqrt(var_v)
        if vol_sigma > 0:
            vol_z = (pos_vols[-1] - avg_v) / vol_sigma

    mean_close = sum(closes) / len(closes)
    vwap_bias = ((closes[-1] - mean_close) / closes[-1] * 100.0) if closes[-1] else 0.0
    pearson = _pearson_r(closes[-8:])
    # Log-volume so share-count sigma cannot crush cosine vs Room 2 envelopes.
    vol_sigma_n = math.log10(1.0 + vol_sigma) if vol_sigma > 0 else 0.0

    return [
        round(session_velocity, 4),
        round(peak_bar, 4),
        round(mean_bar, 4),
        round(vol_sigma_n, 4),
        round(vol_z, 4),
        round(vwap_bias, 4),
        0.0,
        round(pearson, 4),
    ]


def match_spatial(
    snapshot_vec: list[float],
    layouts: list[dict[str, Any]],
    *,
    watch_timeframe: str | None = None,
) -> dict[str, Any]:
    best_cosine = 0.0
    second_cosine = 0.0
    nearest = "—"
    nearest_strategy = ""
    structural_move = 0.0
    best_ticker = ""
    best_tf = ""
    watch_tf = _normalize_watch_tf(watch_timeframe or "")
    dim_ok = [
        e
        for e in (layouts or [])
        if (e.get("vector") or []) and len(e.get("vector") or []) == len(snapshot_vec)
    ]
    usable: list[dict[str, Any]] = []
    for e in dim_ok:
        entry_tf = _layout_dna_tf(e)
        if watch_tf and entry_tf and entry_tf != watch_tf:
            continue
        strat = str(e.get("strategy") or e.get("execution_strategy") or "")
        if room3_recipes.is_purgatory_letter(
            str(e.get("layout_id") or ""), strat
        ):
            continue
        if watch_tf and strat and not room3_recipes.strategy_tf_agrees(strat, watch_tf):
            continue
        usable.append(e)
    dim = len(snapshot_vec)
    lib_vecs = [
        [float(x) for x in (e.get("vector") or [])]
        for e in usable
        if (e.get("vector") or []) and len(e.get("vector") or []) == dim
    ]
    centers, scales = _adaptive_feature_moments(lib_vecs, dim)
    query_z = _zscore_vec([float(x) for x in snapshot_vec], centers, scales)
    dim_w = list(FEATURE_MATCH_WEIGHTS)
    if len(dim_w) < dim:
        dim_w = dim_w + [0.4] * (dim - len(dim_w))
    elif len(dim_w) > dim:
        dim_w = dim_w[:dim]

    ranked_hits: list[dict[str, Any]] = []
    for entry in usable:
        stored = [float(x) for x in (entry.get("vector") or [])]
        cand_z = _zscore_vec(stored, centers, scales)
        # Weighted cosine = weighted dot / (weighted L2 × weighted L2). Match% stays 0–100.
        cos = cosine_similarity(query_z, cand_z, dim_w)
        entry_tf = _layout_dna_tf(entry)
        ranked_hits.append(
            {
                "cosine": cos,
                "layout_id": str(entry.get("layout_id") or "—"),
                "strategy": str(entry.get("strategy") or ""),
                "structural_move_pct": float(entry.get("structural_move_pct") or 0.0),
                "ticker": str(entry.get("ticker") or ""),
                "timeframe": str(entry.get("timeframe_resolution") or entry_tf),
            }
        )
        if cos > best_cosine:
            second_cosine = best_cosine
            best_cosine = cos
            nearest = str(entry.get("layout_id") or "—")
            nearest_strategy = str(entry.get("strategy") or "")
            structural_move = float(entry.get("structural_move_pct") or 0.0)
            best_ticker = str(entry.get("ticker") or "")
            best_tf = str(entry.get("timeframe_resolution") or entry_tf)
        elif cos > second_cosine:
            second_cosine = cos
    ranked_hits.sort(key=lambda h: -float(h.get("cosine") or 0))
    ranked: list[dict[str, Any]] = []
    seen_letters: set[str] = set()
    for hit in ranked_hits:
        if float(hit.get("cosine") or 0) <= 0:
            continue
        token = room3_lots.letter_token(str(hit.get("layout_id") or ""), str(hit.get("strategy") or ""))
        if not token or token in seen_letters:
            continue
        seen_letters.add(token)
        ranked.append(
            {
                "layout_id": hit["layout_id"],
                "strategy": hit["strategy"] or token,
                "letter": token,
                "spatial_match_pct": int(round(float(hit["cosine"]) * 100)),
                "cosine_similarity": round(float(hit["cosine"]), 4),
                "structural_move_pct": float(hit.get("structural_move_pct") or 0),
            }
        )
        if len(ranked) >= 8:
            break
    # No positive hit → do not invent "NEW_LAYOUT" (Room 2 mint jargon). Show blank.
    if best_cosine <= 0:
        nearest = "—"
        nearest_strategy = ""
        structural_move = 0.0
        best_ticker = ""
        best_tf = ""
        ranked = []
    return {
        "spatial_match_pct": int(round(best_cosine * 100)),
        "cosine_similarity": round(best_cosine, 4),
        "second_cosine": round(second_cosine, 4),
        "nearest_layout_id": nearest,
        "nearest_strategy": nearest_strategy,
        "structural_move_pct": structural_move,
        "layout_ticker": best_ticker,
        "layout_timeframe": best_tf,
        "ranked": ranked,
    }


def _normalize_watch_tf(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    named = room3_recipes.strategy_tf_token(text)
    if named:
        return named
    t = text.lower()
    if t in ("1m", "5m", "15m"):
        return t
    return room3_recipes.recipe_timeframe(timeframe=text) or t


def _layout_dna_tf(entry: dict[str, Any]) -> str:
    return room3_recipes.recipe_timeframe(
        strategy=str(entry.get("strategy") or entry.get("execution_strategy") or ""),
        timeframe_norm=str(entry.get("timeframe_norm") or ""),
        timeframe=str(entry.get("timeframe") or ""),
        timeframe_resolution=str(entry.get("timeframe_resolution") or ""),
    )


def strategy_for_layout(
    layout_id: str,
    repertoire: dict[str, Any],
    *,
    timeframe: str = "",
) -> str:
    lid = str(layout_id or "").strip()
    if not lid or lid in PLACEHOLDER_LAYOUTS:
        return "matrix"
    if room3_recipes.is_purgatory_letter(lid, ""):
        return "matrix"
    want = _normalize_watch_tf(timeframe) if timeframe else ""

    def _ok(strat: str) -> bool:
        if not strat:
            return False
        if room3_recipes.is_purgatory_letter(lid, strat):
            return False
        return room3_recipes.strategy_tf_agrees(strat, want) if want else True

    for row in reversed(list(repertoire.get("deploy_registry") or [])):
        if str(row.get("layout") or row.get("layout_id") or "") == lid:
            strat = str(row.get("strategy") or row.get("execution_strategy") or "").strip()
            if _ok(strat):
                return strat
    for row in repertoire.get("layouts") or []:
        if str(row.get("layout_id") or "") == lid:
            strat = str(row.get("strategy") or row.get("execution_strategy") or "").strip()
            if _ok(strat):
                return strat
    return "matrix"


def score_line_against_repertoire(
    line: dict[str, Any],
    repertoire: dict[str, Any],
) -> dict[str, Any]:
    """DNA match result + blended display score for the watch book."""
    layouts = list(repertoire.get("layouts") or [])
    vec = build_live_feature_vector(line)
    if vec:
        line["live_vector"] = vec
    if not vec or not layouts:
        warmth = min(
            1.0,
            len(line.get("slices") or [])
            / float({"1m": 24, "5m": 36, "15m": 48}.get(str(line.get("timeframe") or "1m"), 24)),
        )
        boost = 0.15 if repertoire.get("ready") else 0.0
        return {
            "display_score": round(min(1.0, warmth * 0.6 + boost), 4),
            "spatial_match_pct": 0,
            "nearest_layout_id": "—",
            "vector_ready": False,
            "ranked": [],
        }

    spatial = match_spatial(vec, layouts, watch_timeframe=str(line.get("timeframe") or "1m"))
    pct = int(spatial.get("spatial_match_pct") or 0)
    warmth = min(1.0, len(line.get("slices") or []) / 24.0)
    display = min(1.0, (pct / 100.0) * 0.75 + warmth * 0.15 + (0.10 if repertoire.get("ready") else 0))
    return {
        **spatial,
        "display_score": round(display, 4),
        "vector_ready": True,
    }


def _approaching_day_close() -> bool:
    """Last ~20 minutes of post — take the second-best exit rather than hold overnight."""
    try:
        now = datetime.now(room3_engine.ET)
        if room3_engine.detect_session_window(now) != room3_engine.SESSION_POST:
            return False
        return now.time() >= dtime(19, 40)
    except Exception:
        return False


def _is_5b_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("5B") and "1M" in token


def _is_2a_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("2A") and "1M" in token


def _is_2b_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("2B") and "1M" in token


def _is_2c_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("2C") and "1M" in token


def _is_3a_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("3A") and "1M" in token


def _is_1a_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("1A") and "1M" in token


def _is_2d_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("2D") and "1M" in token


def _is_4a_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("4A") and "1M" in token


def _is_3b_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("3B") and "1M" in token


def _is_5a_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("5A") and "1M" in token


def _is_7a_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("7A") and "1M" in token


def _is_3c_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("3C") and "1M" in token


def _is_4d_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("4D") and "1M" in token


def _is_4b_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("4B") and "1M" in token


def _is_6a_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("6A") and "1M" in token


def _is_4c_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("4C") and "1M" in token


def _is_4e_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("4E") and "1M" in token


def _is_6b_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("6B") and "1M" in token


def _is_3d_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("3D") and "1M" in token


def _is_7b_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("7B") and "1M" in token


def _is_3g_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("3G") and "1M" in token


def _is_3f_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("3F") and "1M" in token


def _is_8a_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("8A") and "1M" in token


def _is_7c_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("7C") and "1M" in token


def _is_3e_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("3E") and "1M" in token


def _is_6c_1m(strategy: str, tf: str = "1m") -> bool:
    if room3_recipes.normalize_tf(tf) != "1m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("6C") and "1M" in token


def _is_1a_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("1A") and "5M" in token


def _is_1b_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("1B") and "5M" in token


def _is_5a_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("5A") and "5M" in token


def _is_1c_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("1C") and "5M" in token


def _is_9a_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("9A") and "5M" in token


def _is_5b_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("5B") and "5M" in token


def _is_2b_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("2B") and "5M" in token


def _is_5c_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("5C") and "5M" in token


def _is_8a_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("8A") and "5M" in token


def _is_6a_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("6A") and "5M" in token


def _is_2c_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("2C") and "5M" in token


def _is_2d_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("2D") and "5M" in token


def _is_2a_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("2A") and "5M" in token


def _is_1d_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("1D") and "5M" in token


def _is_4a_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("4A") and "5M" in token


def _is_6b_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("6B") and "5M" in token


def _is_8b_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("8B") and "5M" in token


def _is_3a_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("3A") and "5M" in token


def _is_9b_5m(strategy: str, tf: str = "5m") -> bool:
    if room3_recipes.normalize_tf(tf) != "5m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("9B") and "5M" in token


def _is_1a_15m(strategy: str, tf: str = "15m") -> bool:
    if room3_recipes.normalize_tf(tf) != "15m":
        return False
    token = str(strategy or "").strip().upper().replace(" ", "")
    return token.startswith("1A") and "15M" in token


def _is_15m_origin_letter(strategy: str, tf: str = "15m") -> str:
    if room3_recipes.normalize_tf(tf) != "15m":
        return ""
    token = str(strategy or "").strip().upper().replace(" ", "")
    for head in ("1B", "1C", "1D", "2A", "2B", "6A", "9A"):
        if token.startswith(head) and "15M" in token:
            return head
    return ""


def _5m_spec_letter(strategy: str, tf: str = "5m") -> str:
    if _is_1a_5m(strategy, tf):
        return "1A"
    if _is_1b_5m(strategy, tf):
        return "1B"
    if _is_5a_5m(strategy, tf):
        return "5A"
    if _is_1c_5m(strategy, tf):
        return "1C"
    if _is_9a_5m(strategy, tf):
        return "9A"
    if _is_5b_5m(strategy, tf):
        return "5B"
    if _is_2b_5m(strategy, tf):
        return "2B"
    if _is_5c_5m(strategy, tf):
        return "5C"
    if _is_8a_5m(strategy, tf):
        return "8A"
    if _is_6a_5m(strategy, tf):
        return "6A"
    if _is_2c_5m(strategy, tf):
        return "2C"
    if _is_2d_5m(strategy, tf):
        return "2D"
    if _is_2a_5m(strategy, tf):
        return "2A"
    if _is_1d_5m(strategy, tf):
        return "1D"
    if _is_4a_5m(strategy, tf):
        return "4A"
    if _is_6b_5m(strategy, tf):
        return "6B"
    if _is_8b_5m(strategy, tf):
        return "8B"
    if _is_3a_5m(strategy, tf):
        return "3A"
    if _is_9b_5m(strategy, tf):
        return "9B"
    return ""


def _5m_spec_bag_token(letter: str, ticker: str) -> str:
    return f"{letter}|{str(ticker or '').upper()}"


def _5m_spec_cool_until(session_state: Any, letter: str, ticker: str) -> datetime | None:
    if session_state is None or not letter:
        return None
    try:
        bag = session_state.get("room3_5m_spec_cool") or {}
    except Exception:
        return None
    raw = bag.get(_5m_spec_bag_token(letter, ticker))
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _5m_spec_mark_stop_cool(session_state: Any, letter: str, ticker: str) -> None:
    sec = {
        "1A": ONE_A_5M_COOL_SEC,
        "1B": ONE_B_5M_COOL_SEC,
        "5A": FIVE_A_5M_COOL_SEC,
        "1C": ONE_C_5M_COOL_SEC,
        "9A": NINE_A_5M_COOL_SEC,
        "5B": FIVE_B_5M_COOL_SEC,
        "2B": TWO_B_5M_COOL_SEC,
        "5C": FIVE_C_5M_COOL_SEC,
        "8A": EIGHT_A_5M_COOL_SEC,
        "6A": SIX_A_5M_COOL_SEC,
        "2C": TWO_C_5M_COOL_SEC,
        "2D": TWO_D_5M_COOL_SEC,
        "2A": TWO_A_5M_COOL_SEC,
        "1D": ONE_D_5M_COOL_SEC,
        "4A": FOUR_A_5M_COOL_SEC,
        "6B": SIX_B_5M_COOL_SEC,
        "8B": EIGHT_B_5M_COOL_SEC,
        "3A": THREE_A_5M_COOL_SEC,
        "9B": NINE_B_5M_COOL_SEC,
    }.get(letter, 15 * 60)
    until = _5b_now(session_state) + timedelta(seconds=sec)
    _5b_bag_set(
        session_state,
        "room3_5m_spec_cool",
        _5m_spec_bag_token(letter, ticker),
        until.isoformat(),
    )


def _5m_spec_used_today(session_state: Any, letter: str, ticker: str) -> bool:
    if session_state is None or not letter:
        return False
    try:
        bag = session_state.get("room3_5m_spec_used_day") or {}
    except Exception:
        return False
    return str(bag.get(_5m_spec_bag_token(letter, ticker)) or "") == _5b_day_key(
        session_state
    )


def _5m_spec_mark_used(session_state: Any, letter: str, ticker: str) -> None:
    _5b_bag_set(
        session_state,
        "room3_5m_spec_used_day",
        _5m_spec_bag_token(letter, ticker),
        _5b_day_key(session_state),
    )


def _15m_spec_bag_token(letter: str, ticker: str) -> str:
    return f"{letter}|{str(ticker or '').upper()}"


def _15m_spec_cool_until(session_state: Any, letter: str, ticker: str) -> datetime | None:
    if session_state is None or not letter:
        return None
    try:
        bag = session_state.get("room3_15m_spec_cool") or {}
    except Exception:
        return None
    raw = bag.get(_15m_spec_bag_token(letter, ticker))
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _15m_spec_mark_stop_cool(session_state: Any, letter: str, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=ONE_A_15M_COOL_SEC)
    _5b_bag_set(
        session_state,
        "room3_15m_spec_cool",
        _15m_spec_bag_token(letter, ticker),
        until.isoformat(),
    )


def _15m_spec_used_today(session_state: Any, letter: str, ticker: str) -> bool:
    if session_state is None or not letter:
        return False
    try:
        bag = session_state.get("room3_15m_spec_used_day") or {}
    except Exception:
        return False
    return str(bag.get(_15m_spec_bag_token(letter, ticker)) or "") == _5b_day_key(
        session_state
    )


def _15m_spec_mark_used(session_state: Any, letter: str, ticker: str) -> None:
    _5b_bag_set(
        session_state,
        "room3_15m_spec_used_day",
        _15m_spec_bag_token(letter, ticker),
        _5b_day_key(session_state),
    )


def _5b_now(session_state: Any = None) -> datetime:
    try:
        if session_state is not None:
            forced = session_state.get("_now_et")
            if isinstance(forced, datetime):
                return forced
    except Exception:
        pass
    return datetime.now(room3_engine.ET)


def _rth_before(session_state: Any, until: dtime) -> bool:
    now = _5b_now(session_state)
    try:
        if room3_engine.detect_session_window(now) != room3_engine.SESSION_RTH:
            return False
    except Exception:
        if now.time() < dtime(9, 30) or now.time() >= dtime(16, 0):
            return False
    return now.time() < until


def _5b_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, FIVE_B_SKIP_UNTIL)


def _2a_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, TWO_A_SKIP_UNTIL)


def _2b_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, TWO_B_SKIP_UNTIL)


def _2c_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, TWO_C_SKIP_UNTIL)


def _3a_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, THREE_A_SKIP_UNTIL)


def _3a_past_noon(session_state: Any = None, *, hunting: bool = False) -> bool:
    """No new 3A arm after 12:00 ET. A dip already started may still reclaim."""
    if hunting:
        return False
    now = _5b_now(session_state)
    try:
        if room3_engine.detect_session_window(now) != room3_engine.SESSION_RTH:
            return True
    except Exception:
        if now.time() < dtime(9, 30) or now.time() >= dtime(16, 0):
            return True
    return now.time() >= THREE_A_UNTIL


def _ph_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, PH_SKIP_UNTIL)


def _2d_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, TWO_D_SKIP_UNTIL)


def _4a_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, FOUR_A_SKIP_UNTIL)


def _3b_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, THREE_B_SKIP_UNTIL)


def _5a_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, FIVE_A_SKIP_UNTIL)


def _7a_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, SEVEN_A_SKIP_UNTIL)


def _3c_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, THREE_C_SKIP_UNTIL)


def _4d_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, FOUR_D_SKIP_UNTIL)


def _4b_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, FOUR_B_SKIP_UNTIL)


def _6a_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, SIX_A_SKIP_UNTIL)


def _4c_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, FOUR_C_SKIP_UNTIL)


def _4e_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, FOUR_E_SKIP_UNTIL)


def _6b_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, SIX_B_SKIP_UNTIL)


def _3d_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, THREE_D_SKIP_UNTIL)


def _7b_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, SEVEN_B_SKIP_UNTIL)


def _3g_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, THREE_G_SKIP_UNTIL)


def _3f_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, THREE_F_SKIP_UNTIL)


def _8a_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, EIGHT_A_SKIP_UNTIL)


def _7c_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, SEVEN_C_SKIP_UNTIL)


def _3e_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, THREE_E_SKIP_UNTIL)


def _6c_open_chop(session_state: Any = None) -> bool:
    return _rth_before(session_state, SIX_C_SKIP_UNTIL)


def _5b_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_5b_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _5b_bag_set(session_state: Any, key: str, ticker: str, value: str) -> None:
    if session_state is None:
        return
    token = str(ticker or "").upper()
    if not token:
        return
    try:
        bag = dict(session_state.get(key) or {})
        bag[token] = value
        setattr(session_state, key, bag)
    except Exception:
        try:
            session_state[key] = {**(session_state.get(key) or {}), token: value}
        except Exception:
            pass


def _5b_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=FIVE_B_COOL_SEC)
    _5b_bag_set(session_state, "room3_5b_cool_until", ticker, until.isoformat())


def _pack_mark_stop_cool(session_state: Any, ticker: str, lot: dict[str, Any]) -> None:
    strat = str(lot.get("strategy") or lot.get("letter") or "")
    tf = str(lot.get("tf") or lot.get("timeframe") or "1m")
    style = str(lot.get("exit_style") or "")
    if _is_2a_1m(strat, tf) or style == TWO_A_EXIT_STYLE:
        _2a_mark_stop_cool(session_state, ticker)
        return
    if _is_2b_1m(strat, tf) or style == TWO_B_EXIT_STYLE:
        _2b_mark_stop_cool(session_state, ticker)
        return
    if _is_2c_1m(strat, tf) or style == TWO_C_EXIT_STYLE:
        _2c_mark_stop_cool(session_state, ticker)
        return
    if _is_3a_1m(strat, tf) or style == THREE_A_EXIT_STYLE:
        _3a_mark_stop_cool(session_state, ticker)
        return
    if _is_2d_1m(strat, tf) or style == TWO_D_EXIT_STYLE:
        _2d_mark_stop_cool(session_state, ticker)
        return
    if _is_4a_1m(strat, tf) or style == FOUR_A_EXIT_STYLE:
        _4a_mark_stop_cool(session_state, ticker)
        return
    if _is_3b_1m(strat, tf) or style == THREE_B_EXIT_STYLE:
        _3b_mark_stop_cool(session_state, ticker)
        return
    if _is_5a_1m(strat, tf) or style == FIVE_A_EXIT_STYLE:
        _5a_mark_stop_cool(session_state, ticker)
        return
    if _is_7a_1m(strat, tf) or style == SEVEN_A_EXIT_STYLE:
        _7a_mark_stop_cool(session_state, ticker)
        return
    if _is_3c_1m(strat, tf) or style == THREE_C_EXIT_STYLE:
        _3c_mark_stop_cool(session_state, ticker)
        return
    if _is_4d_1m(strat, tf) or style == FOUR_D_EXIT_STYLE:
        _4d_mark_stop_cool(session_state, ticker)
        return
    if _is_4b_1m(strat, tf) or style == FOUR_B_EXIT_STYLE:
        _4b_mark_stop_cool(session_state, ticker)
        return
    if _is_6a_1m(strat, tf) or style == SIX_A_EXIT_STYLE:
        _6a_mark_stop_cool(session_state, ticker)
        return
    if _is_4c_1m(strat, tf) or style == FOUR_C_EXIT_STYLE:
        _4c_mark_stop_cool(session_state, ticker)
        return
    if _is_4e_1m(strat, tf) or style == FOUR_E_EXIT_STYLE:
        _4e_mark_stop_cool(session_state, ticker)
        return
    if _is_6b_1m(strat, tf) or style == SIX_B_EXIT_STYLE:
        _6b_mark_stop_cool(session_state, ticker)
        return
    if _is_3d_1m(strat, tf) or style == THREE_D_EXIT_STYLE:
        _3d_mark_stop_cool(session_state, ticker)
        return
    if _is_7b_1m(strat, tf) or style == SEVEN_B_EXIT_STYLE:
        _7b_mark_stop_cool(session_state, ticker)
        return
    if _is_3g_1m(strat, tf) or style == THREE_G_EXIT_STYLE:
        _3g_mark_stop_cool(session_state, ticker)
        return
    if _is_3f_1m(strat, tf) or style == THREE_F_EXIT_STYLE:
        _3f_mark_stop_cool(session_state, ticker)
        return
    if _is_8a_1m(strat, tf) or style == EIGHT_A_EXIT_STYLE:
        _8a_mark_stop_cool(session_state, ticker)
        return
    if _is_7c_1m(strat, tf) or style == SEVEN_C_EXIT_STYLE:
        _7c_mark_stop_cool(session_state, ticker)
        return
    if _is_3e_1m(strat, tf) or style == THREE_E_EXIT_STYLE:
        _3e_mark_stop_cool(session_state, ticker)
        return
    if _is_6c_1m(strat, tf) or style == SIX_C_EXIT_STYLE:
        _6c_mark_stop_cool(session_state, ticker)
        return
    letter_5m = _5m_spec_letter(strat, tf)
    if letter_5m or style in (
        ONE_A_5M_EXIT_STYLE,
        ONE_B_5M_EXIT_STYLE,
        FIVE_A_5M_EXIT_STYLE,
        ONE_C_5M_EXIT_STYLE,
        NINE_A_5M_EXIT_STYLE,
        FIVE_B_5M_EXIT_STYLE,
        TWO_B_5M_EXIT_STYLE,
        FIVE_C_5M_EXIT_STYLE,
        EIGHT_A_5M_EXIT_STYLE,
        SIX_A_5M_EXIT_STYLE,
        TWO_C_5M_EXIT_STYLE,
        TWO_D_5M_EXIT_STYLE,
        TWO_A_5M_EXIT_STYLE,
        ONE_D_5M_EXIT_STYLE,
        FOUR_A_5M_EXIT_STYLE,
        SIX_B_5M_EXIT_STYLE,
        EIGHT_B_5M_EXIT_STYLE,
        THREE_A_5M_EXIT_STYLE,
        NINE_B_5M_EXIT_STYLE,
        ONE_A_15M_EXIT_STYLE,
        ONE_B_15M_EXIT_STYLE,
        ONE_C_15M_EXIT_STYLE,
        ONE_D_15M_EXIT_STYLE,
        TWO_A_15M_EXIT_STYLE,
        TWO_B_15M_EXIT_STYLE,
        SIX_A_15M_EXIT_STYLE,
        NINE_A_15M_EXIT_STYLE,
    ):
        if not letter_5m:
            letter_5m = {
                ONE_A_5M_EXIT_STYLE: "1A",
                ONE_B_5M_EXIT_STYLE: "1B",
                FIVE_A_5M_EXIT_STYLE: "5A",
                ONE_C_5M_EXIT_STYLE: "1C",
                NINE_A_5M_EXIT_STYLE: "9A",
                FIVE_B_5M_EXIT_STYLE: "5B",
                TWO_B_5M_EXIT_STYLE: "2B",
                FIVE_C_5M_EXIT_STYLE: "5C",
                EIGHT_A_5M_EXIT_STYLE: "8A",
                SIX_A_5M_EXIT_STYLE: "6A",
                TWO_C_5M_EXIT_STYLE: "2C",
                TWO_D_5M_EXIT_STYLE: "2D",
                TWO_A_5M_EXIT_STYLE: "2A",
                ONE_D_5M_EXIT_STYLE: "1D",
                FOUR_A_5M_EXIT_STYLE: "4A",
                SIX_B_5M_EXIT_STYLE: "6B",
                EIGHT_B_5M_EXIT_STYLE: "8B",
                THREE_A_5M_EXIT_STYLE: "3A",
                NINE_B_5M_EXIT_STYLE: "9B",
            }.get(style, "")
        if letter_5m:
            _5m_spec_mark_stop_cool(session_state, letter_5m, ticker)
            return
        letter_15m = {
            ONE_A_15M_EXIT_STYLE: "1A",
            ONE_B_15M_EXIT_STYLE: "1B",
            ONE_C_15M_EXIT_STYLE: "1C",
            ONE_D_15M_EXIT_STYLE: "1D",
            TWO_A_15M_EXIT_STYLE: "2A",
            TWO_B_15M_EXIT_STYLE: "2B",
            SIX_A_15M_EXIT_STYLE: "6A",
            NINE_A_15M_EXIT_STYLE: "9A",
        }.get(style, "")
        if letter_15m:
            _15m_spec_mark_stop_cool(session_state, letter_15m, ticker)
            return
        return
    if _is_1a_1m(strat, tf) or style in ONE_A_EXIT_STYLES:
        _1a_mark_stop_cool(session_state, ticker)
        return
    if _is_5b_1m(strat, tf) or style in (FIVE_B_EXIT_STYLE, FIVE_B_EXIT_STYLE_LEGACY):
        _5b_mark_stop_cool(session_state, ticker)
        return
    if style in (PH_EXIT_STYLE, PH_5M_EXIT_STYLE):
        _ph_mark_stop_cool(session_state, ticker, strat)


def _5b_day_key(session_state: Any = None) -> str:
    return _5b_now(session_state).strftime("%Y-%m-%d")


def _5b_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_5b_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _5b_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_5b_used_day", ticker, _5b_day_key(session_state))


def _2a_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_2a_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _2a_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=TWO_A_COOL_SEC)
    _5b_bag_set(session_state, "room3_2a_cool_until", ticker, until.isoformat())


def _2a_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_2a_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _2a_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_2a_used_day", ticker, _5b_day_key(session_state))


def _2b_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_2b_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _2b_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=TWO_B_COOL_SEC)
    _5b_bag_set(session_state, "room3_2b_cool_until", ticker, until.isoformat())


def _2b_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_2b_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _2b_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_2b_used_day", ticker, _5b_day_key(session_state))


def _2c_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_2c_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _2c_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=TWO_C_COOL_SEC)
    _5b_bag_set(session_state, "room3_2c_cool_until", ticker, until.isoformat())


def _2c_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_2c_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _2c_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_2c_used_day", ticker, _5b_day_key(session_state))


def _3a_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_3a_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _3a_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=THREE_A_COOL_SEC)
    _5b_bag_set(session_state, "room3_3a_cool_until", ticker, until.isoformat())


def _3a_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_3a_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _3a_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_3a_used_day", ticker, _5b_day_key(session_state))


def _4a_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_4a_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _4a_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=FOUR_A_COOL_SEC)
    _5b_bag_set(session_state, "room3_4a_cool_until", ticker, until.isoformat())


def _4a_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_4a_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _4a_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_4a_used_day", ticker, _5b_day_key(session_state))


def _3b_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_3b_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _3b_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=THREE_B_COOL_SEC)
    _5b_bag_set(session_state, "room3_3b_cool_until", ticker, until.isoformat())


def _3b_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_3b_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _3b_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_3b_used_day", ticker, _5b_day_key(session_state))


def _5a_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_5a_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _5a_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=FIVE_A_COOL_SEC)
    _5b_bag_set(session_state, "room3_5a_cool_until", ticker, until.isoformat())


def _5a_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_5a_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _5a_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_5a_used_day", ticker, _5b_day_key(session_state))


def _7a_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_7a_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _7a_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=SEVEN_A_COOL_SEC)
    _5b_bag_set(session_state, "room3_7a_cool_until", ticker, until.isoformat())


def _7a_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_7a_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _7a_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_7a_used_day", ticker, _5b_day_key(session_state))


def _3c_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_3c_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _3c_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=THREE_C_COOL_SEC)
    _5b_bag_set(session_state, "room3_3c_cool_until", ticker, until.isoformat())


def _3c_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_3c_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _3c_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_3c_used_day", ticker, _5b_day_key(session_state))


def _4d_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_4d_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _4d_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=FOUR_D_COOL_SEC)
    _5b_bag_set(session_state, "room3_4d_cool_until", ticker, until.isoformat())


def _4d_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_4d_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _4d_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_4d_used_day", ticker, _5b_day_key(session_state))


def _4b_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_4b_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _4b_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=FOUR_B_COOL_SEC)
    _5b_bag_set(session_state, "room3_4b_cool_until", ticker, until.isoformat())


def _4b_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_4b_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _4b_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_4b_used_day", ticker, _5b_day_key(session_state))


def _6a_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_6a_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _6a_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=SIX_A_COOL_SEC)
    _5b_bag_set(session_state, "room3_6a_cool_until", ticker, until.isoformat())


def _6a_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_6a_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _6a_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_6a_used_day", ticker, _5b_day_key(session_state))


def _4c_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_4c_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _4c_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=FOUR_C_COOL_SEC)
    _5b_bag_set(session_state, "room3_4c_cool_until", ticker, until.isoformat())


def _4c_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_4c_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _4c_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_4c_used_day", ticker, _5b_day_key(session_state))


def _4e_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_4e_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _4e_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=FOUR_E_COOL_SEC)
    _5b_bag_set(session_state, "room3_4e_cool_until", ticker, until.isoformat())


def _4e_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_4e_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _4e_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_4e_used_day", ticker, _5b_day_key(session_state))


def _6b_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_6b_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _6b_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=SIX_B_COOL_SEC)
    _5b_bag_set(session_state, "room3_6b_cool_until", ticker, until.isoformat())


def _6b_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_6b_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _6b_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_6b_used_day", ticker, _5b_day_key(session_state))


def _3d_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_3d_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _3d_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=THREE_D_COOL_SEC)
    _5b_bag_set(session_state, "room3_3d_cool_until", ticker, until.isoformat())


def _3d_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_3d_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _3d_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_3d_used_day", ticker, _5b_day_key(session_state))


def _7b_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_7b_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _7b_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=SEVEN_B_COOL_SEC)
    _5b_bag_set(session_state, "room3_7b_cool_until", ticker, until.isoformat())


def _7b_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_7b_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _7b_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_7b_used_day", ticker, _5b_day_key(session_state))


def _3g_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_3g_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _3g_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=THREE_G_COOL_SEC)
    _5b_bag_set(session_state, "room3_3g_cool_until", ticker, until.isoformat())


def _3g_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_3g_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _3g_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_3g_used_day", ticker, _5b_day_key(session_state))


def _3f_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_3f_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _3f_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=THREE_F_COOL_SEC)
    _5b_bag_set(session_state, "room3_3f_cool_until", ticker, until.isoformat())


def _3f_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_3f_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _3f_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_3f_used_day", ticker, _5b_day_key(session_state))


def _8a_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_8a_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _8a_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=EIGHT_A_COOL_SEC)
    _5b_bag_set(session_state, "room3_8a_cool_until", ticker, until.isoformat())


def _8a_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_8a_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _8a_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_8a_used_day", ticker, _5b_day_key(session_state))


def _7c_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_7c_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _7c_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=SEVEN_C_COOL_SEC)
    _5b_bag_set(session_state, "room3_7c_cool_until", ticker, until.isoformat())


def _7c_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_7c_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _7c_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_7c_used_day", ticker, _5b_day_key(session_state))


def _3e_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_3e_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _3e_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=THREE_E_COOL_SEC)
    _5b_bag_set(session_state, "room3_3e_cool_until", ticker, until.isoformat())


def _3e_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_3e_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _3e_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_3e_used_day", ticker, _5b_day_key(session_state))


def _6c_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_6c_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _6c_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=SIX_C_COOL_SEC)
    _5b_bag_set(session_state, "room3_6c_cool_until", ticker, until.isoformat())


def _6c_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_6c_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _6c_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_6c_used_day", ticker, _5b_day_key(session_state))


def _1a_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_1a_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _1a_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=ONE_A_COOL_SEC)
    _5b_bag_set(session_state, "room3_1a_cool_until", ticker, until.isoformat())


def _1a_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_1a_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _1a_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_1a_used_day", ticker, _5b_day_key(session_state))


def _2d_cool_until(session_state: Any, ticker: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_2d_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(str(ticker or "").upper())
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _2d_mark_stop_cool(session_state: Any, ticker: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=TWO_D_COOL_SEC)
    _5b_bag_set(session_state, "room3_2d_cool_until", ticker, until.isoformat())


def _2d_used_today(session_state: Any, ticker: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_2d_used_day") or {}
    except Exception:
        return False
    return str(bag.get(str(ticker or "").upper()) or "") == _5b_day_key(session_state)


def _2d_mark_used(session_state: Any, ticker: str) -> None:
    _5b_bag_set(session_state, "room3_2d_used_day", ticker, _5b_day_key(session_state))


def _2d_shots_today(session_state: Any, ticker: str) -> int:
    if session_state is None:
        return 0
    try:
        bag = session_state.get("room3_2d_shots_day") or {}
    except Exception:
        return 0
    raw = str(bag.get(str(ticker or "").upper()) or "")
    day = _5b_day_key(session_state)
    if raw.startswith(f"{day}:"):
        try:
            return max(0, int(raw.split(":", 1)[1]))
        except (TypeError, ValueError):
            return 0
    if raw == day:
        return 1
    return 0


def _2d_mark_shot(session_state: Any, ticker: str) -> None:
    n = _2d_shots_today(session_state, ticker) + 1
    _5b_bag_set(
        session_state,
        "room3_2d_shots_day",
        ticker,
        f"{_5b_day_key(session_state)}:{n}",
    )
    if n >= 2:
        _2d_mark_used(session_state, ticker)


def _1m_name_shots_today(session_state: Any, ticker: str) -> int:
    if session_state is None:
        return 0
    try:
        bag = session_state.get("room3_1m_name_shots_day") or {}
    except Exception:
        return 0
    raw = str(bag.get(str(ticker or "").upper()) or "")
    day = _5b_day_key(session_state)
    if raw.startswith(f"{day}:"):
        try:
            return max(0, int(raw.split(":", 1)[1]))
        except (TypeError, ValueError):
            return 0
    return 0


def _1m_name_shots_blocked(session_state: Any, ticker: str) -> bool:
    return _1m_name_shots_today(session_state, ticker) >= ONE_M_NAME_SHOT_MAX


def _1m_mark_name_shot(session_state: Any, ticker: str) -> None:
    n = _1m_name_shots_today(session_state, ticker) + 1
    _5b_bag_set(
        session_state,
        "room3_1m_name_shots_day",
        ticker,
        f"{_5b_day_key(session_state)}:{n}",
    )


def _ph_token(ticker: str, strategy: str) -> str:
    return f"{str(ticker or '').upper()}|{str(strategy or '').strip()}".upper()


def _ph_used_today(session_state: Any, ticker: str, strategy: str) -> bool:
    if session_state is None:
        return False
    try:
        bag = session_state.get("room3_ph_used_day") or {}
    except Exception:
        return False
    return str(bag.get(_ph_token(ticker, strategy)) or "") == _5b_day_key(session_state)


def _ph_mark_used(session_state: Any, ticker: str, strategy: str) -> None:
    _5b_bag_set(
        session_state,
        "room3_ph_used_day",
        _ph_token(ticker, strategy),
        _5b_day_key(session_state),
    )


def _ph_cool_until(session_state: Any, ticker: str, strategy: str) -> datetime | None:
    if session_state is None:
        return None
    try:
        bag = session_state.get("room3_ph_cool_until") or {}
    except Exception:
        return None
    raw = bag.get(_ph_token(ticker, strategy))
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=room3_engine.ET)
    return ts


def _ph_mark_stop_cool(session_state: Any, ticker: str, strategy: str) -> None:
    until = _5b_now(session_state) + timedelta(seconds=PH_COOL_SEC)
    _5b_bag_set(
        session_state,
        "room3_ph_cool_until",
        _ph_token(ticker, strategy),
        until.isoformat(),
    )


def _window_velocity_pct(slices: list[dict[str, Any]], bars: int = 0) -> float:
    win = slices[-bars:] if bars and bars > 0 else slices
    closes = [float(s.get("c") or 0) for s in win if float(s.get("c") or 0) > 0]
    if len(closes) < 3:
        return 0.0
    total = 0.0
    prev = closes[0]
    for c in closes[1:]:
        if prev > 0:
            total += (c - prev) / prev
        prev = c
    return total * 100.0


def _2a_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Live tape must look like 2A packs: still-up window, fat green bar, RVOL."""
    if len(slices) < 2:
        return False
    if _window_velocity_pct(slices) < TWO_A_VEL_PCT:
        return False
    last = slices[-1]
    if _bar_range_pct(last) < TWO_A_BAR_RANGE_PCT:
        return False
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_c <= last_o:
        return False
    if _5b_tape_rvol(slices) < TWO_A_RVOL_MIN:
        return False
    return True


def _2b_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """9-bar window still up ≥10%, last bar range ≥2%. No RVOL/green — that is 2A."""
    if len(slices) < 3:
        return False
    if _window_velocity_pct(slices, 9) < TWO_B_VEL9_PCT:
        return False
    last = slices[-1]
    if _bar_range_pct(last) < TWO_B_BAR_RANGE_PCT:
        return False
    return True


def _2c_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Slower than 2B: 5-bar ≥4%, 9-bar ≥4%, last bar range ≥3%. No RVOL."""
    if len(slices) < 3:
        return False
    if _window_velocity_pct(slices, 5) < TWO_C_VEL5_PCT:
        return False
    if _window_velocity_pct(slices, 9) < TWO_C_VEL9_PCT:
        return False
    last = slices[-1]
    if _bar_range_pct(last) < TWO_C_BAR_RANGE_PCT:
        return False
    return True


def _3a_session_vwap(slices: list[dict[str, Any]]) -> float:
    num = 0.0
    den = 0.0
    for s in slices or []:
        h = float(s.get("h") or 0)
        lo = float(s.get("l") or 0)
        c = float(s.get("c") or 0)
        v = float(s.get("v") or 0)
        tp = (h + lo + c) / 3.0 if h > 0 and lo > 0 and c > 0 else c
        if tp > 0 and v > 0:
            num += tp * v
            den += v
    return (num / den) if den > 0 else 0.0


def _3a_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Under VWAP, RVOL ≥1.5, last bar range ≥1.5%. Wallpaper 3A does not fire."""
    if len(slices) < 2:
        return False
    last = slices[-1]
    if _bar_range_pct(last) < THREE_A_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < THREE_A_RVOL_MIN:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px <= 0 or px >= vwap:
        return False
    return True


def _4a_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Middle 5-bar 3–8%, last bar ≥2%, RVOL <1.5. Not 2A/1A wallpaper."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    if _bar_range_pct(last) < FOUR_A_BAR_RANGE_PCT:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < FOUR_A_VEL5_MIN or vel5 > FOUR_A_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) >= FOUR_A_RVOL_MAX:
        return False
    if _2a_gene_ok(slices):
        return False
    if _1a_classify(slices):
        return False
    return True


def _3b_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Under VWAP, last bar ≥2%, RVOL <1.5. Complement of 3A — wallpaper 3B does not fire."""
    if len(slices) < 2:
        return False
    last = slices[-1]
    if _bar_range_pct(last) < THREE_B_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) >= THREE_B_RVOL_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px <= 0 or px >= vwap:
        return False
    return True


def _5a_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """5-bar and 9-bar still down ≥4%, last bar green ≥2%. Not 5B climax."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < FIVE_A_BAR_RANGE_PCT:
        return False
    if _window_velocity_pct(slices, 5) > FIVE_A_VEL5_PCT:
        return False
    if _window_velocity_pct(slices, 9) > FIVE_A_VEL9_PCT:
        return False
    if _5b_climax_ok(slices) and _5b_tape_rvol(slices) >= FIVE_B_RVOL_MIN:
        return False
    return True


def _7a_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Quiet green, last bar ≥3% with strong close and ≥1.5% body, vel5 −1..3%, RVOL <1.5. Not 2A/4A wallpaper."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < SEVEN_A_BAR_RANGE_PCT:
        return False
    if _bar_close_loc(last) < SEVEN_A_CLOSE_LOC_MIN:
        return False
    if _bar_body_pct(last) < SEVEN_A_BODY_PCT_MIN:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < SEVEN_A_VEL5_MIN or vel5 >= SEVEN_A_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) >= SEVEN_A_RVOL_MAX:
        return False
    if _2a_gene_ok(slices) or _2b_gene_ok(slices) or _2c_gene_ok(slices):
        return False
    if _1a_classify(slices) or _4a_gene_ok(slices):
        return False
    return True


def _3c_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Above VWAP, last bar ≥4%, RVOL <1.5. Not 3A/3B. Last-green not required."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    if _bar_range_pct(last) < THREE_C_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) >= THREE_C_RVOL_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px <= 0 or px <= vwap:
        return False
    if _3a_gene_ok(slices) or _3b_gene_ok(slices):
        return False
    return True


def _4d_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """5-bar 3–10%, last bar green ≥5%, RVOL ≥1.5, session still up. Not 2A/1A/4A."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < FOUR_D_BAR_RANGE_PCT:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < FOUR_D_VEL5_MIN or vel5 > FOUR_D_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) < FOUR_D_RVOL_MIN:
        return False
    if _session_up_pct(slices) < FOUR_D_SESS_UP_MIN:
        return False
    if _2a_gene_ok(slices) or _1a_classify(slices) or _4a_gene_ok(slices):
        return False
    return True


def _4b_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Vel5 4–9%, last green ≥3%, RVOL ≥1.5, session up ≥8%. Not 2A/1A/4A/4D."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < FOUR_B_BAR_RANGE_PCT:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < FOUR_B_VEL5_MIN or vel5 > FOUR_B_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) < FOUR_B_RVOL_MIN:
        return False
    if _session_up_pct(slices) < FOUR_B_SESS_UP_MIN:
        return False
    if _2a_gene_ok(slices) or _1a_classify(slices) or _4a_gene_ok(slices) or _4d_gene_ok(slices):
        return False
    return True


def _6a_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Vel5 ≤−3%, vel9 ≤−2%, last green ≥2.5%, under VWAP. Not 5A / 5B climax."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < SIX_A_BAR_RANGE_PCT:
        return False
    if _window_velocity_pct(slices, 5) > SIX_A_VEL5_MAX:
        return False
    if _window_velocity_pct(slices, 9) > SIX_A_VEL9_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px >= vwap:
        return False
    if _5a_gene_ok(slices):
        return False
    if _5b_climax_ok(slices) and _5b_tape_rvol(slices) >= FIVE_B_RVOL_MIN:
        return False
    return True


def _4c_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Vel5 0.5–<3%, last green ≥3%, close loc ≥0.40, RVOL <1.5. Not 4A/7A/2A/1A."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < FOUR_C_BAR_RANGE_PCT:
        return False
    if _bar_close_loc(last) < FOUR_C_CLOSE_LOC_MIN:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < FOUR_C_VEL5_MIN or vel5 >= FOUR_C_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) >= FOUR_C_RVOL_MAX:
        return False
    if _4a_gene_ok(slices) or _7a_gene_ok(slices):
        return False
    if _2a_gene_ok(slices) or _1a_classify(slices):
        return False
    return True


def _4e_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Vel5 9–12%, last green ≥4%, RVOL <1.5, session still up. Not 4A/4B/4D."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < FOUR_E_BAR_RANGE_PCT:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < FOUR_E_VEL5_MIN or vel5 > FOUR_E_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) >= FOUR_E_RVOL_MAX:
        return False
    if _session_up_pct(slices) < FOUR_E_SESS_UP_MIN:
        return False
    return True


def _6b_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Vel5 ≤−2.5%, vel9 ≤0, last green ≥2%, under VWAP. Not 6A / 5A / 5B."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < SIX_B_BAR_RANGE_PCT:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    vel9 = _window_velocity_pct(slices, 9)
    if vel5 > SIX_B_VEL5_MAX:
        return False
    if vel9 > SIX_B_VEL9_MAX:
        return False
    if vel5 <= SIX_A_VEL5_MAX and vel9 <= SIX_A_VEL9_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px >= vwap:
        return False
    if _5a_gene_ok(slices):
        return False
    if _5b_climax_ok(slices) and _5b_tape_rvol(slices) >= FIVE_B_RVOL_MIN:
        return False
    return True


def _3d_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Above VWAP, last green 3.5–<4%, close loc ≥0.55, RVOL <1.5. Not 3C."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    rng = _bar_range_pct(last)
    if rng < THREE_D_BAR_RANGE_MIN or rng >= THREE_D_BAR_RANGE_MAX:
        return False
    if _bar_close_loc(last) < THREE_D_CLOSE_LOC_MIN:
        return False
    if _5b_tape_rvol(slices) >= THREE_D_RVOL_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px <= vwap:
        return False
    return True


def _7b_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Last green 2.5–<3%, loc ≥0.55, body ≥1.5%, vel5 0–<3%, RVOL <1.5. Not 7A."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    rng = _bar_range_pct(last)
    if rng < SEVEN_B_BAR_RANGE_MIN or rng >= SEVEN_B_BAR_RANGE_MAX:
        return False
    if _bar_close_loc(last) < SEVEN_B_CLOSE_LOC_MIN:
        return False
    if _bar_body_pct(last) < SEVEN_B_BODY_PCT_MIN:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < SEVEN_B_VEL5_MIN or vel5 >= SEVEN_B_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) >= SEVEN_B_RVOL_MAX:
        return False
    return True


def _3g_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Above VWAP, last bar ≥4%, RVOL ≥1.5, session up ≥8%. Not 3C / 4B / 4D / 2A / 1A."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    if _bar_range_pct(last) < THREE_G_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < THREE_G_RVOL_MIN:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px <= vwap:
        return False
    if _session_up_pct(slices) < THREE_G_SESS_UP_MIN:
        return False
    if _2a_gene_ok(slices) or _1a_classify(slices) or _4b_gene_ok(slices) or _4d_gene_ok(slices):
        return False
    return True


def _3f_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Above VWAP, last green 2–<3.5%, RVOL <1.5, session up ≥8%. Not 3C / 3D."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    rng = _bar_range_pct(last)
    if rng < THREE_F_BAR_RANGE_MIN or rng >= THREE_F_BAR_RANGE_MAX:
        return False
    if _5b_tape_rvol(slices) >= THREE_F_RVOL_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px <= vwap:
        return False
    if _session_up_pct(slices) < THREE_F_SESS_UP_MIN:
        return False
    return True


def _8a_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Last green ≥2%, loc ≥0.60, vel5 −2–<2%, RVOL ≥1.5, session up ≥5%. Not 1A/2*/4*/3*/5A/5B/6A/6B/7A/7B."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < EIGHT_A_BAR_RANGE_PCT:
        return False
    if _bar_close_loc(last) < EIGHT_A_CLOSE_LOC_MIN:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < EIGHT_A_VEL5_MIN or vel5 >= EIGHT_A_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) < EIGHT_A_RVOL_MIN:
        return False
    if _session_up_pct(slices) < EIGHT_A_SESS_UP_MIN:
        return False
    if (
        _1a_classify(slices)
        or _2a_gene_ok(slices)
        or _2b_gene_ok(slices)
        or _2c_gene_ok(slices)
        or _2d_gene_ok(slices)
        or _3a_gene_ok(slices)
        or _3b_gene_ok(slices)
        or _3c_gene_ok(slices)
        or _3d_gene_ok(slices)
        or _3f_gene_ok(slices)
        or _3g_gene_ok(slices)
        or _4a_gene_ok(slices)
        or _4b_gene_ok(slices)
        or _4c_gene_ok(slices)
        or _4d_gene_ok(slices)
        or _4e_gene_ok(slices)
        or _5a_gene_ok(slices)
        or _6a_gene_ok(slices)
        or _6b_gene_ok(slices)
        or _7a_gene_ok(slices)
        or _7b_gene_ok(slices)
    ):
        return False
    if _5b_climax_ok(slices) and _5b_tape_rvol(slices) >= FIVE_B_RVOL_MIN:
        return False
    return True


def _7c_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Last green 2–<2.5%, loc ≥0.70, vel5 −1–<2%, RVOL <1.5. Not 7A / 7B."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    rng = _bar_range_pct(last)
    if rng < SEVEN_C_BAR_RANGE_MIN or rng >= SEVEN_C_BAR_RANGE_MAX:
        return False
    if _bar_close_loc(last) < SEVEN_C_CLOSE_LOC_MIN:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < SEVEN_C_VEL5_MIN or vel5 >= SEVEN_C_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) >= SEVEN_C_RVOL_MAX:
        return False
    return True


def _3e_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Above VWAP, last 2–<3.5%, loc ≥0.50, RVOL <1.5, session up ≥0. Not 3F / 4A."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    rng = _bar_range_pct(last)
    if rng < THREE_E_BAR_RANGE_MIN or rng >= THREE_E_BAR_RANGE_MAX:
        return False
    if _bar_close_loc(last) < THREE_E_CLOSE_LOC_MIN:
        return False
    if _5b_tape_rvol(slices) >= THREE_E_RVOL_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px <= vwap:
        return False
    if _session_up_pct(slices) < THREE_E_SESS_UP_MIN:
        return False
    if (
        _3a_gene_ok(slices)
        or _3b_gene_ok(slices)
        or _3c_gene_ok(slices)
        or _3d_gene_ok(slices)
        or _3f_gene_ok(slices)
        or _3g_gene_ok(slices)
        or _4a_gene_ok(slices)
        or _4b_gene_ok(slices)
        or _4c_gene_ok(slices)
        or _4d_gene_ok(slices)
        or _4e_gene_ok(slices)
        or _2a_gene_ok(slices)
        or _1a_classify(slices)
        or _7a_gene_ok(slices)
        or _7b_gene_ok(slices)
        or _7c_gene_ok(slices)
        or _8a_gene_ok(slices)
    ):
        return False
    return True


def _6c_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Vel5 −2 to −0.3%, last green ≥2%, under VWAP. Not 6A / 6B / 5A / 5B."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < SIX_C_BAR_RANGE_PCT:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 <= SIX_C_VEL5_MIN or vel5 > SIX_C_VEL5_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px >= vwap:
        return False
    if _6a_gene_ok(slices) or _6b_gene_ok(slices):
        return False
    if _5a_gene_ok(slices):
        return False
    if _5b_climax_ok(slices) and _5b_tape_rvol(slices) >= FIVE_B_RVOL_MIN:
        return False
    return True


def _1a_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Fat 5m rip: vel5 ≥10%, last green, last range ≥5%."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < ONE_A_5M_BAR_RANGE_PCT:
        return False
    if _window_velocity_pct(slices, 5) < ONE_A_5M_VEL5_MIN:
        return False
    return True


def _1b_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Medium 5m up, not 1A: vel5 5–<10, last green, last range ≥4%."""
    if len(slices) < 3:
        return False
    if _1a_5m_gene_ok(slices):
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < ONE_B_5M_BAR_RANGE_PCT:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < ONE_B_5M_VEL5_MIN or vel5 >= ONE_B_5M_VEL5_MAX:
        return False
    return True


def _5a_5m_dump_ok(slices: list[dict[str, Any]]) -> bool:
    """Under-VWAP dump bounce body. 5A is this minus 5B / 6A; 5B climax; 6A tighter vel."""
    if len(slices) < 3:
        return False
    if _1a_5m_gene_ok(slices) or _1b_5m_gene_ok(slices):
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < FIVE_A_5M_BAR_RANGE_PCT:
        return False
    if _window_velocity_pct(slices, 5) > FIVE_A_5M_VEL5_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px >= vwap:
        return False
    return True


def _5a_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """5m dump bounce: vel5 ≤−2, last green ≥2%, under VWAP. Not 1A / 1B / 5B / 6A."""
    if not _5a_5m_dump_ok(slices):
        return False
    if _5b_5m_gene_ok(slices):
        return False
    if _6a_5m_gene_ok(slices):
        return False
    return True


def _1c_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Quieter Layout 1 up: vel5 0–<5%, last green ≥3.5%, RVOL <1.5. Not 1A / 1B / 5A."""
    if len(slices) < 3:
        return False
    if _1a_5m_gene_ok(slices) or _1b_5m_gene_ok(slices) or _5a_5m_gene_ok(slices):
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < ONE_C_5M_BAR_RANGE_PCT:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < ONE_C_5M_VEL5_MIN or vel5 >= ONE_C_5M_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) >= ONE_C_5M_RVOL_MAX:
        return False
    return True


def _9a_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Dump bounce above VWAP: vel5 ≤−2, last green ≥2.5%, loc ≥0.50. Not 5A (under VWAP)."""
    if len(slices) < 3:
        return False
    if (
        _1a_5m_gene_ok(slices)
        or _1b_5m_gene_ok(slices)
        or _5a_5m_gene_ok(slices)
        or _1c_5m_gene_ok(slices)
    ):
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < NINE_A_5M_BAR_RANGE_PCT:
        return False
    if _bar_close_loc(last) < NINE_A_5M_LOC_MIN:
        return False
    if _window_velocity_pct(slices, 5) > NINE_A_5M_VEL5_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px <= vwap:
        return False
    return True


def _5b_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Dump climax: 5A dump plus last green ≥4% loc ≥0.50. Not leftover wallpaper."""
    if not _5a_5m_dump_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < FIVE_B_5M_BAR_RANGE_PCT:
        return False
    if _bar_close_loc(last) < FIVE_B_5M_LOC_MIN:
        return False
    return True


def _6a_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Tighter dump subset of 5A: vel5 ≤−3.5, last green ≥2%, loc ≥0.40, under VWAP. Not 5B climax."""
    if not _5a_5m_dump_ok(slices):
        return False
    if _5b_5m_gene_ok(slices):
        return False
    last = slices[-1]
    if _bar_close_loc(last) < SIX_A_5M_LOC_MIN:
        return False
    if _window_velocity_pct(slices, 5) > SIX_A_5M_VEL5_MAX:
        return False
    return True


def _5m_spec_siblings_ok(slices: list[dict[str, Any]]) -> bool:
    """True when a leftover-locked 5m letter already owns this tape."""
    return (
        _1a_5m_gene_ok(slices)
        or _1b_5m_gene_ok(slices)
        or _1c_5m_gene_ok(slices)
        or _5a_5m_gene_ok(slices)
        or _9a_5m_gene_ok(slices)
        or _5b_5m_gene_ok(slices)
        or _2b_5m_gene_ok(slices)
        or _5c_5m_gene_ok(slices)
        or _8a_5m_gene_ok(slices)
        or _6a_5m_gene_ok(slices)
    )


def _2c_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 2C (5M): last range ≥1.9%, RVOL ≥1.5. Last-green is not required. Not siblings."""
    if len(slices) < 3:
        return False
    if _5m_spec_siblings_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < TWO_C_5M_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < TWO_C_5M_RVOL_MIN:
        return False
    return True


def _2d_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 2D (5M): last range ≥0.9%, RVOL ≥1.5. Last-green is not required. Not 2C / siblings."""
    if len(slices) < 3:
        return False
    if _5m_spec_siblings_ok(slices) or _2c_5m_gene_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < TWO_D_5M_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < TWO_D_5M_RVOL_MIN:
        return False
    return True


def _2a_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 2A (5M): last range ≥2%, RVOL ≥1.5. Last-green is not required. Not leftover siblings."""
    if len(slices) < 3:
        return False
    if _5m_spec_siblings_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < TWO_A_5M_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < TWO_A_5M_RVOL_MIN:
        return False
    return True


def _1d_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 1D (5M): last range ≥1%, RVOL ≥1.5, vel5 under 3%. Last-green is not required. Not 2C / leftover siblings."""
    if len(slices) < 3:
        return False
    if _5m_spec_siblings_ok(slices) or _2c_5m_gene_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < ONE_D_5M_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < ONE_D_5M_RVOL_MIN:
        return False
    if _window_velocity_pct(slices, 5) >= ONE_D_5M_VEL5_MAX:
        return False
    return True


def _4a_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 4A (5M): vel5 3–<8, last range ≥1.5%, RVOL ≥1.5. Last-green is not required. Not leftover siblings."""
    if len(slices) < 3:
        return False
    if _5m_spec_siblings_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < FOUR_A_5M_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < FOUR_A_5M_RVOL_MIN:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < FOUR_A_5M_VEL5_MIN or vel5 >= FOUR_A_5M_VEL5_MAX:
        return False
    return True


def _6b_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 6B (5M): last range ≥2%, RVOL ≥1.5. Last-green is not required. Not leftover siblings."""
    if len(slices) < 3:
        return False
    if _5m_spec_siblings_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < SIX_B_5M_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < SIX_B_5M_RVOL_MIN:
        return False
    return True


def _8b_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 8B (5M): last range ≥2%, RVOL ≥1.5. Last-green is not required. Not leftover siblings."""
    if len(slices) < 3:
        return False
    if _5m_spec_siblings_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < EIGHT_B_5M_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < EIGHT_B_5M_RVOL_MIN:
        return False
    return True


def _3a_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 3A (5M): last range ≥2%, RVOL ≥1.5. Last-green is not required. Not leftover siblings."""
    if len(slices) < 3:
        return False
    if _5m_spec_siblings_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < THREE_A_5M_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < THREE_A_5M_RVOL_MIN:
        return False
    return True


def _9b_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 9B (5M): last range ≥4%. Last-green is not required. No RVOL gate. Not leftover siblings."""
    if len(slices) < 3:
        return False
    if _5m_spec_siblings_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < NINE_B_5M_BAR_RANGE_PCT:
        return False
    return True


def _1a_15m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Leftover 1A (15M): vel5 ≥12%, last range ≥2%. Last-green is not required."""
    if len(slices) < 3:
        return False
    last = slices[-1]
    if _bar_range_pct(last) < ONE_A_15M_BAR_RANGE_PCT:
        return False
    if _window_velocity_pct(slices, 5) < ONE_A_15M_VEL5_MIN:
        return False
    return True


def _15m_origin_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Origin 15m (not 1A / 8A / 8B): last range ≥3%. Last-green is not required."""
    if len(slices) < 3:
        return False
    if _1a_15m_gene_ok(slices):
        return False
    last = slices[-1]
    if _bar_range_pct(last) < FIFTEEN_M_ORIGIN_BAR_RANGE_PCT:
        return False
    return True


def _2b_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Leftover 9-bar up: vel9 ≥8%, last green ≥2.5%. Not 1A / 1B / 1C / 5A / 9A / 5B."""
    if len(slices) < 3:
        return False
    if (
        _1a_5m_gene_ok(slices)
        or _1b_5m_gene_ok(slices)
        or _1c_5m_gene_ok(slices)
        or _5a_5m_gene_ok(slices)
        or _9a_5m_gene_ok(slices)
        or _5b_5m_gene_ok(slices)
        or _6a_5m_gene_ok(slices)
    ):
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < TWO_B_5M_BAR_RANGE_PCT:
        return False
    if _window_velocity_pct(slices, 9) < TWO_B_5M_VEL9_PCT:
        return False
    return True


def _5c_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Milder dump than 5A: vel5 −1.5 to under −2, last green ≥2%, under VWAP."""
    if len(slices) < 3:
        return False
    if (
        _1a_5m_gene_ok(slices)
        or _1b_5m_gene_ok(slices)
        or _1c_5m_gene_ok(slices)
        or _5a_5m_gene_ok(slices)
        or _9a_5m_gene_ok(slices)
        or _5b_5m_gene_ok(slices)
        or _6a_5m_gene_ok(slices)
        or _2b_5m_gene_ok(slices)
    ):
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < FIVE_C_5M_BAR_RANGE_PCT:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 <= FIVE_C_5M_VEL5_MIN or vel5 > FIVE_C_5M_VEL5_MAX:
        return False
    vwap = _3a_session_vwap(slices)
    px = float(last.get("c") or 0)
    if vwap <= 0 or px >= vwap:
        return False
    return True


def _8a_5m_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Loud leftover flat-up: vel5 −2–<2, last green ≥2%, loc ≥0.50, RVOL ≥1.5, session ≥8%."""
    if len(slices) < 3:
        return False
    if (
        _1a_5m_gene_ok(slices)
        or _1b_5m_gene_ok(slices)
        or _1c_5m_gene_ok(slices)
        or _5a_5m_gene_ok(slices)
        or _9a_5m_gene_ok(slices)
        or _5b_5m_gene_ok(slices)
        or _2b_5m_gene_ok(slices)
        or _5c_5m_gene_ok(slices)
        or _6a_5m_gene_ok(slices)
    ):
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_o <= 0 or last_c <= last_o:
        return False
    if _bar_range_pct(last) < EIGHT_A_5M_BAR_RANGE_PCT:
        return False
    if _bar_close_loc(last) < EIGHT_A_5M_LOC_MIN:
        return False
    vel5 = _window_velocity_pct(slices, 5)
    if vel5 < EIGHT_A_5M_VEL5_MIN or vel5 >= EIGHT_A_5M_VEL5_MAX:
        return False
    if _5b_tape_rvol(slices) < EIGHT_A_5M_RVOL_MIN:
        return False
    if _session_up_pct(slices) < EIGHT_A_5M_SESS_PCT:
        return False
    return True


def _2d_gene_ok(slices: list[dict[str, Any]]) -> bool:
    """Hunt extra — not a new gene. Fat green bar + RVOL ≥3. Wallpaper 2D does not fire."""
    if len(slices) < 2:
        return False
    last = slices[-1]
    last_o = float(last.get("o") or 0)
    last_c = float(last.get("c") or 0)
    if last_c <= last_o:
        return False
    if _bar_range_pct(last) < TWO_D_BAR_RANGE_PCT:
        return False
    if _5b_tape_rvol(slices) < TWO_D_RVOL_MIN:
        return False
    return True


def _1a_last_green(slices: list[dict[str, Any]]) -> bool:
    if not slices:
        return False
    last = slices[-1]
    last_c = float(last.get("c") or 0)
    last_o = float(last.get("o") or last_c)
    return last_c > last_o


def _1a_classify(slices: list[dict[str, Any]]) -> str:
    """Pick one 1A Handle from already-printed tape. Empty = wallpaper, skip."""
    if len(slices) < 3:
        return ""
    if _5b_tape_rvol(slices) < ONE_A_RVOL_MIN:
        return ""
    last = slices[-1]
    rng = _bar_range_pct(last)
    vel20 = _window_velocity_pct(slices, 20)
    vel5 = _window_velocity_pct(slices, 5)
    green = _1a_last_green(slices)
    if vel20 >= ONE_A_TRIP_VEL20 and rng >= ONE_A_TRIP_RNG_PCT and green:
        return "trip"
    if vel20 >= ONE_A_VIOLENT_VEL20 and rng >= ONE_A_VIOLENT_RNG_PCT:
        return "violent"
    if (
        vel5 >= ONE_A_MILD_VEL5
        and rng >= ONE_A_MILD_RNG_PCT
        and green
        and vel20 < ONE_A_VIOLENT_VEL20
    ):
        return "mild"
    return ""


def _bar_range_pct(bar: dict[str, Any]) -> float:
    c = float(bar.get("c") or 0)
    h = float(bar.get("h") or 0)
    l = float(bar.get("l") or 0)
    if c <= 0:
        return 0.0
    return (h - l) / c * 100.0


def _bar_close_loc(bar: dict[str, Any]) -> float:
    """0 = close at the low, 1 = close at the high."""
    h = float(bar.get("h") or 0)
    l = float(bar.get("l") or 0)
    c = float(bar.get("c") or 0)
    span = h - l
    if span <= 0:
        return 0.5
    return (c - l) / span


def _bar_body_pct(bar: dict[str, Any]) -> float:
    o = float(bar.get("o") or 0)
    c = float(bar.get("c") or 0)
    if o <= 0:
        return 0.0
    return (c - o) / o * 100.0


def _session_up_pct(slices: list[dict[str, Any]]) -> float:
    """Last close vs first printed open. Walkforward day-open when slices start at the open."""
    if not slices:
        return 0.0
    o = float(slices[0].get("o") or 0)
    c = float(slices[-1].get("c") or 0)
    if o <= 0:
        return 0.0
    return (c - o) / o * 100.0


def _5b_tape_rvol(slices: list[dict[str, Any]]) -> float:
    """Window volume vs median bar volume (already-printed slices only)."""
    vols = [float(s.get("v") or 0) for s in slices if float(s.get("v") or 0) > 0]
    if not vols:
        return 0.0
    ordered = sorted(vols)
    n = len(ordered)
    mid = n // 2
    med = ordered[mid] if n % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])
    if med <= 0:
        return 0.0
    return float(sum(vols) / (med * n))


def _5b_climax_ok(slices: list[dict[str, Any]]) -> bool:
    """Prior 1m dumps ≥6% on ≥2× volume; this bar holds the low and closes green."""
    if len(slices) < 2:
        return False
    prior, last = slices[-2], slices[-1]
    pc = float(prior.get("c") or 0)
    po = float(prior.get("o") or pc)
    if pc <= 0 or po <= 0:
        return False
    if pc >= po:
        return False
    if _bar_range_pct(prior) < FIVE_B_DUMP_RANGE_PCT:
        return False
    vols = [float(s.get("v") or 0) for s in slices[:-1]]
    avg_v = (sum(vols) / len(vols)) if vols else 0.0
    if avg_v <= 0 or float(prior.get("v") or 0) < FIVE_B_VOL_MULT * avg_v:
        return False
    last_l = float(last.get("l") or last.get("c") or 0)
    prior_l = float(prior.get("l") or pc)
    last_c = float(last.get("c") or 0)
    last_o = float(last.get("o") or last_c)
    hold = last_l >= prior_l
    green = last_c > last_o or last_c > pc
    return bool(hold and green)


def _5b_r_frac(slices: list[dict[str, Any]]) -> float:
    last = slices[-1] if slices else {}
    rng = _bar_range_pct(last)
    return max(rng / 100.0, FIVE_B_STOP_FLOOR_PCT / 100.0)


def _5b_target_frac(structural_move_pct: float = 0.0) -> float:
    move = abs(float(structural_move_pct or 0))
    if move > 0:
        return max(move / 100.0 * 0.5, FIVE_B_STOP_FLOOR_PCT / 100.0)
    return FIVE_B_TARGET_FRAC


def _lookback_stop_px(
    px: float,
    slices: list[dict[str, Any]],
    n: int,
    floor_pct: float,
    *,
    cap_pct: float | None = ONE_M_STOP_CAP_PCT,
) -> tuple[float, float]:
    """Lookback-low: not tighter than floor, not deeper than cap (1m max loss)."""
    if px <= 0:
        return 0.0, floor_pct / 100.0
    floor = px * (1.0 - floor_pct / 100.0)
    win = slices[-n:] if slices else []
    lows = [float(s.get("l") or 0) for s in win if float(s.get("l") or 0) > 0]
    lo_win = min(lows) if lows else floor
    stop_px = lo_win if lo_win > 0 and lo_win < px else floor
    if stop_px > floor:
        stop_px = floor
    if cap_pct is not None and cap_pct > 0:
        cap = px * (1.0 - cap_pct / 100.0)
        if stop_px < cap:
            stop_px = cap
    if stop_px >= px:
        stop_px = floor
        if cap_pct is not None and cap_pct > 0:
            stop_px = max(stop_px, px * (1.0 - cap_pct / 100.0))
    stop_frac = (px - stop_px) / px if px > 0 else floor_pct / 100.0
    stop_frac = max(stop_frac, floor_pct / 100.0)
    if cap_pct is not None and cap_pct > 0:
        stop_frac = min(stop_frac, cap_pct / 100.0)
    return stop_px, stop_frac


def _5b_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    """Lookback-low stop (floor 2%, cap 3.5%), half-structural target. Prices for a long."""
    px = float(fill or 0)
    if px <= 0:
        return 0.0, 0.0, FIVE_B_STOP_FLOOR_PCT / 100.0
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, FIVE_B_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + _5b_target_frac(structural_move_pct))
    return stop_px, tgt_px, stop_frac


def _2a_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + TWO_A_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _2b_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + TWO_B_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _2c_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + TWO_C_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _3a_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    px = float(fill or 0)
    floor_pct = THREE_A_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, THREE_A_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + THREE_A_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _2d_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + TWO_D_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _4a_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + FOUR_A_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _3b_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = THREE_B_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, THREE_B_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + THREE_B_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _5a_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + FIVE_A_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _7a_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = SEVEN_A_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, SEVEN_A_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + SEVEN_A_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _3c_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = THREE_C_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, THREE_C_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + THREE_C_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _4d_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + FOUR_D_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _4b_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + FOUR_B_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _6a_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = SIX_A_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, SIX_A_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + SIX_A_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _4c_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + FOUR_C_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _4e_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    tgt_px = px * (1.0 + FOUR_E_TARGET_FRAC) if px > 0 else 0.0
    return stop_px, tgt_px, stop_frac


def _6b_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = SIX_B_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, SIX_B_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + SIX_B_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _3d_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = THREE_D_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, THREE_D_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + THREE_D_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _7b_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = SEVEN_B_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, SEVEN_B_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + SEVEN_B_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _3g_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = THREE_G_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, THREE_G_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + THREE_G_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _3f_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = THREE_F_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, THREE_F_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + THREE_F_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _8a_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = EIGHT_A_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, EIGHT_A_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + EIGHT_A_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _7c_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = SEVEN_C_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, SEVEN_C_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + SEVEN_C_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _3e_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = THREE_E_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, THREE_E_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + THREE_E_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _6c_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
) -> tuple[float, float, float]:
    _ = structural_move_pct
    px = float(fill or 0)
    floor_pct = SIX_C_STOP_FLOOR_PCT / 100.0
    if px <= 0:
        return 0.0, 0.0, floor_pct
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, FIVE_B_LOOKBACK_BARS, SIX_C_STOP_FLOOR_PCT
    )
    tgt_px = px * (1.0 + SIX_C_TARGET_FRAC)
    return stop_px, tgt_px, stop_frac


def _5m_spec_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    *,
    floor_pct: float,
    tgt_frac: float,
) -> tuple[float, float, float]:
    px = float(fill or 0)
    floor = float(floor_pct) / 100.0
    if px <= 0:
        return 0.0, 0.0, floor
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, ONE_A_5M_LOOKBACK, floor_pct, cap_pct=None
    )
    tgt_px = px * (1.0 + float(tgt_frac))
    return stop_px, tgt_px, stop_frac


def _1a_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=ONE_A_5M_STOP_FLOOR_PCT, tgt_frac=ONE_A_5M_TARGET_FRAC
    )


def _1b_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=ONE_B_5M_STOP_FLOOR_PCT, tgt_frac=ONE_B_5M_TARGET_FRAC
    )


def _5a_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=FIVE_A_5M_STOP_FLOOR_PCT, tgt_frac=FIVE_A_5M_TARGET_FRAC
    )


def _1c_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=ONE_C_5M_STOP_FLOOR_PCT, tgt_frac=ONE_C_5M_TARGET_FRAC
    )


def _9a_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=NINE_A_5M_STOP_FLOOR_PCT, tgt_frac=NINE_A_5M_TARGET_FRAC
    )


def _5b_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=FIVE_B_5M_STOP_FLOOR_PCT, tgt_frac=FIVE_B_5M_TARGET_FRAC
    )


def _2b_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=TWO_B_5M_STOP_FLOOR_PCT, tgt_frac=TWO_B_5M_TARGET_FRAC
    )


def _5c_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=FIVE_C_5M_STOP_FLOOR_PCT, tgt_frac=FIVE_C_5M_TARGET_FRAC
    )


def _8a_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=EIGHT_A_5M_STOP_FLOOR_PCT, tgt_frac=EIGHT_A_5M_TARGET_FRAC
    )


def _6a_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=SIX_A_5M_STOP_FLOOR_PCT, tgt_frac=SIX_A_5M_TARGET_FRAC
    )


def _2c_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=TWO_C_5M_STOP_FLOOR_PCT, tgt_frac=TWO_C_5M_TARGET_FRAC
    )


def _2d_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=TWO_D_5M_STOP_FLOOR_PCT, tgt_frac=TWO_D_5M_TARGET_FRAC
    )


def _2a_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=TWO_A_5M_STOP_FLOOR_PCT, tgt_frac=TWO_A_5M_TARGET_FRAC
    )


def _1d_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=ONE_D_5M_STOP_FLOOR_PCT, tgt_frac=ONE_D_5M_TARGET_FRAC
    )


def _4a_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=FOUR_A_5M_STOP_FLOOR_PCT, tgt_frac=FOUR_A_5M_TARGET_FRAC
    )


def _6b_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=SIX_B_5M_STOP_FLOOR_PCT, tgt_frac=SIX_B_5M_TARGET_FRAC
    )


def _8b_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=EIGHT_B_5M_STOP_FLOOR_PCT, tgt_frac=EIGHT_B_5M_TARGET_FRAC
    )


def _3a_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=THREE_A_5M_STOP_FLOOR_PCT, tgt_frac=THREE_A_5M_TARGET_FRAC
    )


def _9b_5m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=NINE_B_5M_STOP_FLOOR_PCT, tgt_frac=NINE_B_5M_TARGET_FRAC
    )


def _1a_15m_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices, fill, floor_pct=ONE_A_15M_STOP_FLOOR_PCT, tgt_frac=ONE_A_15M_TARGET_FRAC
    )


def _15m_origin_pack_exits(slices, fill, structural_move_pct=0.0):
    _ = structural_move_pct
    return _5m_spec_pack_exits(
        slices,
        fill,
        floor_pct=FIFTEEN_M_ORIGIN_STOP_FLOOR_PCT,
        tgt_frac=FIFTEEN_M_ORIGIN_TARGET_FRAC,
    )


def _1a_style_for(handle: str) -> str:
    if handle == "trip":
        return ONE_A_EXIT_TRIP
    if handle == "mild":
        return ONE_A_EXIT_MILD
    return ONE_A_EXIT_VIOLENT


def _1a_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    handle: str,
) -> tuple[float, float, float]:
    stop_px, _, stop_frac = _5b_pack_exits(slices, fill, 0.0)
    px = float(fill or 0)
    if px <= 0:
        return stop_px, 0.0, stop_frac
    if handle == "trip":
        return stop_px, 0.0, stop_frac
    frac = ONE_A_MILD_TARGET_FRAC if handle == "mild" else ONE_A_VIOLENT_TARGET_FRAC
    return stop_px, px * (1.0 + frac), stop_frac


def _ph_target_frac(structural_move_pct: float = 0.0, tf: str = "1m") -> float:
    tf_n = room3_recipes.normalize_tf(tf)
    if tf_n == "15m":
        return PH_15M_TARGET_FRAC
    move = abs(float(structural_move_pct or 0))
    if tf_n == "5m" and move > 0:
        return max(move / 100.0 * PH_5M_STRUCT_FRAC, FIVE_B_STOP_FLOOR_PCT / 100.0)
    return _5b_target_frac(structural_move_pct)


def _ph_lookback(tf: str) -> int:
    tf_n = room3_recipes.normalize_tf(tf)
    if tf_n == "1m":
        return FIVE_B_LOOKBACK_BARS
    return 3


def _ph_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
    tf: str = "1m",
) -> tuple[float, float, float]:
    px = float(fill or 0)
    n = _ph_lookback(tf)
    if px <= 0:
        return 0.0, 0.0, FIVE_B_STOP_FLOOR_PCT / 100.0
    cap = ONE_M_STOP_CAP_PCT if room3_recipes.normalize_tf(tf) == "1m" else None
    stop_px, stop_frac = _lookback_stop_px(
        px, slices, n, FIVE_B_STOP_FLOOR_PCT, cap_pct=cap
    )
    tgt_px = px * (1.0 + _ph_target_frac(structural_move_pct, tf))
    return stop_px, tgt_px, stop_frac


def _5b_lot_exit(lot: dict[str, Any]) -> bool:
    style = str(lot.get("exit_style") or "")
    if style in (
        FIVE_B_EXIT_STYLE,
        FIVE_B_EXIT_STYLE_LEGACY,
        TWO_A_EXIT_STYLE,
        TWO_B_EXIT_STYLE,
        TWO_C_EXIT_STYLE,
        THREE_A_EXIT_STYLE,
        TWO_D_EXIT_STYLE,
        FOUR_A_EXIT_STYLE,
        THREE_B_EXIT_STYLE,
        FIVE_A_EXIT_STYLE,
        SEVEN_A_EXIT_STYLE,
        THREE_C_EXIT_STYLE,
        FOUR_D_EXIT_STYLE,
        FOUR_B_EXIT_STYLE,
        SIX_A_EXIT_STYLE,
        FOUR_C_EXIT_STYLE,
        FOUR_E_EXIT_STYLE,
        SIX_B_EXIT_STYLE,
        THREE_D_EXIT_STYLE,
        SEVEN_B_EXIT_STYLE,
        THREE_G_EXIT_STYLE,
        THREE_F_EXIT_STYLE,
        EIGHT_A_EXIT_STYLE,
        SEVEN_C_EXIT_STYLE,
        THREE_E_EXIT_STYLE,
        SIX_C_EXIT_STYLE,
        ONE_A_5M_EXIT_STYLE,
        ONE_B_5M_EXIT_STYLE,
        FIVE_A_5M_EXIT_STYLE,
        PH_EXIT_STYLE,
        PH_5M_EXIT_STYLE,
        *ONE_A_EXIT_STYLES,
    ):
        return True
    strat = str(lot.get("strategy") or lot.get("letter") or "")
    tf = str(lot.get("tf") or lot.get("timeframe") or "1m")
    return (
        _is_5b_1m(strat, tf)
        or _is_2a_1m(strat, tf)
        or _is_2b_1m(strat, tf)
        or _is_2c_1m(strat, tf)
        or _is_3a_1m(strat, tf)
        or _is_4a_1m(strat, tf)
        or _is_3b_1m(strat, tf)
        or _is_5a_1m(strat, tf)
        or _is_7a_1m(strat, tf)
        or _is_3c_1m(strat, tf)
        or _is_4d_1m(strat, tf)
        or _is_4b_1m(strat, tf)
        or _is_6a_1m(strat, tf)
        or _is_4c_1m(strat, tf)
        or _is_4e_1m(strat, tf)
        or _is_6b_1m(strat, tf)
        or _is_3d_1m(strat, tf)
        or _is_7b_1m(strat, tf)
        or _is_3g_1m(strat, tf)
        or _is_3f_1m(strat, tf)
        or _is_8a_1m(strat, tf)
        or _is_7c_1m(strat, tf)
        or _is_3e_1m(strat, tf)
        or _is_6c_1m(strat, tf)
        or _is_1a_5m(strat, tf)
        or _is_1b_5m(strat, tf)
        or _is_5a_5m(strat, tf)
        or _is_1c_5m(strat, tf)
        or _is_9a_5m(strat, tf)
        or _is_5b_5m(strat, tf)
        or _is_2b_5m(strat, tf)
        or _is_5c_5m(strat, tf)
        or _is_8a_5m(strat, tf)
        or _is_6a_5m(strat, tf)
        or _is_2c_5m(strat, tf)
        or _is_2d_5m(strat, tf)
        or _is_2a_5m(strat, tf)
        or _is_1d_5m(strat, tf)
        or _is_4a_5m(strat, tf)
        or _is_6b_5m(strat, tf)
        or _is_8b_5m(strat, tf)
        or _is_3a_5m(strat, tf)
        or _is_9b_5m(strat, tf)
        or _is_1a_15m(strat, tf)
        or bool(_is_15m_origin_letter(strat, tf))
        or _is_1a_1m(strat, tf)
        or _is_2d_1m(strat, tf)
    )


def _ticker_already_engaged(
    book: dict[str, Any],
    ticker: str,
    *,
    except_key: str = "",
    session_state: Any = None,
    letter: str = "",
) -> bool:
    """True if this letter is already in/queued. A different letter may add."""
    token = room3_lots.letter_token("", letter) if letter else ""
    if token and session_state is not None:
        if room3_lots.open_lots(session_state, ticker, letter=token):
            return True
    for key, line in (book.get("lines") or {}).items():
        if except_key and key == except_key:
            continue
        if str(line.get("ticker") or "").upper() != str(ticker).upper():
            continue
        queued = str((line.get("entry_signal") or {}).get("strategy") or "")
        if token and queued and room3_lots.letter_token("", queued) == token:
            return True
        if token:
            continue
        # No letter asked: only block a duplicate queue on this same line.
        if except_key and key == except_key:
            continue
    return False


def _sync_hot_children(
    line: dict[str, Any],
    ranked: list[dict[str, Any]],
    session_state: Any,
    ticker: str,
    tf: str,
) -> list[dict[str, Any]]:
    """Mint/keep fire-ready sub-lanes. Open lots stay even if Match% cools."""
    prev = {
        str(c.get("letter") or ""): dict(c)
        for c in (line.get("children") or [])
        if isinstance(c, dict) and str(c.get("letter") or "").strip()
    }
    open_tokens = {
        str(r.get("letter") or "")
        for r in room3_lots.open_lots(session_state, ticker, tf=tf)
        if str(r.get("letter") or "").strip()
    }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ranked or []:
        layout = str(row.get("layout_id") or "")
        strat = str(row.get("strategy") or "")
        if room3_recipes.is_purgatory_letter(layout, strat):
            continue
        letter = str(row.get("letter") or room3_lots.letter_token(layout, strat))
        if not letter or letter in seen:
            continue
        pct = int(row.get("spatial_match_pct") or 0)
        if pct < CHILD_READY_PCT and letter not in open_tokens:
            continue
        seen.add(letter)
        old = prev.get(letter) or {}
        child = {
            "letter": letter,
            "layout_id": layout,
            "strategy": strat or letter,
            "match_pct": pct,
            "structural_move_pct": float(row.get("structural_move_pct") or 0),
            "cosine_similarity": float(row.get("cosine_similarity") or 0),
            "family_armed_px": old.get("family_armed_px"),
            "family_armed_high": old.get("family_armed_high"),
            "pullback_low": old.get("pullback_low"),
            "trigger_phase": old.get("trigger_phase"),
            "entry_skipped_late": old.get("entry_skipped_late"),
            "patience_note": str(old.get("patience_note") or ""),
            "in_lot": letter in open_tokens,
        }
        if pct < WARMING_MATCH_PCT and letter not in open_tokens:
            _reset_entry_trigger(child)
        out.append(child)
    for letter in open_tokens:
        if letter in seen:
            continue
        old = prev.get(letter) or {}
        old["letter"] = letter
        old["in_lot"] = True
        out.append(old)
    line["children"] = out
    return out


def _child_match_floor(session_state: Any, child: dict[str, Any], tf: str) -> float:
    floor = float(MATCH_THRESHOLD_PCT)
    try:
        floor += float(
            room3_review_learn.overlay_match_floor_delta(
                session_state,
                str(child.get("layout_id") or ""),
                str(child.get("strategy") or ""),
                tf,
            )
        )
    except Exception:
        pass
    return max(70.0, min(95.0, floor))


def _try_queue_child_entry(
    book: dict[str, Any],
    line: dict[str, Any],
    *,
    session_state: Any,
    ticker: str,
    tf: str,
    last_px: float,
    slices: list[dict[str, Any]],
    layouts: list[dict[str, Any]],
    match: dict[str, Any],
) -> bool:
    """Queue one child that is fire-ready. Second letter on the pile is an add.

    A sibling TF's unfilled stamp does not freeze this TF. Alpaca is one pile;
    the second fill adds as its own lot. This line still waits if *it* already
    has a working order.
    """
    import room3_watcher

    if line.get("entry_signal"):
        return False
    if line.get("order_pending") or str(line.get("state") or "") == "committed":
        return False
    children = list(line.get("children") or [])
    for child in children:
        if not isinstance(child, dict):
            continue
        letter = str(child.get("letter") or "")
        layout_id = str(child.get("layout_id") or "")
        strategy = str(child.get("strategy") or letter)
        if not letter or room3_recipes.is_purgatory_letter(layout_id, strategy):
            continue
        if child.get("in_lot"):
            continue
        if _ticker_already_engaged(
            book, ticker, except_key=room3_watcher.line_key(ticker, tf),
            session_state=session_state, letter=letter,
        ):
            continue
        pct = int(child.get("match_pct") or 0)
        floor = _child_match_floor(session_state, child, tf)
        if pct < floor:
            if pct >= WARMING_MATCH_PCT:
                child["patience_note"] = f"warming {pct}% · need ≥{int(floor)}%"
            continue
        structural = float(child.get("structural_move_pct") or 0)
        ready, trigger_note = _entry_trigger_ready(
            child,
            slices,
            last_px=last_px,
            tf=tf,
            strategy=strategy,
            layout_id=layout_id,
            structural=structural,
            session_state=session_state,
        )
        child["patience_note"] = trigger_note
        if not ready:
            continue
        add_lot = bool(room3_lots.open_lots(session_state, ticker) or _open_qty(session_state, ticker) > 0)
        if tf == "15m" and not _15m_can_open_lot(session_state, ticker, scale_in=False):
            child["patience_note"] = "15m add already used · wait exit"
            continue
        qty, notional = _compute_entry_qty(
            price=last_px,
            session_state=session_state,
            timeframe=tf,
            match_pct=pct,
            second_cosine=float(match.get("second_cosine") or 0),
            best_cosine=float(child.get("cosine_similarity") or match.get("cosine_similarity") or 0),
            layouts=layouts,
            exclude_ticker=ticker if add_lot else "",
        )
        if qty < 1 or notional <= 0:
            child["patience_note"] = "size $0 — not enough room or price too high"
            continue
        _claim_cash(session_state, notional)
        room3_watcher.queue_entry_signal(
            book,
            ticker,
            tf,
            side="buy",
            qty=qty,
            strategy=strategy,
            keep_in=add_lot and str(line.get("state") or "") == "in",
            scale_in=False,
            layout_id=layout_id,
        )
        key = room3_watcher.line_key(ticker, tf)
        stamped = (book.get("lines") or {}).get(key) or line
        stamped["entry_match_pct"] = pct
        stamped["entry_layout"] = layout_id
        stamped["entry_strategy"] = strategy
        stamped["entry_price"] = last_px
        stamped["entry_qty"] = qty
        stamped["entry_structural_move_pct"] = structural
        sig = stamped.get("entry_signal")
        if isinstance(sig, dict):
            sig["ref_price"] = last_px
            sig["notional"] = notional
            sig["match_pct"] = pct
            sig["layout_id"] = layout_id
            sig["strategy"] = strategy
            sig["add_lot"] = add_lot
            sig["letter"] = letter
            sig["trigger"] = trigger_note
            sig["order_style"] = room3_review_learn.resolved_order_style(
                session_state,
                strategy,
                tf,
                layout_id=layout_id,
                structural_move_pct=structural,
            )
            if _is_5b_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _5b_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FIVE_B_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FIVE_B_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5b_mark_used(session_state, ticker)
            elif _is_2a_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _2a_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = TWO_A_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = TWO_A_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _2a_mark_used(session_state, ticker)
            elif _is_2b_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _2b_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = TWO_B_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = TWO_B_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _2b_mark_used(session_state, ticker)
            elif _is_2c_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _2c_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = TWO_C_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = TWO_C_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _2c_mark_used(session_state, ticker)
            elif _is_3a_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _3a_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = THREE_A_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = THREE_A_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _3a_mark_used(session_state, ticker)
            elif _is_1a_1m(strategy, tf):
                handle = str(line.get("1a_handle") or _1a_classify(slices) or "violent")
                stop_px, tgt_px, stop_frac = _1a_pack_exits(slices, last_px, handle)
                style = _1a_style_for(handle)
                sig["exit_style"] = style
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                sig["1a_handle"] = handle
                stamped["exit_style"] = style
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                stamped["1a_handle"] = handle
                _1a_mark_used(session_state, ticker)
            elif _is_2d_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _2d_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = TWO_D_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = TWO_D_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _2d_mark_shot(session_state, ticker)
            elif _is_4a_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _4a_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FOUR_A_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FOUR_A_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _4a_mark_used(session_state, ticker)
            elif _is_3b_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _3b_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = THREE_B_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = THREE_B_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _3b_mark_used(session_state, ticker)
            elif _is_5a_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _5a_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FIVE_A_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FIVE_A_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5a_mark_used(session_state, ticker)
            elif _is_7a_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _7a_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = SEVEN_A_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = SEVEN_A_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _7a_mark_used(session_state, ticker)
            elif _is_3c_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _3c_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = THREE_C_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = THREE_C_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _3c_mark_used(session_state, ticker)
            elif _is_4d_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _4d_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FOUR_D_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FOUR_D_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _4d_mark_used(session_state, ticker)
            elif _is_4b_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _4b_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FOUR_B_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FOUR_B_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _4b_mark_used(session_state, ticker)
            elif _is_6a_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _6a_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = SIX_A_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = SIX_A_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _6a_mark_used(session_state, ticker)
            elif _is_4c_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _4c_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FOUR_C_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FOUR_C_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _4c_mark_used(session_state, ticker)
            elif _is_4e_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _4e_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FOUR_E_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FOUR_E_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _4e_mark_used(session_state, ticker)
            elif _is_6b_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _6b_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = SIX_B_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = SIX_B_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _6b_mark_used(session_state, ticker)
            elif _is_3d_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _3d_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = THREE_D_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = THREE_D_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _3d_mark_used(session_state, ticker)
            elif _is_7b_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _7b_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = SEVEN_B_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = SEVEN_B_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _7b_mark_used(session_state, ticker)
            elif _is_3g_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _3g_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = THREE_G_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = THREE_G_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _3g_mark_used(session_state, ticker)
            elif _is_3f_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _3f_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = THREE_F_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = THREE_F_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _3f_mark_used(session_state, ticker)
            elif _is_8a_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _8a_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = EIGHT_A_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = EIGHT_A_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _8a_mark_used(session_state, ticker)
            elif _is_7c_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _7c_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = SEVEN_C_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = SEVEN_C_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _7c_mark_used(session_state, ticker)
            elif _is_3e_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _3e_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = THREE_E_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = THREE_E_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _3e_mark_used(session_state, ticker)
            elif _is_6c_1m(strategy, tf):
                stop_px, tgt_px, stop_frac = _6c_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = SIX_C_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = SIX_C_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _6c_mark_used(session_state, ticker)
            elif _is_1a_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _1a_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = ONE_A_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = ONE_A_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "1A", ticker)
            elif _is_1b_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _1b_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = ONE_B_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = ONE_B_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "1B", ticker)
            elif _is_5a_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _5a_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FIVE_A_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FIVE_A_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "5A", ticker)
            elif _is_1c_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _1c_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = ONE_C_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = ONE_C_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "1C", ticker)
            elif _is_9a_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _9a_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = NINE_A_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = NINE_A_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "9A", ticker)
            elif _is_5b_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _5b_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FIVE_B_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FIVE_B_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "5B", ticker)
            elif _is_2b_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _2b_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = TWO_B_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = TWO_B_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "2B", ticker)
            elif _is_5c_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _5c_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FIVE_C_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FIVE_C_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "5C", ticker)
            elif _is_8a_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _8a_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = EIGHT_A_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = EIGHT_A_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "8A", ticker)
            elif _is_6a_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _6a_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = SIX_A_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = SIX_A_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "6A", ticker)
            elif _is_2c_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _2c_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = TWO_C_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = TWO_C_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "2C", ticker)
            elif _is_2d_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _2d_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = TWO_D_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = TWO_D_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "2D", ticker)
            elif _is_2a_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _2a_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = TWO_A_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = TWO_A_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "2A", ticker)
            elif _is_1d_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _1d_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = ONE_D_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = ONE_D_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "1D", ticker)
            elif _is_4a_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _4a_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = FOUR_A_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = FOUR_A_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "4A", ticker)
            elif _is_6b_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _6b_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = SIX_B_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = SIX_B_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "6B", ticker)
            elif _is_8b_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _8b_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = EIGHT_B_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = EIGHT_B_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "8B", ticker)
            elif _is_3a_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _3a_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = THREE_A_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = THREE_A_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "3A", ticker)
            elif _is_9b_5m(strategy, tf):
                stop_px, tgt_px, stop_frac = _9b_5m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = NINE_B_5M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = NINE_B_5M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _5m_spec_mark_used(session_state, "9B", ticker)
            elif _is_1a_15m(strategy, tf):
                stop_px, tgt_px, stop_frac = _1a_15m_pack_exits(
                    slices, last_px, structural
                )
                sig["exit_style"] = ONE_A_15M_EXIT_STYLE
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = ONE_A_15M_EXIT_STYLE
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _15m_spec_mark_used(session_state, "1A", ticker)
            elif _is_15m_origin_letter(strategy, tf):
                head = _is_15m_origin_letter(strategy, tf)
                stop_px, tgt_px, stop_frac = _15m_origin_pack_exits(
                    slices, last_px, structural
                )
                style = {
                    "1B": ONE_B_15M_EXIT_STYLE,
                    "1C": ONE_C_15M_EXIT_STYLE,
                    "1D": ONE_D_15M_EXIT_STYLE,
                    "2A": TWO_A_15M_EXIT_STYLE,
                    "2B": TWO_B_15M_EXIT_STYLE,
                    "6A": SIX_A_15M_EXIT_STYLE,
                    "9A": NINE_A_15M_EXIT_STYLE,
                }[head]
                sig["exit_style"] = style
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = style
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _15m_spec_mark_used(session_state, head, ticker)
            else:
                stop_px, tgt_px, stop_frac = _ph_pack_exits(
                    slices, last_px, structural, tf
                )
                ph_style = (
                    PH_5M_EXIT_STYLE
                    if room3_recipes.normalize_tf(tf) == "5m"
                    else PH_EXIT_STYLE
                )
                sig["exit_style"] = ph_style
                sig["exit_r_frac"] = stop_frac
                sig["exit_stop_px"] = stop_px
                sig["exit_tgt_px"] = tgt_px
                stamped["exit_style"] = ph_style
                stamped["exit_r_frac"] = stop_frac
                stamped["exit_stop_px"] = stop_px
                stamped["exit_tgt_px"] = tgt_px
                _ph_mark_used(session_state, ticker, strategy)
            if room3_recipes.normalize_tf(tf) == "1m":
                _1m_mark_name_shot(session_state, ticker)
        line["nearest_strategy"] = strategy
        line["patience"] = False
        line.pop("patience_note", None)
        return True
    return False


def _lot_should_exit(
    lot: dict[str, Any],
    *,
    cur_match: int,
    last_px: float,
    patience: bool,
    bar: dict[str, Any] | None = None,
    session_state: Any = None,
) -> str:
    if _5b_lot_exit(lot):
        return _5b_should_exit(lot, last_px=last_px, bar=bar, session_state=session_state)
    entry_px = float(lot.get("entry_px") or 0)
    entry_match = int(lot.get("entry_match_pct") or MATCH_THRESHOLD_PCT)
    structural = float(lot.get("structural_move_pct") or 0)
    pnl_pct = ((last_px - entry_px) / entry_px * 100.0) if entry_px > 0 and last_px > 0 else 0.0
    hard_fade = cur_match < EXIT_MATCH_FLOOR_PCT and cur_match < entry_match - 15
    soft_fade = cur_match < EXIT_MATCH_FLOOR_PCT and cur_match < entry_match - 10
    if hard_fade:
        return f"match faded {cur_match}%"
    if soft_fade and not patience:
        return f"match faded {cur_match}%"
    if soft_fade and patience and structural > 0 and pnl_pct < structural * 0.25:
        return ""
    if soft_fade:
        return f"match faded {cur_match}%"
    if pnl_pct <= -STOP_LOSS_PCT:
        return f"stop {pnl_pct:.1f}%"
    if structural > 0 and pnl_pct >= structural * 0.5:
        return f"target {pnl_pct:.1f}%"
    if _approaching_day_close():
        return "day close · second-best exit"
    return ""


def _5b_should_exit(
    lot: dict[str, Any],
    *,
    last_px: float,
    bar: dict[str, Any] | None = None,
    session_state: Any = None,
) -> str:
    entry_px = float(lot.get("entry_px") or 0)
    if entry_px <= 0:
        return ""
    frac = float(lot.get("exit_r_frac") or FIVE_B_STOP_FLOOR_PCT / 100.0)
    stop_px = float(lot.get("exit_stop_px") or entry_px * (1.0 - frac))
    style = str(lot.get("exit_style") or FIVE_B_EXIT_STYLE)
    if style == FIVE_B_EXIT_STYLE_LEGACY:
        tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + frac))
    else:
        if style == TWO_A_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + TWO_A_TARGET_FRAC))
        elif style == TWO_B_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + TWO_B_TARGET_FRAC))
        elif style == TWO_C_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + TWO_C_TARGET_FRAC))
        elif style == THREE_A_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + THREE_A_TARGET_FRAC))
        elif style == TWO_D_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + TWO_D_TARGET_FRAC))
        elif style == FOUR_A_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + FOUR_A_TARGET_FRAC))
        elif style == THREE_B_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + THREE_B_TARGET_FRAC))
        elif style == FIVE_A_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + FIVE_A_TARGET_FRAC))
        elif style == SEVEN_A_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + SEVEN_A_TARGET_FRAC))
        elif style == THREE_C_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + THREE_C_TARGET_FRAC))
        elif style == FOUR_D_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + FOUR_D_TARGET_FRAC))
        elif style == FOUR_B_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + FOUR_B_TARGET_FRAC))
        elif style == SIX_A_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + SIX_A_TARGET_FRAC))
        elif style == FOUR_C_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + FOUR_C_TARGET_FRAC))
        elif style == FOUR_E_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + FOUR_E_TARGET_FRAC))
        elif style == SIX_B_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + SIX_B_TARGET_FRAC))
        elif style == THREE_D_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + THREE_D_TARGET_FRAC))
        elif style == SEVEN_B_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + SEVEN_B_TARGET_FRAC))
        elif style == THREE_G_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + THREE_G_TARGET_FRAC))
        elif style == THREE_F_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + THREE_F_TARGET_FRAC))
        elif style == EIGHT_A_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + EIGHT_A_TARGET_FRAC))
        elif style == SEVEN_C_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + SEVEN_C_TARGET_FRAC))
        elif style == THREE_E_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + THREE_E_TARGET_FRAC))
        elif style == SIX_C_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + SIX_C_TARGET_FRAC))
        elif style == ONE_A_5M_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + ONE_A_5M_TARGET_FRAC))
        elif style == ONE_B_5M_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + ONE_B_5M_TARGET_FRAC))
        elif style == FIVE_A_5M_EXIT_STYLE:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + FIVE_A_5M_TARGET_FRAC))
        elif style == ONE_A_EXIT_MILD:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + ONE_A_MILD_TARGET_FRAC))
        elif style == ONE_A_EXIT_VIOLENT:
            tgt_px = float(lot.get("exit_tgt_px") or entry_px * (1.0 + ONE_A_VIOLENT_TARGET_FRAC))
        elif style == ONE_A_EXIT_TRIP:
            tgt_px = 0.0
        else:
            tf_lot = room3_recipes.normalize_tf(str(lot.get("tf") or lot.get("timeframe") or ""))
            tgt_px = float(
                lot.get("exit_tgt_px")
                or entry_px
                * (
                    1.0
                    + _ph_target_frac(float(lot.get("structural_move_pct") or 0), tf_lot)
                )
            )
    lo = float((bar or {}).get("l") or last_px or 0)
    hi = float((bar or {}).get("h") or last_px or 0)
    tf_n = room3_recipes.normalize_tf(str(lot.get("tf") or lot.get("timeframe") or ""))
    five_m_trail = style == PH_5M_EXIT_STYLE or (
        style == PH_EXIT_STYLE and tf_n == "5m"
    )
    if style == ONE_A_EXIT_TRIP or five_m_trail:
        peak = max(float(lot.get("exit_high_px") or entry_px), hi if hi > 0 else 0.0, last_px or 0.0)
        lot["exit_high_px"] = peak
        if five_m_trail:
            arm_px = float(lot.get("exit_tgt_px") or 0)
            if arm_px <= 0 and entry_px > 0:
                arm_px = entry_px * (
                    1.0
                    + _ph_target_frac(float(lot.get("structural_move_pct") or 0), "5m")
                )
            trail_frac = PH_5M_TRAIL_FRAC
            if arm_px > 0 and peak >= arm_px:
                lot["exit_runner_on"] = True
        else:
            trail_frac = ONE_A_TRIP_TRAIL_FRAC
            if peak >= entry_px * (1.0 + ONE_A_TRIP_ARM_FRAC):
                lot["exit_runner_on"] = True
        if lot.get("exit_runner_on"):
            trail = peak * (1.0 - trail_frac)
            if trail > stop_px:
                stop_px = trail
                lot["exit_stop_px"] = stop_px
        if lo > 0 and lo <= stop_px:
            pnl_pct = (stop_px - entry_px) / entry_px * 100.0
            return f"{'runner' if lot.get('exit_runner_on') else 'stop'} {pnl_pct:.1f}%"
        if last_px > 0 and last_px <= stop_px:
            pnl_pct = (last_px - entry_px) / entry_px * 100.0
            return f"{'runner' if lot.get('exit_runner_on') else 'stop'} {pnl_pct:.1f}%"
        if _approaching_day_close():
            return "day close · second-best exit"
        return ""
    if lo > 0 and lo <= stop_px:
        pnl_pct = (stop_px - entry_px) / entry_px * 100.0
        return f"stop {pnl_pct:.1f}%"
    if last_px > 0 and last_px <= stop_px:
        pnl_pct = (last_px - entry_px) / entry_px * 100.0
        return f"stop {pnl_pct:.1f}%"
    if hi >= tgt_px or (last_px > 0 and last_px >= tgt_px):
        pnl_pct = (tgt_px - entry_px) / entry_px * 100.0
        return f"target {pnl_pct:.1f}%"
    if style == FIVE_B_EXIT_STYLE_LEGACY:
        raw_ts = lot.get("entry_ts") or ""
        if raw_ts:
            try:
                opened = datetime.fromisoformat(str(raw_ts))
                if opened.tzinfo is None:
                    opened = opened.replace(tzinfo=room3_engine.ET)
                if (_5b_now(session_state) - opened).total_seconds() >= FIVE_B_HOLD_SEC:
                    pnl_pct = ((last_px - entry_px) / entry_px * 100.0) if last_px else 0.0
                    return f"time {pnl_pct:.1f}%"
            except (TypeError, ValueError):
                pass
    if _approaching_day_close():
        return "day close · second-best exit"
    return ""


def _open_qty(session_state: Any, symbol: str) -> float:
    try:
        for row in session_state.get("room3_open_positions") or []:
            if str(row.get("ticker") or "").upper() == str(symbol).upper():
                return abs(float(row.get("qty") or 0))
    except Exception:
        pass
    return 0.0


def _15m_scale_in_used(session_state: Any, ticker: str) -> bool:
    try:
        book = session_state.get("room3_watch_book") or {}
        for line in (book.get("lines") or {}).values():
            if str(line.get("ticker") or "").upper() != str(ticker).upper():
                continue
            if str(line.get("timeframe") or "") != "15m":
                continue
            if int(line.get("scale_ins") or 0) >= SCALE_IN_MAX:
                return True
    except Exception:
        return False
    return False


def _15m_can_open_lot(
    session_state: Any,
    ticker: str,
    *,
    scale_in: bool = False,
) -> bool:
    """A live 15m can add once: initial lot + one add (scale-in or a second 15m letter)."""
    n15 = len(room3_lots.open_lots(session_state, ticker, tf="15m"))
    all_lots = room3_lots.open_lots(session_state, ticker)
    broker_qty = _open_qty(session_state, ticker)
    if n15 >= 2:
        return False
    # Lot book vanished while Alpaca still holds the name — do not mint another 15m.
    if n15 <= 0 and broker_qty > 0 and not all_lots:
        return False
    if n15 <= 0:
        return True
    if scale_in:
        return not _15m_scale_in_used(session_state, ticker)
    if _15m_scale_in_used(session_state, ticker):
        return False
    return True


def _off_belt(line: dict[str, Any], book: dict[str, Any]) -> bool:
    """Open leftover maps (keep_tickers) that are not on the operator belt."""
    if line.get("in_filter") is False:
        return True
    ticker = str(line.get("ticker") or "").upper()
    uni = {str(t).upper() for t in (book.get("universe") or []) if str(t).strip()}
    return bool(ticker) and ticker not in uni


def _enter_on_print(
    strategy: str,
    tf: str,
    layout_id: str,
    structural_move_pct: float,
    session_state: Any = None,
) -> bool:
    """1m / specialized 5m: fill-now after the letter's Hunt extra. Other 5m/15m wait Handle."""
    _ = (strategy, layout_id, structural_move_pct, session_state)
    return room3_recipes.normalize_tf(tf) == "1m"


def _5b_gene_ok(slices: list[dict[str, Any]]) -> bool:
    return bool(_5b_climax_ok(slices) and _5b_tape_rvol(slices) >= FIVE_B_RVOL_MIN)


def _1m_live_fill_now(
    line: dict[str, Any],
    tag: str,
    *,
    gene_ok: bool = True,
    wait: str = "wait suited tape",
) -> tuple[bool, str]:
    """Fill now on the print. Specialized letters pass gene_ok first (operator 2026-09-20)."""
    if not gene_ok:
        return False, f"{tag} · {wait}"
    line["trigger_phase"] = "ready"
    return True, f"{tag} · enter now"


def _reset_entry_trigger(line: dict[str, Any]) -> None:
    line.pop("family_armed_px", None)
    line.pop("family_armed_high", None)
    line.pop("pullback_low", None)
    line.pop("trigger_phase", None)
    line.pop("entry_skipped_late", None)
    line.pop("1a_handle", None)


def _entry_is_late(line: dict[str, Any], last_px: float, structural: float) -> bool:
    armed = float(line.get("family_armed_px") or 0)
    if armed <= 0 or last_px <= 0:
        return False
    run_pct = (last_px - armed) / armed * 100.0
    if run_pct >= 8.0:
        return True
    if structural > 0 and run_pct >= max(2.0, structural * 0.5):
        return True
    return False


def _5b_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _5b_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"5B · cool {mins}m after stop"
    if _5b_open_chop(session_state):
        return False, "5B · skip 9:30–9:45"
    if _5b_used_today(session_state, ticker):
        return False, "5B · first of day already used"
    _ = last_px
    return _1m_live_fill_now(
        line, "5B", gene_ok=_5b_gene_ok(slices), wait="wait dump-then-hold"
    )


def _2a_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _2a_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"2A · cool {mins}m after stop"
    if _2a_open_chop(session_state):
        return False, "2A · skip 9:30–10:00"
    if _2a_used_today(session_state, ticker):
        return False, "2A · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "2A", gene_ok=_2a_gene_ok(slices))


def _2b_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _2b_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"2B · cool {mins}m after stop"
    if _2b_open_chop(session_state):
        return False, "2B · skip 9:30–9:45"
    if _2b_used_today(session_state, ticker):
        return False, "2B · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "2B", gene_ok=_2b_gene_ok(slices))


def _2c_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _2c_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"2C · cool {mins}m after stop"
    if _2c_open_chop(session_state):
        return False, "2C · skip 9:30–10:00"
    if _2c_used_today(session_state, ticker):
        return False, "2C · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "2C", gene_ok=_2c_gene_ok(slices))


def _3a_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _3a_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"3A · cool {mins}m after stop"
    if _3a_open_chop(session_state):
        return False, "3A · skip 9:30–10:00"
    if _3a_past_noon(session_state, hunting=False):
        return False, "3A · no new shot after 12:00"
    if _3a_used_today(session_state, ticker):
        return False, "3A · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "3A", gene_ok=_3a_gene_ok(slices))


def _2d_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _2d_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"2D · cool {mins}m after stop"
    if _2d_open_chop(session_state):
        return False, "2D · skip 9:30–9:45"
    if _2d_used_today(session_state, ticker):
        return False, "2D · done for the day"
    if _2d_shots_today(session_state, ticker) >= 1:
        return False, "2D · first of day already used"
    if not _2d_gene_ok(slices):
        return _1m_live_fill_now(line, "2D", gene_ok=False)
    if int(line.get("match_pct") or 0) < TWO_D_MATCH_MIN:
        return _1m_live_fill_now(line, "2D", gene_ok=False, wait="wait match ≥91")
    return _1m_live_fill_now(line, "2D")


def _4a_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _4a_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"4A · cool {mins}m after stop"
    if _4a_open_chop(session_state):
        return False, "4A · skip 9:30–9:45"
    if _4a_used_today(session_state, ticker):
        return False, "4A · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "4A", gene_ok=_4a_gene_ok(slices))


def _3b_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _3b_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"3B · cool {mins}m after stop"
    if _3b_open_chop(session_state):
        return False, "3B · skip 9:30–10:00"
    if _3b_used_today(session_state, ticker):
        return False, "3B · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "3B", gene_ok=_3b_gene_ok(slices))


def _5a_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _5a_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"5A · cool {mins}m after stop"
    if _5a_open_chop(session_state):
        return False, "5A · skip 9:30–9:45"
    if _5a_used_today(session_state, ticker):
        return False, "5A · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "5A", gene_ok=_5a_gene_ok(slices))


def _7a_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _7a_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"7A · cool {mins}m after stop"
    if _7a_open_chop(session_state):
        return False, "7A · skip 9:30–9:45"
    if _7a_used_today(session_state, ticker):
        return False, "7A · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "7A", gene_ok=_7a_gene_ok(slices))


def _3c_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _3c_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"3C · cool {mins}m after stop"
    if _3c_open_chop(session_state):
        return False, "3C · skip 9:30–9:45"
    if _3c_used_today(session_state, ticker):
        return False, "3C · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "3C", gene_ok=_3c_gene_ok(slices))


def _4d_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _4d_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"4D · cool {mins}m after stop"
    if _4d_open_chop(session_state):
        return False, "4D · skip 9:30–9:45"
    if _4d_used_today(session_state, ticker):
        return False, "4D · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "4D", gene_ok=_4d_gene_ok(slices))


def _4b_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _4b_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"4B · cool {mins}m after stop"
    if _4b_open_chop(session_state):
        return False, "4B · skip 9:30–10:00"
    if _4b_used_today(session_state, ticker):
        return False, "4B · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "4B", gene_ok=_4b_gene_ok(slices))


def _6a_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _6a_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"6A · cool {mins}m after stop"
    if _6a_open_chop(session_state):
        return False, "6A · skip 9:30–9:45"
    if _6a_used_today(session_state, ticker):
        return False, "6A · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "6A", gene_ok=_6a_gene_ok(slices))


def _4c_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _4c_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"4C · cool {mins}m after stop"
    if _4c_open_chop(session_state):
        return False, "4C · skip 9:30–9:45"
    if _4c_used_today(session_state, ticker):
        return False, "4C · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "4C", gene_ok=_4c_gene_ok(slices))


def _4e_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _4e_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"4E · cool {mins}m after stop"
    if _4e_open_chop(session_state):
        return False, "4E · skip 9:30–9:45"
    if _4e_used_today(session_state, ticker):
        return False, "4E · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "4E", gene_ok=_4e_gene_ok(slices))


def _6b_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _6b_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"6B · cool {mins}m after stop"
    if _6b_open_chop(session_state):
        return False, "6B · skip 9:30–9:45"
    if _6b_used_today(session_state, ticker):
        return False, "6B · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "6B", gene_ok=_6b_gene_ok(slices))


def _3d_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _3d_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"3D · cool {mins}m after stop"
    if _3d_open_chop(session_state):
        return False, "3D · skip 9:30–9:45"
    if _3d_used_today(session_state, ticker):
        return False, "3D · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "3D", gene_ok=_3d_gene_ok(slices))


def _7b_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _7b_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"7B · cool {mins}m after stop"
    if _7b_open_chop(session_state):
        return False, "7B · skip 9:30–9:45"
    if _7b_used_today(session_state, ticker):
        return False, "7B · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "7B", gene_ok=_7b_gene_ok(slices))


def _3g_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _3g_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"3G · cool {mins}m after stop"
    if _3g_open_chop(session_state):
        return False, "3G · skip 9:30–9:45"
    if _3g_used_today(session_state, ticker):
        return False, "3G · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "3G", gene_ok=_3g_gene_ok(slices))


def _3f_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _3f_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"3F · cool {mins}m after stop"
    if _3f_open_chop(session_state):
        return False, "3F · skip 9:30–10:00"
    if _3f_used_today(session_state, ticker):
        return False, "3F · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "3F", gene_ok=_3f_gene_ok(slices))


def _8a_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _8a_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"8A · cool {mins}m after stop"
    if _8a_open_chop(session_state):
        return False, "8A · skip 9:30–10:00"
    if _8a_used_today(session_state, ticker):
        return False, "8A · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "8A", gene_ok=_8a_gene_ok(slices))


def _7c_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _7c_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"7C · cool {mins}m after stop"
    if _7c_open_chop(session_state):
        return False, "7C · skip 9:30–10:00"
    if _7c_used_today(session_state, ticker):
        return False, "7C · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "7C", gene_ok=_7c_gene_ok(slices))


def _3e_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _3e_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"3E · cool {mins}m after stop"
    if _3e_open_chop(session_state):
        return False, "3E · skip 9:30–10:00"
    if _3e_used_today(session_state, ticker):
        return False, "3E · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "3E", gene_ok=_3e_gene_ok(slices))


def _6c_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _6c_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"6C · cool {mins}m after stop"
    if _6c_open_chop(session_state):
        return False, "6C · skip 9:30–10:00"
    if _6c_used_today(session_state, ticker):
        return False, "6C · first of day already used"
    _ = last_px
    return _1m_live_fill_now(line, "6C", gene_ok=_6c_gene_ok(slices))


def _5m_spec_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    letter: str,
    skip_until,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _5m_spec_cool_until(session_state, letter, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"{letter} (5M) · cool {mins}m after stop"
    if _rth_before(session_state, skip_until):
        until = skip_until.strftime("%H:%M")
        return False, f"{letter} (5M) · skip 9:30–{until}"
    if _5m_spec_used_today(session_state, letter, ticker):
        return False, f"{letter} (5M) · first of day already used"
    gene = {
        "1A": _1a_5m_gene_ok,
        "1B": _1b_5m_gene_ok,
        "5A": _5a_5m_gene_ok,
        "1C": _1c_5m_gene_ok,
        "9A": _9a_5m_gene_ok,
        "5B": _5b_5m_gene_ok,
        "2B": _2b_5m_gene_ok,
        "5C": _5c_5m_gene_ok,
        "8A": _8a_5m_gene_ok,
        "6A": _6a_5m_gene_ok,
        "2C": _2c_5m_gene_ok,
        "2D": _2d_5m_gene_ok,
        "2A": _2a_5m_gene_ok,
        "1D": _1d_5m_gene_ok,
        "4A": _4a_5m_gene_ok,
        "6B": _6b_5m_gene_ok,
        "8B": _8b_5m_gene_ok,
        "3A": _3a_5m_gene_ok,
        "9B": _9b_5m_gene_ok,
    }[letter]
    _ = last_px
    return _1m_live_fill_now(
        line, f"{letter} (5M)", gene_ok=gene(slices), wait="wait suited tape"
    )


def _15m_spec_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    letter: str,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _15m_spec_cool_until(session_state, letter, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"{letter} (15M) · cool {mins}m after stop"
    if _15m_spec_used_today(session_state, letter, ticker):
        return False, f"{letter} (15M) · first of day already used"
    if letter == "1A":
        ok = _1a_15m_gene_ok(slices)
    else:
        ok = _15m_origin_gene_ok(slices)
    _ = last_px
    return _1m_live_fill_now(
        line, f"{letter} (15M)", gene_ok=ok, wait="wait suited tape"
    )


def _1a_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    ticker = str(line.get("ticker") or "").upper()
    cool = _1a_cool_until(session_state, ticker)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"1A · cool {mins}m after stop"
    if _rth_before(session_state, ONE_A_SKIP_UNTIL):
        return False, "1A · skip 9:30–9:45"
    if _1a_used_today(session_state, ticker):
        return False, "1A · first of day already used"
    handle = str(line.get("1a_handle") or "") or _1a_classify(slices)
    if not handle:
        return False, "1A · wait suited tape"
    line["1a_handle"] = handle
    if handle in ("trip", "mild"):
        if _rth_before(session_state, ONE_A_LONG_PAUSE):
            return False, "1A · skip 9:30–10:00"
    elif _rth_before(session_state, ONE_A_SKIP_UNTIL):
        return False, "1A · skip 9:30–9:45"
    tag = {"trip": "trip runner", "mild": "mild 8%", "violent": "violent 12%"}.get(
        handle, "1A"
    )
    _ = last_px
    return _1m_live_fill_now(line, f"1A · {tag}")


def _ph_entry_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    tf: str,
    strategy: str,
    layout_id: str,
    structural: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    """Shared Handle for letters that are not 5B / 2A / 1A / 2D / 2B / 2C / 3A / 4A / 3B / 5A / 7A / 3C / 4D / 4B / 6A / 4C. Detect is still ≥85% same TF."""
    ticker = str(line.get("ticker") or "").upper()
    tf_n = room3_recipes.normalize_tf(tf)
    cool = _ph_cool_until(session_state, ticker, strategy)
    now = _5b_now(session_state)
    if cool is not None and now < cool:
        mins = max(1, int((cool - now).total_seconds() // 60))
        return False, f"{strategy} · cool {mins}m after stop"
    if tf_n in ("1m", "5m") and _ph_open_chop(session_state):
        return False, f"{strategy} · skip 9:30–9:45"
    if _ph_used_today(session_state, ticker, strategy):
        return False, f"{strategy} · first of day already used"
    if tf_n == "1m":
        _ = (slices, last_px, layout_id, structural)
        return _1m_live_fill_now(line, strategy)
    last = slices[-1] if slices else {}
    last_c = float(last.get("c") or last_px)
    last_l = float(last.get("l") or last_c)
    last_o = float(last.get("o") or last_c)
    prior = slices[-2] if len(slices) >= 2 else last
    prior_h = float(prior.get("h") or prior.get("c") or 0)
    if not line.get("family_armed_px"):
        line["family_armed_px"] = last_px
        line["family_armed_high"] = float(last.get("h") or last_px)
        line["trigger_phase"] = "wait_dip"
    if _entry_is_late(line, last_px, structural):
        line["entry_skipped_late"] = True
        line["trigger_phase"] = "skipped"
        return False, "late · move already gone · skip"
    armed_px = float(line.get("family_armed_px") or last_px)
    phase = str(line.get("trigger_phase") or "wait_dip")
    if tf_n == "15m":
        dip_frac = PH_DIP_FRAC_15M
    elif tf_n == "5m":
        dip_frac = PH_DIP_FRAC_5M
    else:
        dip_frac = PH_DIP_FRAC_1M
    if phase == "ready":
        return True, f"{strategy} · dip-reclaim · enter now"
    if phase == "wait_dip":
        if last_l <= armed_px * (1.0 - dip_frac) or last_c < armed_px:
            line["trigger_phase"] = "wait_reclaim"
            line["pullback_low"] = last_l
            return False, f"{strategy} · waiting pullback"
        return False, f"{strategy} · waiting first pullback"
    if phase == "wait_reclaim":
        pb = min(float(line.get("pullback_low") or last_l), last_l)
        line["pullback_low"] = pb
        if tf_n in ("5m", "15m"):
            if last_c > pb and last_c >= armed_px * 0.997:
                line["trigger_phase"] = "ready"
                return True, f"{strategy} · {tf_n} hold after pullback"
            return False, f"{strategy} · waiting hold after dip"
        green = last_c > last_o
        if not green:
            return False, f"{strategy} · waiting green reclaim"
        if last_c > pb and (prior_h <= 0 or last_c >= prior_h):
            line["trigger_phase"] = "ready"
            return True, f"{strategy} · dip-reclaim · enter now"
        return False, f"{strategy} · waiting reclaim after dip"
    return False, f"{strategy} · waiting trigger"


def _entry_trigger_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    tf: str,
    strategy: str,
    layout_id: str,
    structural: float,
    session_state: Any = None,
) -> tuple[bool, str]:
    """
    ≥85% = family. Fill = letter style, else TF fallback.
    Late (half the expected move already in) = skip this shot.
    """
    if line.get("entry_skipped_late"):
        return False, "late · skipped · wait next pattern"
    if last_px <= 0:
        return False, "no last print"
    if room3_recipes.normalize_tf(tf) == "1m" and _1m_name_shots_blocked(
        session_state, str(line.get("ticker") or "")
    ):
        return False, "1m · max 3 shots this name today"
    if _is_5b_1m(strategy, tf):
        return _5b_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_2a_1m(strategy, tf):
        return _2a_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_2b_1m(strategy, tf):
        return _2b_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_2c_1m(strategy, tf):
        return _2c_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_3a_1m(strategy, tf):
        return _3a_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_1a_1m(strategy, tf):
        return _1a_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_2d_1m(strategy, tf):
        return _2d_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_4a_1m(strategy, tf):
        return _4a_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_3b_1m(strategy, tf):
        return _3b_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_5a_1m(strategy, tf):
        return _5a_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_7a_1m(strategy, tf):
        return _7a_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_3c_1m(strategy, tf):
        return _3c_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_4d_1m(strategy, tf):
        return _4d_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_4b_1m(strategy, tf):
        return _4b_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_6a_1m(strategy, tf):
        return _6a_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_4c_1m(strategy, tf):
        return _4c_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_4e_1m(strategy, tf):
        return _4e_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_6b_1m(strategy, tf):
        return _6b_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_3d_1m(strategy, tf):
        return _3d_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_7b_1m(strategy, tf):
        return _7b_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_3g_1m(strategy, tf):
        return _3g_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_3f_1m(strategy, tf):
        return _3f_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_8a_1m(strategy, tf):
        return _8a_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_7c_1m(strategy, tf):
        return _7c_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_3e_1m(strategy, tf):
        return _3e_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_6c_1m(strategy, tf):
        return _6c_entry_ready(line, slices, last_px=last_px, session_state=session_state)
    if _is_1a_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="1A",
            skip_until=ONE_A_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_1b_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="1B",
            skip_until=ONE_B_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_5a_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="5A",
            skip_until=FIVE_A_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_1c_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="1C",
            skip_until=ONE_C_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_9a_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="9A",
            skip_until=NINE_A_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_5b_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="5B",
            skip_until=FIVE_B_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_2b_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="2B",
            skip_until=TWO_B_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_5c_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="5C",
            skip_until=FIVE_C_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_8a_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="8A",
            skip_until=EIGHT_A_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_6a_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="6A",
            skip_until=SIX_A_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_2c_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="2C",
            skip_until=TWO_C_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_2d_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="2D",
            skip_until=TWO_D_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_2a_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="2A",
            skip_until=TWO_A_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_1d_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="1D",
            skip_until=ONE_D_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_4a_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="4A",
            skip_until=FOUR_A_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_6b_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="6B",
            skip_until=SIX_B_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_8b_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="8B",
            skip_until=EIGHT_B_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_3a_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="3A",
            skip_until=THREE_A_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_9b_5m(strategy, tf):
        return _5m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="9B",
            skip_until=NINE_B_5M_SKIP_UNTIL,
            session_state=session_state,
        )
    if _is_1a_15m(strategy, tf):
        return _15m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter="1A",
            session_state=session_state,
        )
    origin_15m = _is_15m_origin_letter(strategy, tf)
    if origin_15m:
        return _15m_spec_entry_ready(
            line,
            slices,
            last_px=last_px,
            letter=origin_15m,
            session_state=session_state,
        )
    return _ph_entry_ready(
        line,
        slices,
        last_px=last_px,
        tf=tf,
        strategy=strategy,
        layout_id=layout_id,
        structural=structural,
        session_state=session_state,
    )


def _ss_get(session_state: Any, key: str, default: Any = None) -> Any:
    if session_state is None:
        return default
    try:
        return session_state.get(key, default)
    except Exception:
        return default


def _tf_layout_counts(layouts: list[dict[str, Any]] | None) -> dict[str, int]:
    counts = {"1m": 0, "5m": 0, "15m": 0}
    seen: set[tuple[str, str, str]] = set()
    for entry in layouts or []:
        tf = _layout_dna_tf(entry)
        if tf not in counts:
            continue
        key = (
            str(entry.get("layout_id") or entry.get("layout") or "").strip(),
            str(entry.get("strategy") or "").strip(),
            tf,
        )
        if key in seen:
            continue
        seen.add(key)
        counts[tf] += 1
    return counts


def project_tf_counts(
    layouts: list[dict[str, Any]] | None,
    n_names: int | None = None,
) -> dict[str, int]:
    """
    Expected fills per TF today from layout richness + how many names are on the belt.
    sqrt(recipe_count / prior) so a fat 15m library does not claim 20 fills.
    Empty DNA uses the prior (3 / 6 / 5) until layouts hydrate.
    """
    n = _tf_layout_counts(layouts)
    name_scale = 1.0
    try:
        nn = int(n_names or 0)
    except (TypeError, ValueError):
        nn = 0
    if nn > 0:
        name_scale = min(1.5, max(0.75, math.sqrt(nn / 8.0)))
    out: dict[str, int] = {}
    for tf in ("15m", "5m", "1m"):
        prior = int(TF_PROJECTED_PRIOR[tf])
        cap = int(TF_PROJECTED_CAP[tf])
        layouts_n = int(n.get(tf) or 0)
        if layouts_n <= 0:
            est = prior
        else:
            richness = math.sqrt(max(1.0, layouts_n) / max(1.0, prior))
            est = int(round(prior * richness))
        out[tf] = max(1, min(cap, int(round(est * name_scale))))
    return out


def _row_notional(row: dict[str, Any]) -> float:
    try:
        qty = abs(float(row.get("qty") or 0))
        px = abs(float(row.get("last_price") or row.get("entry_price") or 0))
        if qty > 0 and px > 0:
            return qty * px
        return abs(float(row.get("position_usd") or row.get("notional") or 0))
    except (TypeError, ValueError):
        return 0.0


def _tf_live_usage(session_state: Any, *, exclude_ticker: str = "") -> dict[str, Any]:
    """Open + committed dollars and live count per TF (money still in the trade)."""
    spent = {"1m": 0.0, "5m": 0.0, "15m": 0.0}
    live = {"1m": 0, "5m": 0, "15m": 0}
    counted: set[str] = set()
    skip = str(exclude_ticker or "").upper()
    for row in list(_ss_get(session_state, "room3_open_positions") or []):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if skip and ticker == skip:
            continue
        tf = _normalize_watch_tf(row.get("timeframe") or "")
        usd = _row_notional(row)
        if tf not in spent or usd <= 0:
            continue
        spent[tf] += usd
        live[tf] += 1
        if ticker:
            counted.add(ticker)
    book = _ss_get(session_state, "room3_watch_book") or {}
    for line in (book.get("lines") or {}).values():
        ticker = str(line.get("ticker") or "").upper()
        if skip and ticker == skip:
            continue
        tf = _normalize_watch_tf(line.get("timeframe") or "")
        if tf not in spent:
            continue
        if str(line.get("state") or "") not in ("in", "committed"):
            continue
        if ticker and ticker in counted:
            continue
        usd = 0.0
        sig = line.get("entry_signal")
        if isinstance(sig, dict):
            usd = float(sig.get("notional") or 0)
        if usd <= 0:
            usd = float(line.get("size_usd") or 0)
        if usd <= 0:
            continue
        spent[tf] += usd
        live[tf] += 1
        if ticker:
            counted.add(ticker)
    return {"spent": spent, "live": live}


def _heat(live: int, projected: int) -> float:
    return float(live) / float(max(1, projected))


def _idle_cash(
    remaining: dict[str, float],
    live: dict[str, int],
    projected: dict[str, int],
    *,
    taker: str,
) -> float:
    """
    Cash sitting in buckets that are not hot. A hot book (live ≥ projected)
    keeps its leftover for its own extras; a quiet book can donate.
    """
    idle = 0.0
    for tf, left in remaining.items():
        if tf == taker:
            continue
        donor_live = int(live.get(tf) or 0)
        donor_heat = _heat(donor_live, int(projected.get(tf) or 1))
        # Quiet / empty books donate. Keep leftover only if this TF is actually printing.
        if donor_live > 0 and donor_heat >= 0.5:
            continue
        idle += max(0.0, float(left or 0))
    return idle


def _claim_cash(session_state: Any, usd: float) -> None:
    if session_state is None or usd <= 0:
        return
    try:
        cur = float(session_state.get("room3_cash_claimed") or 0)
        session_state["room3_cash_claimed"] = cur + float(usd)
    except Exception:
        pass


def _layouts_from_session(session_state: Any) -> list[dict[str, Any]]:
    cache = _ss_get(session_state, "room3_repertoire_cache") or {}
    layouts = list(cache.get("layouts") or []) if isinstance(cache, dict) else []
    if layouts:
        return layouts
    try:
        import room3_bridge

        return list((room3_bridge.matrix_repertoire(session_state) or {}).get("layouts") or [])
    except Exception:
        return []


def _belt_name_count(session_state: Any) -> int:
    book = _ss_get(session_state, "room3_watch_book") or {}
    try:
        n = len(list(book.get("universe") or []))
        if n:
            return n
    except Exception:
        pass
    try:
        return len(list(_ss_get(session_state, "room3_filter_universe") or []))
    except Exception:
        return 0


def tf_budget_snapshot(session_state: Any | None = None) -> dict[str, Any]:
    tradable = 0.0
    try:
        tradable = float(_ss_get(session_state, "room3_tradable_today") or 0)
    except (TypeError, ValueError):
        tradable = 0.0
    layouts = _layouts_from_session(session_state)
    projected = project_tf_counts(layouts, n_names=_belt_name_count(session_state))
    usage = (
        _tf_live_usage(session_state)
        if session_state is not None
        else {"spent": {"1m": 0.0, "5m": 0.0, "15m": 0.0}, "live": {"1m": 0, "5m": 0, "15m": 0}}
    )
    spent = usage["spent"]
    live = usage["live"]
    buckets = {tf: tradable * TF_BUCKET_FRAC[tf] for tf in ("15m", "5m", "1m")}
    remaining = {tf: max(0.0, buckets[tf] - float(spent.get(tf) or 0)) for tf in buckets}
    slots = {tf: (buckets[tf] / float(projected[tf])) if projected[tf] else 0.0 for tf in buckets}
    layout_n = _tf_layout_counts(layouts)
    rows = []
    for tf in ("15m", "5m", "1m"):
        rows.append(
            {
                "TF": tf,
                "Bucket %": f"{TF_BUCKET_FRAC[tf]:.0%}",
                "Bucket $": round(buckets[tf], 2),
                "Projected": projected[tf],
                "Live": int(live.get(tf) or 0),
                "In use $": round(float(spent.get(tf) or 0), 2),
                "Left $": round(remaining[tf], 2),
                "Full-match slot $": round(slots[tf], 2),
                "Layouts": int(layout_n.get(tf) or 0),
                "Heat": (
                    "hot"
                    if _heat(int(live.get(tf) or 0), int(projected.get(tf) or 1)) >= 1.0
                    else (
                        "on pace"
                        if _heat(int(live.get(tf) or 0), int(projected.get(tf) or 1)) >= 0.5
                        else "quiet"
                    )
                ),
            }
        )
    return {
        "tradable": tradable,
        "projected": projected,
        "buckets": buckets,
        "spent": spent,
        "live": live,
        "remaining": remaining,
        "slots": slots,
        "layout_counts": layout_n,
        "rows": rows,
        "dna_empty": sum(layout_n.values()) <= 0,
    }


def _match_size_scale(match_pct: float) -> float:
    """85% (entry floor) → 55% of that TF's slot; 100% → full slot."""
    at_floor = 0.55
    try:
        at_floor = float(SIZE_AT_THRESHOLD)
    except (NameError, TypeError, ValueError):
        at_floor = 0.55
    pct = max(0.0, min(100.0, float(match_pct or 0)))
    floor = float(MATCH_THRESHOLD_PCT)
    if pct <= 0:
        return 0.0
    if pct < floor:
        return at_floor * (pct / floor)
    span = max(1.0, 100.0 - floor)
    return at_floor + (1.0 - at_floor) * ((pct - floor) / span)


def _distinctiveness(best_cosine: float, second_cosine: float) -> float:
    """
    Unique hit vs wallpaper: if runner-up is almost as close, this isn't a
    distinctive strategy read — pay it less. Gap of ~10% cosine → full size.
    """
    gap = max(0.0, float(best_cosine or 0) - float(second_cosine or 0))
    if float(second_cosine or 0) <= 0:
        return 1.0
    return max(0.50, min(1.0, 0.50 + gap / 0.10 * 0.50))


def stamp_line_size(
    line: dict[str, Any],
    session_state: Any,
    *,
    repertoire: dict[str, Any] | None = None,
    last_px: float | None = None,
    second_cosine: float | None = None,
    best_cosine: float | None = None,
) -> None:
    """Size $ follows Trading today now — do not wait for a 5m/15m tape pulse."""
    slices = list(line.get("slices") or [])
    if last_px is None:
        last_px = float(slices[-1].get("c") or 0) if slices else 0.0
    tf = str(line.get("timeframe") or "1m")
    ticker = str(line.get("ticker") or "").upper()
    exclude = ticker if str(line.get("state") or "") in ("in", "committed") else ""
    raw_match = float(line.get("match_pct") or 0)
    preview_match = (
        float(MATCH_THRESHOLD_PCT)
        if 0 < raw_match < MATCH_THRESHOLD_PCT
        else raw_match
    )
    layouts = list((repertoire or {}).get("layouts") or []) or _layouts_from_session(session_state)
    cos = float(best_cosine if best_cosine is not None else (raw_match / 100.0))
    preview = compute_entry_plan(
        price=float(last_px or 0),
        timeframe=tf,
        match_pct=preview_match,
        session_state=session_state,
        second_cosine=float(second_cosine if second_cosine is not None else line.get("second_cosine") or 0),
        best_cosine=cos,
        layouts=layouts,
        exclude_ticker=exclude,
    )
    line["size_usd"] = float(preview.get("notional") or 0)
    line["size_qty"] = float(preview.get("qty") or 0)
    line["size_note"] = str(preview.get("note") or "")


def compute_entry_plan(
    *,
    price: float,
    timeframe: str,
    match_pct: float,
    session_state: Any,
    second_cosine: float = 0.0,
    best_cosine: float | None = None,
    layouts: list[dict[str, Any]] | None = None,
    exclude_ticker: str = "",
) -> dict[str, Any]:
    """
    Size from TF bucket → projected count slot → match → uniqueness → borrow.
    Never more than remaining Trading-today cash.
    """
    tf = _normalize_watch_tf(timeframe)
    if tf not in TF_BUCKET_FRAC:
        tf = "5m"
    match_scale = _match_size_scale(match_pct)
    best = float(best_cosine if best_cosine is not None else (float(match_pct or 0) / 100.0))
    distinct = _distinctiveness(best, second_cosine)
    try:
        tradable = float(session_state.get("room3_tradable_today") or 0)
    except (TypeError, ValueError):
        tradable = 0.0
    if layouts is None:
        layouts = _layouts_from_session(session_state)
    projected = project_tf_counts(layouts, n_names=_belt_name_count(session_state))
    usage = _tf_live_usage(session_state, exclude_ticker=exclude_ticker)
    spent = usage["spent"]
    live = usage["live"]
    buckets = {k: tradable * v for k, v in TF_BUCKET_FRAC.items()}
    remaining = {k: max(0.0, buckets[k] - float(spent.get(k) or 0)) for k in buckets}
    leftover_other = _idle_cash(remaining, live, projected, taker=tf)
    try:
        claimed = float(session_state.get("room3_cash_claimed") or 0)
    except (TypeError, ValueError):
        claimed = 0.0
    leftover_other = max(0.0, leftover_other - claimed)
    remaining_slots = max(1, int(projected[tf]) - int(live.get(tf) or 0))
    full_slot = buckets[tf] / float(max(1, projected[tf]))
    if remaining[tf] > 1e-6:
        slot = remaining[tf] / float(remaining_slots)
    else:
        slot = full_slot
    want = slot * match_scale * distinct
    from_own = min(want, remaining[tf])
    borrowed = 0.0
    taker_hot = int(live.get(tf) or 0) >= int(projected[tf])
    if (taker_hot or from_own + 1e-6 < want) and leftover_other > 0:
        borrowed = min(max(0.0, want - from_own), leftover_other)
    raw = from_own + borrowed
    deployed = 0.0
    try:
        import room3_engine

        deployed = room3_engine.deployed_notional(session_state.get("room3_open_positions"))
    except Exception:
        pass
    room = max(0.0, tradable - deployed - claimed)
    notional = min(raw, room)
    qty = 0.0
    if price > 0 and notional >= price:
        qty = math.floor(notional / price)
        notional = qty * price
    borrow_bit = f" · borrowed ${borrowed:,.0f}" if borrowed > 0 else ""
    note = (
        f"{tf} bucket {TF_BUCKET_FRAC[tf]:.0%} · slot ${slot:,.0f} of "
        f"{projected[tf]} projected · match {match_scale:.0%} · "
        f"unique {distinct:.0%}{borrow_bit} · ${notional:,.0f}"
    )
    return {
        "qty": qty,
        "notional": round(notional, 2),
        "tf_cap": TF_BUCKET_FRAC[tf],
        "match_scale": match_scale,
        "distinct": distinct,
        "slot": round(slot, 2),
        "projected": projected[tf],
        "borrowed": round(borrowed, 2),
        "note": note,
        "idle_cash": round(leftover_other, 2),
        "taker_hot": taker_hot,
    }


def _compute_entry_qty(
    *,
    price: float,
    session_state: Any,
    timeframe: str = "5m",
    match_pct: float = 0.0,
    second_cosine: float = 0.0,
    best_cosine: float | None = None,
    max_positions: int = 5,
    layouts: list[dict[str, Any]] | None = None,
    exclude_ticker: str = "",
) -> tuple[float, float]:
    """Return (qty, notional). max_positions kept for call-site compat; unused."""
    _ = max_positions
    plan = compute_entry_plan(
        price=price,
        timeframe=timeframe,
        match_pct=match_pct,
        session_state=session_state,
        second_cosine=second_cosine,
        best_cosine=best_cosine,
        layouts=layouts,
        exclude_ticker=exclude_ticker,
    )
    return float(plan["qty"]), float(plan["notional"])


def compute_scale_in_plan(
    *,
    price: float,
    timeframe: str,
    match_pct: float,
    session_state: Any,
    second_cosine: float = 0.0,
    best_cosine: float | None = None,
    layouts: list[dict[str, Any]] | None = None,
    exclude_ticker: str = "",
) -> dict[str, Any]:
    """
    Add to a live winner using idle leftover from buckets that are not hot.
    Capped at one full-match slot. Does not spend a hot book's leftover.
    """
    plan = compute_entry_plan(
        price=price,
        timeframe=timeframe,
        match_pct=match_pct,
        session_state=session_state,
        second_cosine=second_cosine,
        best_cosine=best_cosine,
        layouts=layouts,
        exclude_ticker=exclude_ticker,
    )
    idle = float(plan.get("idle_cash") or 0)
    slot = float(plan.get("slot") or 0)
    add = min(idle, slot)
    qty = 0.0
    if price > 0 and add >= price:
        qty = math.floor(add / price)
        add = qty * price
    else:
        add = 0.0
        qty = 0.0
    return {
        **plan,
        "qty": qty,
        "notional": round(add, 2),
        "borrowed": round(add, 2),
        "note": f"add ${add:,.0f} from idle leftover · {plan.get('note') or ''}",
    }


def maybe_queue_matrix_signals(
    book: dict[str, Any],
    line: dict[str, Any],
    repertoire: dict[str, Any],
    session_state: Any,
    *,
    engine_armed: bool = False,
    entries_allowed: bool = True,
) -> None:
    """
    Stamp entry_signal or exit_signal on a line when DNA rules pass.
    One Alpaca pile per ticker. App lots are per letter; a second letter adds.
    """
    import room3_watcher

    match = score_line_against_repertoire(line, repertoire)
    new_pct = int(match.get("spatial_match_pct") or 0)
    prior_pct = int(line.get("match_pct") or 0)
    # Empty tape (belt add / remount) must not blank Kind / Match% on names that already scored.
    if not (line.get("slices") or []) and prior_pct > 0 and new_pct <= 0:
        return
    line["match_pct"] = new_pct
    layout_id = str(match.get("nearest_layout_id") or "—")
    line["nearest_layout"] = layout_id
    tf = str(line.get("timeframe") or "1m")
    nearest_strat = str(match.get("nearest_strategy") or "").strip()
    if (
        (not nearest_strat or nearest_strat in ("—", "-", "matrix"))
        and layout_id not in PLACEHOLDER_LAYOUTS
    ):
        nearest_strat = strategy_for_layout(layout_id, repertoire, timeframe=tf)
    if nearest_strat and not room3_recipes.strategy_tf_agrees(nearest_strat, tf):
        nearest_strat = "—"
        # Keep Match% / layout. Wrong-TF letter must not fire; do not blank the score.
    if room3_recipes.is_purgatory_letter(layout_id, nearest_strat):
        layout_id = "—"
        nearest_strat = "—"
        line["nearest_layout"] = "—"
        line["match_pct"] = 0
        match = {**match, "nearest_layout_id": "—", "nearest_strategy": "", "spatial_match_pct": 0, "ranked": []}
    line["nearest_strategy"] = nearest_strat or "—"
    line["score"] = float(match.get("display_score") or 0)
    line["second_cosine"] = float(match.get("second_cosine") or 0)

    ticker = str(line.get("ticker") or "").upper()
    slices = list(line.get("slices") or [])
    last_px = float(slices[-1].get("c") or 0) if slices else 0.0
    _sync_hot_children(
        line,
        list(match.get("ranked") or []),
        session_state,
        ticker,
        tf,
    )
    if _off_belt(line, book):
        line["children"] = []
    stamp_line_size(
        line,
        session_state,
        repertoire=repertoire,
        last_px=last_px,
        second_cosine=float(match.get("second_cosine") or 0),
        best_cosine=float(match.get("cosine_similarity") or 0),
    )

    layouts = list(repertoire.get("layouts") or [])
    if not layouts or not engine_armed:
        return

    if line.get("state") == "in":
        tf_lots = room3_lots.open_lots(session_state, ticker, tf=tf)
        children_by = {
            str(c.get("letter") or ""): c
            for c in (line.get("children") or [])
            if isinstance(c, dict)
        }
        if tf_lots:
            for lot in tf_lots:
                letter = str(lot.get("letter") or "")
                child = children_by.get(letter) or {}
                lot_match = int(child.get("match_pct") or line.get("match_pct") or 0)
                exit_reason = _lot_should_exit(
                    lot,
                    cur_match=lot_match,
                    last_px=last_px,
                    patience=True,
                    bar=slices[-1] if slices else None,
                    session_state=session_state,
                )
                if not exit_reason or line.get("exit_signal"):
                    if not exit_reason and lot_match < EXIT_MATCH_FLOOR_PCT:
                        line["patience"] = True
                        line["patience_note"] = (
                            f"holding {letter} · match {lot_match}%"
                        )
                    continue
                qty = abs(float(lot.get("qty") or 0))
                if qty <= 0:
                    qty = _open_qty(session_state, ticker)
                if qty <= 0:
                    continue
                strat = str(lot.get("strategy") or line.get("entry_strategy") or "matrix")
                room3_watcher.queue_exit_signal(
                    book,
                    ticker,
                    tf,
                    side="sell",
                    qty=qty,
                    strategy=strat,
                    layout_id=str(lot.get("layout_id") or line.get("entry_layout") or ""),
                )
                line["last_exit_reason"] = exit_reason
                line["patience"] = False
                es = line.get("exit_signal")
                if isinstance(es, dict):
                    es["ref_price"] = last_px
                    es["lot_id"] = str(lot.get("id") or "")
                    es["letter"] = letter
                if str(exit_reason).startswith("stop") and _5b_lot_exit(lot):
                    _pack_mark_stop_cool(session_state, ticker, lot)
                elif _is_2d_1m(
                    str(lot.get("strategy") or lot.get("letter") or ""),
                    str(lot.get("tf") or lot.get("timeframe") or "1m"),
                ) or str(lot.get("exit_style") or "") == TWO_D_EXIT_STYLE:
                    _2d_mark_used(session_state, ticker)
                return
        else:
            entry_px = float(line.get("entry_price") or last_px or 0)
            entry_match = int(line.get("entry_match_pct") or MATCH_THRESHOLD_PCT)
            cur_match = int(line.get("match_pct") or 0)
            structural = float(line.get("entry_structural_move_pct") or 0.0)
            dummy = {
                "entry_px": entry_px,
                "entry_match_pct": entry_match,
                "structural_move_pct": structural,
                "strategy": str(line.get("entry_strategy") or ""),
                "letter": str(line.get("entry_strategy") or ""),
                "tf": tf,
                "exit_style": line.get("exit_style"),
                "exit_r_frac": line.get("exit_r_frac"),
                "exit_stop_px": line.get("exit_stop_px"),
                "exit_tgt_px": line.get("exit_tgt_px"),
                "exit_high_px": line.get("exit_high_px"),
                "exit_runner_on": line.get("exit_runner_on"),
                "1a_handle": line.get("1a_handle"),
                "entry_ts": line.get("entry_ts"),
            }
            exit_reason = _lot_should_exit(
                dummy,
                cur_match=cur_match,
                last_px=last_px,
                patience=True,
                bar=slices[-1] if slices else None,
                session_state=session_state,
            )
            if exit_reason and not line.get("exit_signal"):
                qty = _open_qty(session_state, ticker)
                if qty <= 0:
                    qty = float(line.get("entry_qty") or 0)
                if qty <= 0:
                    return
                strat = str(line.get("entry_strategy") or "matrix")
                room3_watcher.queue_exit_signal(
                    book,
                    ticker,
                    tf,
                    side="sell",
                    qty=qty,
                    strategy=strat,
                    layout_id=str(line.get("entry_layout") or ""),
                )
                line["last_exit_reason"] = exit_reason
                line["patience"] = False
                es = line.get("exit_signal")
                if isinstance(es, dict):
                    es["ref_price"] = last_px
                if str(exit_reason).startswith("stop") and _5b_lot_exit(dummy):
                    _pack_mark_stop_cool(session_state, ticker, dummy)
                elif _is_2d_1m(
                    str(dummy.get("strategy") or dummy.get("letter") or ""),
                    str(dummy.get("tf") or dummy.get("timeframe") or "1m"),
                ) or str(dummy.get("exit_style") or "") == TWO_D_EXIT_STYLE:
                    _2d_mark_used(session_state, ticker)
                return

        entry_px = float(line.get("entry_price") or last_px or 0)
        cur_match = int(line.get("match_pct") or 0)
        structural = float(line.get("entry_structural_move_pct") or 0.0)
        pnl_pct = ((last_px - entry_px) / entry_px * 100.0) if entry_px > 0 and last_px > 0 else 0.0
        if (
            entries_allowed
            and not _off_belt(line, book)
            and not _approaching_day_close()
            and tf == "15m"
            and not line.get("entry_signal")
            and int(line.get("scale_ins") or 0) < SCALE_IN_MAX
            and _15m_can_open_lot(session_state, ticker, scale_in=True)
            and cur_match >= MATCH_THRESHOLD_PCT
            and structural > 0
            and pnl_pct > 0
            and pnl_pct < structural * SCALE_IN_TARGET_FRAC
        ):
            add = compute_scale_in_plan(
                price=last_px,
                timeframe=tf,
                match_pct=cur_match,
                session_state=session_state,
                second_cosine=float(match.get("second_cosine") or 0),
                best_cosine=float(match.get("cosine_similarity") or 0),
                layouts=layouts,
                exclude_ticker=ticker,
            )
            add_qty = float(add.get("qty") or 0)
            add_usd = float(add.get("notional") or 0)
            if add_qty >= 1 and add_usd > 0:
                strat = str(line.get("entry_strategy") or "matrix")
                room3_watcher.queue_entry_signal(
                    book,
                    ticker,
                    tf,
                    side="buy",
                    qty=add_qty,
                    strategy=strat,
                    keep_in=True,
                    scale_in=True,
                    layout_id=str(line.get("entry_layout") or ""),
                )
                _claim_cash(session_state, add_usd)
                line["scale_ins"] = int(line.get("scale_ins") or 0) + 1
                line["patience"] = True
                line["patience_note"] = (
                    f"add ${add_usd:,.0f} · match {cur_match}% · "
                    f"move {pnl_pct:.1f}% of ~{structural:.1f}%"
                )
                sig = (book.get("lines") or {}).get(room3_watcher.line_key(ticker, tf)) or line
                if isinstance(sig.get("entry_signal"), dict):
                    sig["entry_signal"]["notional"] = add_usd
                    sig["entry_signal"]["ref_price"] = last_px
                    sig["entry_signal"]["scale_in"] = True
                    sig["entry_signal"]["order_style"] = "limit"
                    sig["entry_signal"]["letter"] = room3_lots.letter_token(
                        str(line.get("entry_layout") or ""), strat
                    )
        if (
            entries_allowed
            and not _off_belt(line, book)
            and not _approaching_day_close()
            and not line.get("entry_signal")
            and not line.get("exit_signal")
            and not line.get("order_pending")
        ):
            _try_queue_child_entry(
                book,
                line,
                session_state=session_state,
                ticker=ticker,
                tf=tf,
                last_px=last_px,
                slices=slices,
                layouts=layouts,
                match=match,
            )
        return

    if not entries_allowed:
        return
    if _off_belt(line, book):
        line["patience"] = True
        line["patience_note"] = "leftover · exit only · no new buy"
        line["children"] = []
        return
    if line.get("entry_signal"):
        return
    if line.get("order_pending") or line.get("state") == "committed":
        line["patience"] = True
        line["patience_note"] = "order working · wait fill"
        return
    if line.get("state") not in ("watching", "committed"):
        return
    if not match.get("vector_ready"):
        if not line.get("children"):
            line["patience"] = False
            line.pop("patience_note", None)
        return
    queued = _try_queue_child_entry(
        book,
        line,
        session_state=session_state,
        ticker=ticker,
        tf=tf,
        last_px=last_px,
        slices=slices,
        layouts=layouts,
        match=match,
    )
    if queued:
        return
    if line.get("children"):
        line["patience"] = True
        notes = [
            str(c.get("patience_note") or "")
            for c in line["children"]
            if str(c.get("patience_note") or "").strip()
        ]
        line["patience_note"] = notes[0] if notes else "scanning live letters"
        return
    cur_match = int(match.get("spatial_match_pct") or 0)
    if cur_match < WARMING_MATCH_PCT:
        _reset_entry_trigger(line)
        line["patience"] = False
        line.pop("patience_note", None)
    else:
        line["patience"] = True
        line["patience_note"] = (
            f"warming {cur_match}% · need ≥{MATCH_THRESHOLD_PCT}%"
        )
