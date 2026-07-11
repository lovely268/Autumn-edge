# Aurum Edge — TEST/EXCLUDED LEDGER

All trades below are verification tests excluded from official evaluation stats.
Broker balance is the single source of truth (§1.1). Official bot state is /reset_state clean.

| Date | Event | P&L | OrderIds | Source |
|---|---|---|---|---|
| Mon Jul 7 | MGC test fills (26 × 21.2 pts × $10) | +$5,512.00 | ... | Raw curl x3 |
| Wed Jul 8 | MES verification fills @ ~7538 | -$427.50 | 568774740156... | Bot path x2 |
| Thu Jul 9 | Orphan 6-lot MES @ 7545.25 + flatten + fees | -$705.90 | ...249 | Overnight residue |
| **Thu Jul 9** | **MNQ 1-lot: SHORT @ 29,920.75 → BUY @ ~29,910 (+$10.70)** | **+$10.70** | **568774740288 / 568774740310** | **Plan v2: direct STA** |
| **Net test P&L** | | **+$4,777.00** | | Broker $54,777 − $50K ✓ |

**Cross-check:** Broker DEMO8306103 balance $54,777.00 − $50,000 baseline = **$4,777.00** ✓ exact.