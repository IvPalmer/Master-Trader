---
name: Master Trader
description: A neutral trading workspace for fleet comparison and position inspection.
colors:
  primary: "#176c84"
  background: "#f3f5f7"
  surface: "#ffffff"
  surface-muted: "#f6f8fa"
  border: "#dce3e9"
  text: "#17232f"
  text-secondary: "#465766"
  text-muted: "#61717f"
  chart-positive: "#16714b"
  chart-negative: "#c23b35"
  chart-pending: "#9a690a"
typography:
  headline:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 650
    letterSpacing: "-.025em"
  body:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: "12px"
rounded:
  surface: "12px"
  control: "6px"
  chip: "4px"
spacing:
  small: "8px"
  compact: "12px"
  medium: "16px"
  panel: "20px"
  section: "24px"
---

# Design System: Master Trader

## Overview

Preserve the existing functional identity: concise trader information, neutral
surfaces and clear measurement labels. The workspace supports fleet comparison,
individual bot inspection and multiple readable position charts with an expanded
view. It does not introduce a new brand or decorative visual theme.

This document records the implemented workspace overrides in
`ft_userdata/ft_dashboard/static/workspace.css`, layered after `styles.css`, and
the template and `frontend/src/price-chart.ts` behavior.

## Colors

The teal primary color marks selection and actions. Cool gray backgrounds, white
surfaces and subdued borders separate information without competing with it.
Positive, negative and pending chart colors communicate direction or order state;
text labels carry the same meaning. Existing metric colors remain inherited from
the base stylesheet, so charts and P&L text use distinct semantic shades.

## Typography

Inter is the interface family; JetBrains Mono with system monospace fallbacks
remains available for numeric tables and technical values. Use tabular figures
for values that users compare.

The overview heading and primary values are 28px; values use weight 600. Card
headings are 15px at weight 650, pair names 16px, table values 13px and supporting
labels 12px. Bot identity headings are 26px. At widths up to 600px, overview
headings and primary values become 24px. Prefer short, explicit labels over
additional typographic emphasis.

## Layout

The centered shell is at most 1800px wide, with 28px horizontal padding, reduced
to 18px at widths up to 1000px and 12px at widths up to 600px. Main sections use
20–24px spacing. Four overview measurements become two columns at 1000px.

Position charts use two columns by default, three from 1650px and one at widths
up to 1000px, with 20px gaps. Cards have 20px padding, reduced to 16px at 1000px.
Charts are 340px tall, or 300px at widths up to 600px. An expanded card occupies
the full grid width and first row; its chart uses up to 65vh/700px with a 380px
minimum. On small screens its height is 65vh, retaining that minimum.

## Elevation & Depth

Primary surfaces are flat, without card shadows. Borders and background tones
provide grouping. The retained highest elevation token is
`0 12px 40px #17232f18`; it is not the default card treatment. The top bar is
static and has no backdrop blur.

## Shapes

Cards and operational strips share the surface radius; controls use the smaller
control radius and exit labels use the chip radius. One-pixel borders define
containers. Tabs use a bottom rule and selected underline rather than raised
pill shapes.

## Components

- **Overview:** incidents precede account equity, realized P&L, unrealized P&L
  and estimated loss to bot stops. Shared accounts count once. The realized
  series represents closed results in live epochs; current unrealized P&L is a
  separate measurement. Secondary research stays behind disclosure controls.
- **Bot detail:** show strategy, venue, account, operating state and measurement
  scope together. Keep the selected bot's performance, positions, history and
  native-stop evidence scoped to that bot. Paper and historical observations
  retain visible context rather than implying live results.
- **Position cards:** identify the bot, pair, direction, paper status when
  applicable, P&L, entry/current-or-exit price and trade window. Timeframes are
  5m, 15m, 1h and 4h. Venue, loading, retry and truncated-history messages remain
  adjacent to the chart.
- **Price action / All exits:** Price action autoscales the candles. All exits
  additionally includes entry, current-or-exit price and available exit levels
  in the price range. Both retain level lines; open positions also list their
  stop and exit states above the chart, so distant targets remain readable
  without forcing candle compression. Active levels use solid lines; other
  levels use dashed lines. Refreshes preserve the visible logical range when
  the timeframe is unchanged; a new timeframe starts near the latest 90 bars.
- **Expand chart:** expand one card within the grid; Restore grid or Escape
  returns to the comparison layout. This is an inline expansion, not a modal.
- **Controls:** compact controls have a 32px minimum height and 6px/12px padding.
  Focus uses a 2px teal outline with 3px offset; hover reduces brightness.
  Scale selection exposes `aria-pressed`, expansion exposes `aria-expanded`
  and chart loading exposes `aria-busy`. Reduced-motion preferences disable
  transitions and smooth scrolling.

## Do's and Don'ts

- **Do** keep realized results, open P&L, account equity and estimated stop loss
  distinct, with the measurement epoch and scope visible.
- **Do** label a bot-reported stop as “Bot stop.” Native exchange protection
  requires separate venue evidence; a price line is not verification.
- **Do** retain planned, pending, active, rejected and unknown exit states in
  text. A target is not automatically an exchange order.
- **Don't** fabricate missing telemetry, mark-to-market history or protection.
  “No TP order reported” does not rule out a dynamic strategy exit.
- **Don't** remove the multiple-chart comparison view to accommodate expansion,
  or reset a user's viewport during a same-timeframe refresh.
