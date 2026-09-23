---
name: Master Trader
description: A neutral trading workspace for fleet comparison and position inspection.
colors:
  primary: "#176c84"
  background: "#f4f6f8"
  surface: "#ffffff"
  surface-muted: "#f6f8fa"
  border: "#dce3e9"
  text: "#17232f"
  text-secondary: "#465766"
  text-muted: "#61717f"
  positive: "#16714b"
  negative: "#ba3a35"
  chart-negative: "#c23b35"
  chart-pending: "#9a690a"
typography:
  headline:
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-.025em"
  title:
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "16px"
    fontWeight: 650
    lineHeight: 1.5
  body:
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
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
the template, `frontend/src/analytics.ts` and `frontend/src/price-chart.ts`.

## Colors

The teal primary color marks selection and actions. Cool gray backgrounds, white
surfaces and subdued borders separate information without competing with it.
Positive, negative and pending chart colors communicate direction or order state;
text labels carry the same meaning. Positive and negative metric text use the
workspace semantic colors; candle losses retain the chart-negative shade.
Position exit-state labels retain their own muted foreground/background pairs.

## Typography

The interface and comparable numeric values use Inter with the native fallbacks
in frontmatter. Weights 400, 500, 600 and 700 are self-hosted as WOFF2 files under
`static/fonts`, with `font-display: swap`. Numeric tables and P&L use tabular figures. The base stylesheet
retains JetBrains Mono for explicit technical/mono treatments; it is not the
default numeric table face.

The overview heading is 28px at weight 650; primary values are 30px at weight 600.
Card headings are 16px at weight 650, table values 13px and supporting labels
12px. Bot identity headings are 26px. At widths up to 600px, the overview heading
becomes 24px and primary values 26px. Prefer short, explicit labels.

## Layout

The centered shell is at most 1600px wide, with 32px horizontal padding, reduced
to 24px at widths up to 1100px and 16px at widths up to 600px. Sections and grids
use 24px gaps; the mobile tab-panel gap becomes 20px at 600px. The 12-column
analytics grid stacks at 1100px. Four overview measurements become two columns
at 800px. Six performance-quality columns become three at 1100px and two at
600px. Mobile navigation wraps into rows at 600px, with 20px horizontal gaps
and 12px vertical tab padding; the current navigation occupies two rows.

Bot-detail exposure and performance panels each span the full grid width.
Performance facts use three columns with 20px row and 32px column gaps,
becoming two columns with 16px column gaps at 600px.

Panel headers use 20px top, 24px horizontal and 16px bottom padding. Analytics
charts use 20px horizontal/bottom padding; comparison tables use 24px horizontal
padding. Charts are 300px tall by default, 360px for tall and 220px for short;
tall charts become 320px at 600px. Empty analytics and comparison tables use
content-driven height.

Position charts use two columns by default, three from 1900px and one at widths
up to 800px, with 24px gaps. Cards have 20px padding, reduced to 16px at 600px.
Position charts are 340px tall, or 300px at 600px. An expanded card occupies the
full grid width and first row; its chart uses `min(65vh, 700px)` with a 380px
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
- **Analytics:** D3 scales and shapes render responsive SVG equity and drawdown
  plots on a continuous calendar-time domain. Sparse observations keep their
  elapsed-time spacing. Realized equity and drawdown use step-after curves,
  2px strokes, horizontal grid lines, right-aligned value axes and separate text
  legends. Hover shows the nearest prior observation per series with a date
  and dashed vertical guide. Current equity remains a separate labeled snapshot
  above the plot. Empty histories and all-zero drawdown show explicit messages;
  a single observation uses a point. Small contribution comparisons use semantic
  tables with Name, Realized, Open P&L and Total columns; numeric columns align
  right. Lightweight Charts is reserved for position candles; ECharts is absent.
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
- **Controls:** compact controls have a 36px minimum height and 8px/12px padding.
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

## Position close controls

Each open chart has a text-labelled Close position control. A native modal dialog
provides protected confirmation focus, bot/market/side/quantity context and bot
API authentication. Passwords are cleared after submission/dismissal and never
stored in browser storage. Submission is disabled during and after accepted or
uncertain requests. Copy distinguishes acceptance from execution; filled status
continues to come from the bot. The backend persists duplicate protection across
restarts, validates current position identity and rejects cross-origin actions.
