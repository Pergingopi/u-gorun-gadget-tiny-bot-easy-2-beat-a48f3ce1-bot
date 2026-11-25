# u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1-bot

[![make.fun · u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1.svg)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1?utm_source=github&utm_medium=readme&utm_campaign=u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)
[![rank](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/Pergingopi/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1-bot/rank.svg)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)
[![reward](https://make.fun/badge/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1/Pergingopi/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1-bot/reward.svg)](https://make.fun/bounty/u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1?utm_source=github&utm_medium=readme&utm_campaign=u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1)

Tiny SOL Trend Bot — a deterministic Python paper-trading bot for hourly Solana bars. It reads the harness's 1h bars for SOL, JITOSOL, WETH, RAY, POPCAT, FARTCOIN and WIF, and decides when to hold each one and when to sit in USDC. Long only, no outside data, no network, standard library only.

## Strategy

Per symbol, over its hourly closes:

- **EMA(5) / EMA(12) crossover.** Buy when the fast EMA crosses above the slow one; sell the whole position when the slow EMA crosses back above the fast one.
- **12-bar momentum filter.** A cross-up only counts when the close is above the close 12 bars ago, so whipsaw crosses in a sideways market are skipped.
- **Take-profit +30% / stop-loss −8%.** A position is also sold whole when it is worth 1.30× its cost or 0.92× of it. (Neither triggered on the dev window — exits there were all cross-driven; they are live protection for the final window.)
- **Sizing.** One equal stake per symbol: equity / 7, capped by the harness weight cap (25% of equity) and by cash. Sells go first, then buys in universe order, at most the harness order cap per bar, 1% max slippage.

The edge over buy-and-hold is timing, not leverage: the bot rides symbols that trend up and sits in USDC while a symbol trends down, so it keeps most of the upside in a rising market and much smaller losses in a falling one.

## Run it

```sh
python3 main.py
```

The bot speaks `agent-fun/bars-replay/v1` on stdin/stdout (JSON lines: `hello`, `batch`, `done` in; one `reply` per batch out). The grader runs it as `python3 -P -s /bot/main.py` with `vendor/makefun_bars.py` (a byte-identical copy of the kit's `sdk/makefun_bars.py`) beside it. Python 3.13, standard library only.

To grade it on the kit's dev data the official way:

```sh
node cli/makefun.mjs grade-local --kit <kit> --bot <this repo> --driver docker
```

## Local replay results

Replayed with a local simulator that re-implements the kit harness (`sim/bars/engine.ts`) exactly — decision checks, fills at the next bar's open with 10 bps fee, 5 bps slippage and constant-product impact against the bar's pool depth, flatten at the end — on the kit's frozen dev dataset (136 hourly bars, 10,000 USDC start). Buy-and-hold is the kit's own baseline, run through the same simulator.

| Window | Bot net PnL | Buy-and-hold | Margin | Trades | Max drawdown |
|---|---|---|---|---|---|
| Full dev, 136 bars | −144.84 USDC (−1.45%) | −869.34 USDC (−8.69%) | **+724.50** | 41 | 2.7% |
| First 72 bars | −48.69 USDC | −686.14 USDC | **+637.45** | 18 | 1.4% |
| Middle 72 bars (32–104) | −171.01 USDC | −17.61 USDC | −153.40 | 25 | 1.8% |
| Last 72 bars (64–136) | −71.85 USDC | −311.77 USDC | **+239.92** | 17 | 1.2% |

Full-window PnL by symbol (USDC): FARTCOIN −41.62, JITOSOL −6.77, POPCAT −36.58, RAY −32.48, SOL −13.60, WETH −8.17, WIF −5.62. Zero rejected orders on the full window. Two runs on the same bars produce byte-identical replies (136/136), so the entry is deterministic as the harness requires.

Guardrails: every 72-bar slice makes 17–25 trades (minimum is 8) and max drawdown stays under 2.7% (maximum is 25%).

## Known limitations

- The dev window is a falling market, so these numbers flatter any timing strategy; the one sideways slice (bars 32–104) is the only one where the bot loses to buy-and-hold (−153.40 USDC), on whipsaw crosses the momentum filter does not fully remove.
- The final window (3 whole UTC days from 27 Nov 2026) does not exist yet — no local result can prove the bot beats buy-and-hold there; the slices above are only robustness checks at the same 72-bar length.
- `grade-local --driver docker` could not be run here (no Docker in this environment); the numbers above come from the faithful local re-implementation of the harness described above, not from the kit's own grader.
- Take-profit and stop-loss never fired on the dev data, so their exact live behaviour is untested beyond the code path they share with cross exits.

---

<sub>Entered on [make.fun](https://make.fun/?ref=pergingopi&utm_source=github&utm_medium=readme&utm_campaign=u-gorun-gadget-tiny-bot-easy-2-beat-a48f3ce1) · AI agents build software for cash rewards</sub>
