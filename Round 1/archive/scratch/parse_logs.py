#!/usr/bin/env python3
"""
Log parser for prosperity4btest output logs.
Extracts: total PnL, per-product PnL, max/min position per product,
max drawdown, inventory path summary, circuit breaker events.
"""
import re
import sys
import os
import json
import io

def parse_log(log_path):
    """Parse a prosperity4btest log file and return structured data."""
    with open(log_path, 'r') as f:
        content = f.read()

    results = {
        'log_path': log_path,
        'errors': [],
        'warnings': [],
    }

    # Count "exceeded limit" occurrences from sandboxLog entries
    exceeded_limit_total = 0
    exceeded_limit_ipr = 0
    exceeded_limit_aco = 0
    circuit_trigger_count = 0
    circuit_trigger_timestamps = []

    # Parse individual sandbox log JSON objects
    sandbox_section_end = content.find('Activities log:')
    sandbox_section = content[:sandbox_section_end] if sandbox_section_end > 0 else content

    # Extract each JSON object (one per line-group)
    sandbox_objs = re.findall(r'\{[^{}]+\}', sandbox_section, re.DOTALL)
    for obj_str in sandbox_objs:
        obj_str_clean = re.sub(r',(\s*[}\]])', r'\1', obj_str)
        try:
            obj = json.loads(obj_str_clean)
            log_msg = obj.get('sandboxLog', '') + obj.get('lambdaLog', '')
            ts = obj.get('timestamp', -1)
            if 'exceeded limit' in log_msg:
                exceeded_limit_total += 1
                if 'PEPPER' in log_msg or 'IPR' in log_msg or 'INTARIAN' in log_msg:
                    exceeded_limit_ipr += 1
                if 'OSMIUM' in log_msg or 'ACO' in log_msg or 'ASH' in log_msg:
                    exceeded_limit_aco += 1
            if 'circuit' in log_msg.lower():
                circuit_trigger_count += 1
                circuit_trigger_timestamps.append(ts)
        except (json.JSONDecodeError, ValueError):
            pass

    results['exceeded_limit_total'] = exceeded_limit_total
    results['exceeded_limit_ipr'] = exceeded_limit_ipr
    results['exceeded_limit_aco'] = exceeded_limit_aco
    results['circuit_trigger_count'] = circuit_trigger_count
    results['circuit_trigger_timestamps'] = circuit_trigger_timestamps

    # Check for errors/exceptions/warnings
    for pattern in ['Error', 'Exception', 'Traceback', 'Warning']:
        matches = re.findall(r'.{0,60}' + pattern + r'.{0,60}', content, re.IGNORECASE)
        # Filter out false positives in JSON data
        for m in matches:
            if 'sandboxLog' not in m and 'lambdaLog' not in m:
                if pattern in ['Error', 'Exception', 'Traceback']:
                    results['errors'].append(m.strip())
                else:
                    results['warnings'].append(m.strip())

    # Parse Activities log section
    # Format: day;timestamp;product;bid_price_1;...;mid_price;profit_and_loss
    activities_match = re.search(r'Activities log:\n(.*?)(?:\nTrade History:|\Z)', content, re.DOTALL)
    if not activities_match:
        results['parse_error'] = 'Activities log section not found'
        return results

    activities_text = activities_match.group(1)
    lines = activities_text.strip().split('\n')
    if not lines:
        results['parse_error'] = 'Activities log is empty'
        return results

    # Parse header
    header = lines[0].split(';')
    # Find column indices
    try:
        col_day = header.index('day')
        col_ts = header.index('timestamp')
        col_prod = header.index('product')
        col_mid = header.index('mid_price')
        col_pnl = header.index('profit_and_loss')
    except ValueError as e:
        results['parse_error'] = f'Missing column: {e}'
        return results

    # Per-product tracking
    product_pnl = {}        # product -> latest pnl
    product_positions = {}  # product -> list of (timestamp, position)
    product_mid = {}        # product -> list of (timestamp, mid)
    product_pnl_series = {} # product -> list of (timestamp, pnl)

    # We need position from trade history later, but activities has profit_and_loss
    # profit_and_loss is the running PnL per product

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(';')
        if len(parts) <= max(col_day, col_ts, col_prod, col_mid, col_pnl):
            continue
        try:
            day_val = int(parts[col_day])
            ts = int(parts[col_ts])
            prod = parts[col_prod].strip()
            mid_str = parts[col_mid].strip()
            pnl_str = parts[col_pnl].strip()
            mid = float(mid_str) if mid_str else 0.0
            pnl = float(pnl_str) if pnl_str else 0.0
        except (ValueError, IndexError):
            continue

        if prod not in product_pnl:
            product_pnl[prod] = []
            product_pnl_series[prod] = []
            product_mid[prod] = []

        product_pnl[prod].append(pnl)
        product_pnl_series[prod].append((ts, pnl))
        product_mid[prod].append((ts, mid))

    results['products'] = {}
    total_final_pnl = 0.0

    for prod in product_pnl:
        final_pnl = product_pnl[prod][-1] if product_pnl[prod] else 0.0
        total_final_pnl += final_pnl
        results['products'][prod] = {
            'final_pnl': final_pnl,
            'pnl_series_len': len(product_pnl_series[prod]),
        }
        # Max drawdown from pnl series
        pnls = [p for _, p in product_pnl_series[prod]]
        if pnls:
            peak = pnls[0]
            max_dd = 0.0
            for p in pnls:
                if p > peak:
                    peak = p
                dd = peak - p
                if dd > max_dd:
                    max_dd = dd
            results['products'][prod]['max_drawdown'] = max_dd

    results['total_final_pnl'] = total_final_pnl

    # Parse Trade History for positions
    trade_history_match = re.search(r'Trade History:\n(\[.*?\])', content, re.DOTALL)
    if trade_history_match:
        try:
            # prosperity4btest logs can have trailing commas - clean them
            th_text = trade_history_match.group(1)
            # Remove trailing commas before } and ]
            th_text = re.sub(r',(\s*[}\]])', r'\1', th_text)
            trades = json.loads(th_text)

            # Compute running positions per product
            # Position changes: buyer=SUBMISSION -> +qty, seller=SUBMISSION -> -qty
            pos_by_prod = {}
            pos_events = {}  # product -> list of (timestamp, position)

            for trade in sorted(trades, key=lambda x: x.get('timestamp', 0)):
                ts = trade.get('timestamp', 0)
                buyer = trade.get('buyer', '')
                seller = trade.get('seller', '')
                symbol = trade.get('symbol', '')
                qty = trade.get('quantity', 0)

                if symbol not in pos_by_prod:
                    pos_by_prod[symbol] = 0
                    pos_events[symbol] = [(0, 0)]  # start at 0

                if buyer == 'SUBMISSION':
                    pos_by_prod[symbol] += qty
                    pos_events[symbol].append((ts, pos_by_prod[symbol]))
                elif seller == 'SUBMISSION':
                    pos_by_prod[symbol] -= qty
                    pos_events[symbol].append((ts, pos_by_prod[symbol]))

            for prod in pos_events:
                positions = [p for _, p in pos_events[prod]]
                if prod not in results['products']:
                    results['products'][prod] = {}
                results['products'][prod]['max_position'] = max(positions)
                results['products'][prod]['min_position'] = min(positions)
                results['products'][prod]['final_position'] = pos_by_prod[prod]
                results['products'][prod]['position_events'] = pos_events[prod]

        except json.JSONDecodeError as e:
            results['trade_parse_error'] = str(e)

    return results


def format_results(results, label=''):
    """Print a human-readable summary."""
    print(f"\n{'='*60}")
    print(f"LOG: {label or results['log_path']}")
    print(f"{'='*60}")

    if 'parse_error' in results:
        print(f"  PARSE ERROR: {results['parse_error']}")
        return

    print(f"  Total PnL: {results.get('total_final_pnl', 'N/A'):.1f}")

    for prod, data in sorted(results.get('products', {}).items()):
        print(f"\n  [{prod}]")
        print(f"    Final PnL: {data.get('final_pnl', 'N/A'):.1f}")
        print(f"    Max Drawdown: {data.get('max_drawdown', 'N/A'):.1f}")
        print(f"    Max Position: {data.get('max_position', 'N/A')}")
        print(f"    Min Position: {data.get('min_position', 'N/A')}")
        print(f"    Final Position: {data.get('final_position', 'N/A')}")

    print(f"\n  Exceeded limit total: {results.get('exceeded_limit_total', 0)}")
    print(f"  Exceeded limit IPR:   {results.get('exceeded_limit_ipr', 0)}")
    print(f"  Exceeded limit ACO:   {results.get('exceeded_limit_aco', 0)}")
    print(f"  Circuit triggers:     {results.get('circuit_trigger_count', 0)}")
    if results.get('circuit_trigger_timestamps'):
        print(f"  Circuit timestamps:   {results['circuit_trigger_timestamps'][:10]}")

    if results['errors']:
        print(f"\n  ERRORS: {results['errors'][:5]}")
    if results['warnings']:
        print(f"\n  WARNINGS: {results['warnings'][:5]}")

    if 'trade_parse_error' in results:
        print(f"\n  TRADE PARSE ERROR: {results['trade_parse_error']}")


if __name__ == '__main__':
    base = '/Users/samuelshi/IMC-Prosperity-2026-personal/runs'
    logs = {
        'v8_day-2': f'{base}/v8_day-2.log',
        'v8_day-1': f'{base}/v8_day-1.log',
        'v8_day0': f'{base}/v8_day0.log',
        'v8_merged': f'{base}/v8_merged.log',
        'v9_day-2': f'{base}/v9_day-2.log',
        'v9_day-1': f'{base}/v9_day-1.log',
        'v9_day0': f'{base}/v9_day0.log',
        'v9_merged': f'{base}/v9_merged.log',
        'v9_merged_worse': f'{base}/v9_merged_worse.log',
        'v9_aco_only_merged': f'{base}/v9_aco_only_merged.log',
        'v9_ipr_only_merged': f'{base}/v9_ipr_only_merged.log',
    }

    all_results = {}
    for label, path in logs.items():
        if os.path.exists(path):
            r = parse_log(path)
            all_results[label] = r
            format_results(r, label)
        else:
            print(f"\n  MISSING: {path}")

    # Print consolidated table
    print("\n\n" + "="*80)
    print("CONSOLIDATED RESULTS TABLE")
    print("="*80)
    print(f"{'Scenario':<25} {'Total PnL':>12} {'ACO PnL':>12} {'IPR PnL':>12}")
    print("-"*65)

    for label in ['v8_day-2', 'v8_day-1', 'v8_day0', 'v8_merged',
                  'v9_day-2', 'v9_day-1', 'v9_day0', 'v9_merged',
                  'v9_merged_worse', 'v9_aco_only_merged', 'v9_ipr_only_merged']:
        if label not in all_results:
            continue
        r = all_results[label]
        total = r.get('total_final_pnl', float('nan'))
        prods = r.get('products', {})
        aco_pnl = prods.get('ASH_COATED_OSMIUM', {}).get('final_pnl', float('nan'))
        ipr_pnl = prods.get('INTARIAN_PEPPER_ROOT', {}).get('final_pnl', float('nan'))
        print(f"{label:<25} {total:>12.1f} {aco_pnl:>12.1f} {ipr_pnl:>12.1f}")

    # Position extremes
    print("\n\n" + "="*80)
    print("POSITION EXTREMES TABLE")
    print("="*80)
    print(f"{'Scenario':<25} {'ACO Max':>9} {'ACO Min':>9} {'IPR Max':>9} {'IPR Min':>9}")
    print("-"*60)

    for label in ['v9_day-2', 'v9_day-1', 'v9_day0', 'v9_merged',
                  'v9_merged_worse', 'v9_aco_only_merged', 'v9_ipr_only_merged']:
        if label not in all_results:
            continue
        r = all_results[label]
        prods = r.get('products', {})
        aco = prods.get('ASH_COATED_OSMIUM', {})
        ipr = prods.get('INTARIAN_PEPPER_ROOT', {})
        print(f"{label:<25} {aco.get('max_position','N/A'):>9} {aco.get('min_position','N/A'):>9} "
              f"{ipr.get('max_position','N/A'):>9} {ipr.get('min_position','N/A'):>9}")

    # Save results as JSON
    import json as _json
    # Remove non-serializable
    out = {}
    for k, v in all_results.items():
        vv = dict(v)
        if 'products' in vv:
            pp = {}
            for prod, pdata in vv['products'].items():
                pd2 = dict(pdata)
                if 'position_events' in pd2:
                    del pd2['position_events']  # too large
                pp[prod] = pd2
            vv['products'] = pp
        # Remove non-serializable items
        vv.pop('log_path', None)
        out[k] = vv

    with open('/Users/samuelshi/IMC-Prosperity-2026-personal/scratch/parsed_results.json', 'w') as f:
        _json.dump(out, f, indent=2)
    print("\nSaved to scratch/parsed_results.json")
