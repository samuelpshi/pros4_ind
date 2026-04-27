"""Build a self-contained HTML dashboard for R4 trader analysis.

Reads the 3 days of price + trade CSVs from R4/r4_datacap/, emits
R4/analysis/r4_dashboard.html with bid/ask/mid lines plus toggleable
per-bot trade markers (up-triangle = bot was buyer, down-triangle = seller).

Sidebar controls:
  - Days: multi-select (1/2/3)
  - Product: dropdown (12 symbols)
  - Traders: per-bot checkboxes with color swatches

Days are stitched on a single x-axis: x = timestamp + (day-1) * 1_000_000.
"""
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "R4" / "r4_datacap"
OUT_PATH = REPO_ROOT / "R4" / "analysis" / "r4_dashboard.html"

DAYS = [1, 2, 3]
PRODUCTS = [
    "HYDROGEL_PACK",
    "VELVETFRUIT_EXTRACT",
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_6000",
    "VEV_6500",
]
DAY_OFFSET = 1_000_000

PRICE_COLS = [("bid_price_1", "Bid", "#d62728"), ("ask_price_1", "Ask", "#2ca02c"), ("mid_price", "Mid", "#7f7f7f")]
# Plotly D3 qualitative palette (skip yellow/light entries that are hard to see on white)
TRADER_PALETTE = ["#1f77b4", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22"]
NON_MARK_COLOR = "#000000"  # reserved for our trader (e.g. "ME") in future extension


def load_prices() -> pd.DataFrame:
    frames = []
    for day in DAYS:
        df = pd.read_csv(DATA_DIR / f"prices_round_4_day_{day}.csv", sep=";")
        df["day"] = day
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["x_stitched"] = out["timestamp"] + (out["day"] - 1) * DAY_OFFSET
    out["hover_depth"] = _build_depth_strings(out)
    return out


def _build_depth_strings(df: pd.DataFrame) -> pd.Series:
    """One string per row listing only non-null bid/ask levels."""
    parts = []
    for level in (1, 2, 3):
        bp, bv = df[f"bid_price_{level}"], df[f"bid_volume_{level}"]
        ap, av = df[f"ask_price_{level}"], df[f"ask_volume_{level}"]
        b = bp.notna()
        a = ap.notna()
        bid_str = pd.Series([""] * len(df))
        ask_str = pd.Series([""] * len(df))
        bid_str.loc[b] = "b" + str(level) + ": " + bp[b].astype(int).astype(str) + "x" + bv[b].astype(int).astype(str)
        ask_str.loc[a] = "a" + str(level) + ": " + ap[a].astype(int).astype(str) + "x" + av[a].astype(int).astype(str)
        parts.append(bid_str)
        parts.append(ask_str)
    combined = parts[0]
    for p in parts[1:]:
        sep = pd.Series([" | " if x else "" for x in combined])
        combined = combined.where(p == "", combined + sep + p)
    return combined


def load_trades() -> pd.DataFrame:
    frames = []
    for day in DAYS:
        df = pd.read_csv(DATA_DIR / f"trades_round_4_day_{day}.csv", sep=";")
        df["day"] = day
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["x_stitched"] = out["timestamp"] + (out["day"] - 1) * DAY_OFFSET
    return out


def derive_traders(trades_df: pd.DataFrame) -> list[str]:
    ids = set(trades_df["buyer"].dropna().unique()) | set(trades_df["seller"].dropna().unique())
    marks = sorted(t for t in ids if t.startswith("Mark "))
    others = sorted(t for t in ids if not t.startswith("Mark "))
    return marks + others


def trader_color_map(traders: list[str]) -> dict[str, str]:
    colors = {}
    palette_idx = 0
    for t in traders:
        if t.startswith("Mark "):
            colors[t] = TRADER_PALETTE[palette_idx % len(TRADER_PALETTE)]
            palette_idx += 1
        else:
            colors[t] = NON_MARK_COLOR
    return colors


def build_figure(prices_df: pd.DataFrame, trades_df: pd.DataFrame, traders: list[str], colors: dict[str, str]):
    traces = []
    trace_meta: dict[str, int] = {}
    legend_seen_price: set[str] = set()
    legend_seen_trader: set[str] = set()

    for day in DAYS:
        for product in PRODUCTS:
            p_sub = prices_df[(prices_df["day"] == day) & (prices_df["product"] == product)]
            for col, label, color in PRICE_COLS:
                show_legend = label not in legend_seen_price
                legend_seen_price.add(label)
                if len(p_sub):
                    cd = list(zip(
                        p_sub["day"].tolist(),
                        p_sub["timestamp"].tolist(),
                        p_sub[col].tolist(),
                        p_sub["hover_depth"].tolist(),
                    ))
                    x = p_sub["x_stitched"].tolist()
                    y = p_sub[col].tolist()
                else:
                    cd, x, y = [], [], []
                traces.append(go.Scatter(
                    x=x, y=y,
                    mode="lines",
                    name=label,
                    legendgroup="price_lines",
                    showlegend=show_legend,
                    line=dict(color=color, width=1),
                    customdata=cd,
                    hovertemplate=(
                        "day %{customdata[0]} ts %{customdata[1]}"
                        "<br>" + label + ": %{customdata[2]}"
                        "<br>%{customdata[3]}"
                        "<extra></extra>"
                    ),
                    visible=False,
                ))
                trace_meta[f"{day}|{product}|price|None|{col}"] = len(traces) - 1

            for trader in traders:
                for side, marker_symbol, role_col, ctp_col in (
                    ("buy", "triangle-up", "buyer", "seller"),
                    ("sell", "triangle-down", "seller", "buyer"),
                ):
                    t_sub = trades_df[
                        (trades_df["day"] == day)
                        & (trades_df["symbol"] == product)
                        & (trades_df[role_col] == trader)
                    ]
                    show_legend = (side == "buy") and (trader not in legend_seen_trader)
                    if show_legend:
                        legend_seen_trader.add(trader)
                    if len(t_sub):
                        cd = list(zip(
                            t_sub["day"].tolist(),
                            t_sub["timestamp"].tolist(),
                            t_sub["price"].tolist(),
                            t_sub["quantity"].tolist(),
                            t_sub[ctp_col].tolist(),
                            [side] * len(t_sub),
                        ))
                        x = t_sub["x_stitched"].tolist()
                        y = t_sub["price"].tolist()
                    else:
                        cd, x, y = [], [], []
                    traces.append(go.Scatter(
                        x=x, y=y,
                        mode="markers",
                        name=trader,
                        legendgroup=trader,
                        showlegend=show_legend,
                        marker=dict(symbol=marker_symbol, size=10, color=colors[trader],
                                    line=dict(width=1, color="white")),
                        customdata=cd,
                        hovertemplate=(
                            "day %{customdata[0]} ts %{customdata[1]}"
                            "<br>" + trader + " %{customdata[5]}"
                            "<br>price %{customdata[2]} qty %{customdata[3]}"
                            "<br>counterparty %{customdata[4]}"
                            "<extra></extra>"
                        ),
                        visible=False,
                    ))
                    trace_meta[f"{day}|{product}|trade|{trader}|{side}"] = len(traces) - 1

    # initial visibility: all 3 days, HYDROGEL_PACK, no traders
    default_product = PRODUCTS[0]
    for day in DAYS:
        for col, _, _ in PRICE_COLS:
            idx = trace_meta[f"{day}|{default_product}|price|None|{col}"]
            traces[idx].visible = True

    fig = go.Figure(data=traces)
    fig.update_layout(
        title="R4 Bot Trader Dashboard",
        xaxis=dict(
            title="Stitched timestamp (D1 → D2 → D3)",
            tickvals=[0, 500_000, 1_000_000, 1_500_000, 2_000_000, 2_500_000, 3_000_000],
            ticktext=["D1 0", "D1 500k", "D2 0", "D2 500k", "D3 0", "D3 500k", "D3 1M"],
        ),
        yaxis=dict(title="Price"),
        hovermode="closest",
        legend=dict(itemclick="toggle", itemdoubleclick="toggleothers"),
        margin=dict(l=40, r=20, t=50, b=40),
        height=720,
    )
    fig.add_vline(x=DAY_OFFSET, line_dash="dash", line_color="rgba(0,0,0,0.3)",
                  annotation_text="D1→D2", annotation_position="top")
    fig.add_vline(x=2 * DAY_OFFSET, line_dash="dash", line_color="rgba(0,0,0,0.3)",
                  annotation_text="D2→D3", annotation_position="top")
    return fig, trace_meta


def render_html(fig, trace_meta: dict[str, int], traders: list[str], colors: dict[str, str], n_traces: int) -> str:
    plot_div = fig.to_html(full_html=False, include_plotlyjs="cdn", div_id="plotly-chart")
    meta_json = json.dumps(trace_meta)

    day_inputs = "\n".join(
        f'<label class="row"><input type="checkbox" class="day-cb" value="{d}" checked> Day {d}</label>'
        for d in DAYS
    )
    product_options = "\n".join(
        f'<option value="{p}"{" selected" if p == PRODUCTS[0] else ""}>{p}</option>'
        for p in PRODUCTS
    )
    trader_rows = "\n".join(
        f'<label class="row"><span class="swatch" style="background:{colors[t]}"></span>'
        f'<input type="checkbox" class="trader-cb" data-trader="{t}"> {t}</label>'
        for t in traders
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>R4 Bot Trader Dashboard</title>
<style>
  body {{ margin: 0; font-family: -apple-system, system-ui, sans-serif; }}
  #app {{ display: flex; height: 100vh; }}
  #sidebar {{ width: 240px; padding: 16px; border-right: 1px solid #ddd; overflow-y: auto; flex-shrink: 0; }}
  #chart-pane {{ flex: 1; min-width: 0; }}
  #sidebar h3 {{ margin: 16px 0 8px 0; font-size: 13px; text-transform: uppercase; color: #555; }}
  #sidebar h3:first-child {{ margin-top: 0; }}
  .row {{ display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 3px 0; cursor: pointer; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 2px; border: 1px solid #999; flex-shrink: 0; }}
  #product-select {{ width: 100%; padding: 4px; font-size: 13px; }}
  .traders-list {{ max-height: 60vh; overflow-y: auto; }}
  .legend-note {{ font-size: 11px; color: #777; margin-top: 6px; }}
  .zoom-grid {{ display: grid; grid-template-columns: auto 1fr 1fr; gap: 4px; align-items: center; font-size: 12px; }}
  .zoom-grid button {{ padding: 4px 8px; font-size: 12px; cursor: pointer; }}
  #zoom-reset {{ width: 100%; margin-top: 6px; padding: 4px; font-size: 12px; cursor: pointer; }}
</style>
</head>
<body>
<div id="app">
  <div id="sidebar">
    <h3>Days</h3>
    {day_inputs}
    <h3>Product</h3>
    <select id="product-select">{product_options}</select>
    <h3>Price lines</h3>
    <label class="row"><span class="swatch" style="background:#d62728"></span><input type="checkbox" class="price-cb" data-col="bid_price_1" checked> Bid</label>
    <label class="row"><span class="swatch" style="background:#2ca02c"></span><input type="checkbox" class="price-cb" data-col="ask_price_1" checked> Ask</label>
    <label class="row"><span class="swatch" style="background:#7f7f7f"></span><input type="checkbox" class="price-cb" data-col="mid_price" checked> Mid</label>
    <h3>Traders</h3>
    <div class="traders-list">{trader_rows}</div>
    <div class="legend-note">▲ = trader was buyer<br>▼ = trader was seller</div>
    <h3>Zoom</h3>
    <div class="zoom-grid">
      <span>X</span><button id="zoom-x-in">−</button><button id="zoom-x-out">+</button>
      <span>Y</span><button id="zoom-y-in">−</button><button id="zoom-y-out">+</button>
    </div>
    <button id="zoom-reset">Reset axes</button>
  </div>
  <div id="chart-pane">{plot_div}</div>
</div>
<script>
  const TRACE_META = {meta_json};
  const N_TRACES = {n_traces};
  const PRICE_COLS = ["bid_price_1", "ask_price_1", "mid_price"];

  const chart = document.getElementById('plotly-chart');

  function updateVisibility() {{
    const days = [...document.querySelectorAll('.day-cb:checked')].map(cb => parseInt(cb.value));
    const product = document.getElementById('product-select').value;
    const checkedCols = [...document.querySelectorAll('.price-cb:checked')].map(cb => cb.dataset.col);
    const checkedTraders = [...document.querySelectorAll('.trader-cb:checked')].map(cb => cb.dataset.trader);

    const visible = new Array(N_TRACES).fill(false);
    for (const day of days) {{
      for (const col of checkedCols) {{
        const k = day + "|" + product + "|price|None|" + col;
        if (k in TRACE_META) visible[TRACE_META[k]] = true;
      }}
      for (const trader of checkedTraders) {{
        for (const side of ["buy", "sell"]) {{
          const k = day + "|" + product + "|trade|" + trader + "|" + side;
          if (k in TRACE_META) visible[TRACE_META[k]] = true;
        }}
      }}
    }}

    const indices = [...Array(N_TRACES).keys()];
    Plotly.restyle('plotly-chart', {{visible: visible}}, indices);
  }}

  function getRange(axis) {{
    const fl = chart._fullLayout || {{}};
    const ax = fl[axis] || {{}};
    const r = ax.range || [];
    return [Number(r[0]), Number(r[1])];
  }}

  function zoomAxis(axis, factor) {{
    // factor < 1 zooms in (range shrinks), factor > 1 zooms out
    const [lo, hi] = getRange(axis);
    if (!isFinite(lo) || !isFinite(hi)) return;
    const mid = (lo + hi) / 2;
    const half = (hi - lo) / 2 * factor;
    const update = {{}};
    update[axis + '.range'] = [mid - half, mid + half];
    Plotly.relayout(chart, update);
  }}

  function resetAxes() {{
    Plotly.relayout(chart, {{'xaxis.autorange': true, 'yaxis.autorange': true}});
  }}

  document.getElementById('zoom-x-in').addEventListener('click', () => zoomAxis('xaxis', 0.5));
  document.getElementById('zoom-x-out').addEventListener('click', () => zoomAxis('xaxis', 2));
  document.getElementById('zoom-y-in').addEventListener('click', () => zoomAxis('yaxis', 0.5));
  document.getElementById('zoom-y-out').addEventListener('click', () => zoomAxis('yaxis', 2));
  document.getElementById('zoom-reset').addEventListener('click', resetAxes);

  document.querySelectorAll('.day-cb').forEach(cb => cb.addEventListener('change', updateVisibility));
  document.getElementById('product-select').addEventListener('change', updateVisibility);
  document.querySelectorAll('.price-cb').forEach(cb => cb.addEventListener('change', updateVisibility));
  document.querySelectorAll('.trader-cb').forEach(cb => cb.addEventListener('change', updateVisibility));
</script>
</body>
</html>
"""


def main():
    print(f"Loading prices from {DATA_DIR} ...")
    prices_df = load_prices()
    print(f"  prices_df: {len(prices_df):,} rows")
    print("Loading trades ...")
    trades_df = load_trades()
    print(f"  trades_df: {len(trades_df):,} rows")

    traders = derive_traders(trades_df)
    print(f"  traders: {traders}")
    colors = trader_color_map(traders)

    print("Building figure ...")
    fig, trace_meta = build_figure(prices_df, trades_df, traders, colors)
    n_traces = len(fig.data)
    print(f"  {n_traces} traces, {len(trace_meta)} trace_meta entries")

    print(f"Rendering HTML to {OUT_PATH} ...")
    html = render_html(fig, trace_meta, traders, colors, n_traces)
    OUT_PATH.write_text(html)
    print(f"  wrote {OUT_PATH.stat().st_size / 1_000_000:.1f} MB")


if __name__ == "__main__":
    main()
