"""
================================================================================
MODULE 1: IDENTIFY TOPS AND BOTTOMS
================================================================================
Purpose : From daily close price data, identify all swing tops and swing bottoms.
         Label them sequentially (B, D, F, H... for tops; C, E, G, I... for bottoms)

Method  : A Top (Swing High) = Current Close > Previous Close AND Current Close > Next Close
          A Bottom (Swing Low) = Current Close < Previous Close AND Current Close < Next Close

Charts  : Based on daily close LINE chart — only daily closing prices are used.
================================================================================
"""

import sys
import io
import pandas as pd
import numpy as np
from datetime import datetime

# Safe print that handles encoding on all platforms
_orig_print = print
def _safe_print(*args, **kwargs):
    try:
        _orig_print(*args, **kwargs)
    except (UnicodeEncodeError, IOError):
        # Strip emoji and retry
        clean_args = [str(a).encode('ascii', 'replace').decode('ascii') if isinstance(a, str) else a for a in args]
        _orig_print(*clean_args, **kwargs)

print = _safe_print


# ------------------------------------------------------------------
# STEP 1: LOAD DAILY CLOSE DATA
# ------------------------------------------------------------------
def load_daily_close_data(filepath=None, data=None):
    """
    Load daily close price data from CSV file or directly from a list/dict.

    Expected CSV format:
        Date, Close
        2024-01-01, 45000.0
        2024-01-02, 45100.0
        ...

    Args:
        filepath : Path to CSV file (optional)
        data     : Dict or DataFrame with 'Date' and 'Close' columns (optional)

    Returns:
        DataFrame with Date index and Close column
    """
    if filepath:
        df = pd.read_csv(filepath, parse_dates=['Date'])
        df = df.set_index('Date').sort_index()
        print(f"✅ Loaded {len(df)} rows from {filepath}")
        return df

    if data is not None:
        if isinstance(data, pd.DataFrame):
            df = data.copy()
        else:
            df = pd.DataFrame(data)
            if 'Date' in df.columns:
                df = df.set_index('Date').sort_index()
        print(f"✅ Loaded {len(df)} rows from provided data")
        return df

    raise ValueError("Either filepath or data must be provided.")


# ------------------------------------------------------------------
# STEP 2: IDENTIFY ALL TOPS AND BOTTOMS
# ------------------------------------------------------------------
def identify_tops_bottoms(df):
    """
    Identify all tops (swing highs) and bottoms (swing lows) from daily close data.

    Logic:
        Top  = Close[i] > Close[i-1] AND Close[i] > Close[i+1]
        Bottom = Close[i] < Close[i-1] AND Close[i] < Close[i+1]

    This requires at least 1 day before and 1 day after — so the first
    and last rows cannot be tops/bottoms.

    Args:
        df : DataFrame with 'Close' column (Date index)

    Returns:
        DataFrame with added columns: 'Is_Top', 'Is_Bottom'
    """
    df = df.copy()

    # Pad the series so we can look back and ahead safely
    closes = df['Close'].values
    n = len(closes)

    tops = []
    bottoms = []

    for i in range(1, n - 1):  # Skip first and last row
        prev_close = closes[i - 1]
        curr_close = closes[i]
        next_close = closes[i + 1]

        # Top: current is higher than BOTH neighbors
        if curr_close > prev_close and curr_close > next_close:
            tops.append((df.index[i], curr_close))

        # Bottom: current is lower than BOTH neighbors
        elif curr_close < prev_close and curr_close < next_close:
            bottoms.append((df.index[i], curr_close))

    # Mark in dataframe
    df['Is_Top'] = False
    df['Is_Bottom'] = False

    for idx, _ in tops:
        df.loc[idx, 'Is_Top'] = True

    for idx, _ in bottoms:
        df.loc[idx, 'Is_Bottom'] = True

    print(f"\n📊 Identified {len(tops)} Tops and {len(bottoms)} Bottoms")

    return df, tops, bottoms


# ------------------------------------------------------------------
# STEP 3: LABEL TOPS AND BOTTOMS SEQUENTIALLY
# ------------------------------------------------------------------
def label_tops_bottoms(df, tops, bottoms):
    """
    Label all tops and bottoms sequentially.

    Tops    : B, D, F, H, J, L, N, P, ... (start from B, skip A)
    Bottoms : C, E, G, I, K, M, O, Q, ...

    Also tracks:
        - Each top's PREVIOUS TOP
        - Each bottom's PREVIOUS BOTTOM

    Args:
        df      : DataFrame with Is_Top and Is_Bottom markers
        tops    : List of (date, price) tuples for tops
        bottoms : List of (date, price) tuples for bottoms

    Returns:
        tops_df   : DataFrame of labeled tops
        bottoms_df: DataFrame of labeled bottoms
    """

    def get_label_list(count, start_letter='B'):
        """Generate B, D, F... or C, E, G... labels."""
        labels = []
        current = ord(start_letter)
        for i in range(count):
            labels.append(chr(current + i * 2))
        return labels

    # Build tops DataFrame
    tops_df = pd.DataFrame(tops, columns=['Date', 'Price'])
    top_labels = get_label_list(len(tops), 'B')
    tops_df['Label'] = top_labels

    # Each top's previous top
    tops_df['Previous_Top_Date'] = [None] + list(tops_df['Date'].iloc[:-1])
    tops_df['Previous_Top_Price'] = [None] + list(tops_df['Price'].iloc[:-1])

    # Build bottoms DataFrame
    bottoms_df = pd.DataFrame(bottoms, columns=['Date', 'Price'])
    bottom_labels = get_label_list(len(bottoms), 'C')
    bottoms_df['Label'] = bottom_labels

    # Each bottom's previous bottom
    bottoms_df['Previous_Bottom_Date'] = [None] + list(bottoms_df['Date'].iloc[:-1])
    bottoms_df['Previous_Bottom_Price'] = [None] + list(bottoms_df['Price'].iloc[:-1])

    return tops_df, bottoms_df


# ------------------------------------------------------------------
# STEP 4: GET CURRENT S-A-R LEVELS (LATEST TOP & BOTTOM)
# ------------------------------------------------------------------
def get_sar_levels(tops_df, bottoms_df):
    """
    Return the most recent Previous Top (S-A-R Top) and Previous Bottom (S-A-R Bottom).

    These are the levels used for trading signals:
        - BUY when price crosses above Previous Top
        - SELL when price crosses below Previous Bottom

    Returns:
        dict with:
            'prev_top_date', 'prev_top_price',
            'prev_bottom_date', 'prev_bottom_price',
            'latest_top', 'latest_bottom'
    """
    if tops_df.empty:
        raise ValueError("No tops found. Need at least one top.")

    # Latest identified top
    latest_top = tops_df.iloc[-1]

    # Previous top = second-to-last top (if exists), else latest top
    prev_top_row = tops_df.iloc[-2] if len(tops_df) >= 2 else tops_df.iloc[-1]

    # Handle case where bottoms_df is empty
    if bottoms_df.empty:
        prev_bottom_row = prev_top_row  # Fallback
        latest_bottom = None
    else:
        latest_bottom = bottoms_df.iloc[-1]
        prev_bottom_row = bottoms_df.iloc[-2] if len(bottoms_df) >= 2 else bottoms_df.iloc[-1]

    # Helper to safely get date string
    def get_date_str(val):
        if val is None: return None
        try:
            return str(pd.to_datetime(val).date())
        except:
            return str(val)

    levels = {
        # The Previous Top — this is the S-A-R level for BUY entry
        'prev_top_date': get_date_str(prev_top_row['Date']),
        'prev_top_price': float(prev_top_row['Price']),

        # The Previous Bottom — this is the S-A-R level for SELL entry
        'prev_bottom_date': get_date_str(prev_bottom_row['Date']),
        'prev_bottom_price': float(prev_bottom_row['Price']),

        # The most recently confirmed top and bottom
        'latest_top_date': get_date_str(latest_top['Date']),
        'latest_top_price': float(latest_top['Price']),
        'latest_top_label': latest_top['Label'],

        'latest_bottom_date': get_date_str(latest_bottom['Date']) if latest_bottom is not None else None,
        'latest_bottom_price': float(latest_bottom['Price']) if latest_bottom is not None else None,
        'latest_bottom_label': latest_bottom['Label'] if latest_bottom is not None else None,

        # Count of identified levels
        'total_tops': len(tops_df),
        'total_bottoms': len(bottoms_df),
    }

    return levels


# ------------------------------------------------------------------
# STEP 5: UPDATE S-A-R LEVELS DAILY (END OF DAY)
# ------------------------------------------------------------------
def update_sar_levels_end_of_day(df, tops_df, bottoms_df, new_close_price, new_date):
    """
    After daily close, add the new closing price and re-identify tops/bottoms.

    Call this at the end of each trading day to update S-A-R levels.

    Args:
        df             : Original DataFrame
        tops_df        : Current labeled tops DataFrame
        bottoms_df     : Current labeled bottoms DataFrame
        new_close_price: Today's closing price
        new_date       : Today's date

    Returns:
        Updated df, tops_df, bottoms_df, and new S-A-R levels
    """
    # Add new row
    new_row = pd.DataFrame({'Close': [new_close_price]}, index=[pd.Timestamp(new_date)])
    df = pd.concat([df, new_row]).sort_index()

    # Re-identify tops and bottoms with new data
    df, tops, bottoms = identify_tops_bottoms(df)

    # Re-label
    tops_df, bottoms_df = label_tops_bottoms(df, tops, bottoms)

    # Get updated S-A-R levels
    levels = get_sar_levels(tops_df, bottoms_df)

    return df, tops_df, bottoms_df, levels


# ------------------------------------------------------------------
# STEP 6: PRINT SUMMARY REPORT
# ------------------------------------------------------------------
def print_sar_report(levels, tops_df, bottoms_df):
    """Print a readable S-A-R levels report."""
    print("\n" + "=" * 60)
    print("📋 S-A-R (STOP AND REVERSE) LEVELS REPORT")
    print("=" * 60)

    print(f"\n🔴 PREVIOUS TOP (S-A-R) — BUY Trigger Level:")
    print(f"   Date  : {levels['prev_top_date']}")
    print(f"   Price : ₹{levels['prev_top_price']:,.2f}")

    print(f"\n🔵 PREVIOUS BOTTOM (S-A-R) — SELL Trigger Level:")
    print(f"   Date  : {levels['prev_bottom_date']}")
    print(f"   Price : ₹{levels['prev_bottom_price']:,.2f}")

    print(f"\n📊 Most Recent Confirmed Levels:")
    print(f"   Latest Top   ({levels['latest_top_label']})  : {levels['latest_top_date']}  @ ₹{levels['latest_top_price']:,.2f}")
    print(f"   Latest Bottom({levels['latest_bottom_label']}): {levels['latest_bottom_date']}  @ ₹{levels['latest_bottom_price']:,.2f}")

    print(f"\n📈 Total Identified: {levels['total_tops']} Tops, {levels['total_bottoms']} Bottoms")

    print("\n" + "=" * 60)
    print("💡 TRADING SIGNALS:")
    print(f"   BUY  if price crosses ABOVE ₹{levels['prev_top_price']:,.2f}")
    print(f"   SELL if price crosses BELOW ₹{levels['prev_bottom_price']:,.2f}")
    print("=" * 60 + "\n")


# ------------------------------------------------------------------
# QUICK TEST WITH SAMPLE DATA
# ------------------------------------------------------------------
def run_sample_test():
    """Run a quick test with sample Bank Nifty-like data."""

    print("[TEST] Running Sample Test...\n")

    # Sample daily close data (simulated Bank Nifty-like prices)
    sample_data = {
        'Date': pd.date_range('2024-01-01', periods=30, freq='B'),
        'Close': [
            45200, 45100, 45350, 45400, 45250,  # Day 5: Top at 45400 (B)
            45100, 44900, 44700, 45000, 45200,  # Day 10: Bottom at 44700 (C)
            45500, 45650, 45500, 45800, 45700,  # Day 15: Top at 45800 (D)
            45400, 45200, 44900, 45100, 45300,  # Day 20: Bottom at 44900 (E)
            45500, 45700, 45600, 45900, 46000,  # Day 25: Top at 46000 (F)
            45800, 45500, 45300, 45600, 45800   # Day 30: Bottom at 45300 (G)
        ]
    }

    df = pd.DataFrame(sample_data).set_index('Date')

    # Identify tops and bottoms
    df, tops, bottoms = identify_tops_bottoms(df)

    # Label them
    tops_df, bottoms_df = label_tops_bottoms(df, tops, bottoms)

    # Print labeled structures
    print("\n🔴 IDENTIFIED TOPS:")
    print(tops_df.to_string(index=False))

    print("\n🔵 IDENTIFIED BOTTOMS:")
    print(bottoms_df.to_string(index=False))

    # Get S-A-R levels
    levels = get_sar_levels(tops_df, bottoms_df)
    print_sar_report(levels, tops_df, bottoms_df)

    return df, tops_df, bottoms_df, levels


# ------------------------------------------------------------------
# MAIN ENTRY POINT
# ------------------------------------------------------------------
if __name__ == "__main__":
    df, tops_df, bottoms_df, levels = run_sample_test()
