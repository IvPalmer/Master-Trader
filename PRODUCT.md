# Master Trader
<!-- impeccable:product-schema 1 -->

## Platform
web

## Users
Palmer operates an automated trading fleet and needs a concise portfolio overview
plus detailed inspection of each bot and its positions.

## Product Purpose
Make performance, exposure, exit plans and operational exceptions understandable.
The operator explicitly prefers multiple position charts with an expand view.

## Capabilities and Constraints
Python dashboard APIs aggregate live and paper bots on different venues. Shared
accounts must not be counted twice. Historical paper results, live realized equity
and current unrealized P&L are distinct measurements. Planned targets are not
exchange orders; a reported bot stop is not independent exchange verification.
Do not invent missing telemetry or mark-to-market history. The dashboard provides authenticated, explicitly confirmed full-position close
requests. It does not autonomously change allocations or orders. Source edits and network-free tests run
locally; live runtime remains on the VPS under RUNTIME.md.

## Product Principles
- Put operational exceptions and real exposure before secondary diagnostics.
- Separate realized returns from unrealized gains and live from paper trading.
- Keep charts readable while retaining access to the complete exit plan.
- Preserve user timeframe and viewport while data refreshes.

## Evidence on Hand
Existing API contracts and tests, user dashboard screenshots and operator feedback.
Visual QA uses explicitly synthetic fixtures, never published account identifiers.
