"""
Updates NSE asset prices in Supabase using the `nse` library
(BennyThadikaran/NseIndiaApi), which hits NSE's own official site directly
and is explicitly confirmed to work from cloud/server environments
(unlike Yahoo Finance scraping, which gets blocked from shared cloud IPs).

NSE's documented rate limit is 3 requests/second. We use a much more
conservative ~1 request/second, comfortably under that limit.

Run: python update_nse_prices.py
Requires: pip install "nse[server]" supabase python-dotenv
"""

import os
import sys
import time
import tempfile
from datetime import date

from supabase import create_client
from dotenv import load_dotenv
from nse import NSE

load_dotenv()

DELAY_SECONDS = 1.0  # well under NSE's documented 3 req/sec limit

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)


def fetch_nse_assets():
    resp = (
        supabase.table("assets")
        .select("id, symbol, markets!inner(code)")
        .eq("markets.code", "NSE")
        .eq("is_active", True)
        .execute()
    )
    return resp.data


def extract_ohlcv(quote: dict, printed_raw: bool):
    """
    Pulls OHLCV out of the equityQuote() response. Prints the raw dict
    on the FIRST call only, so you can immediately verify the real key
    names if extraction ever looks wrong, instead of debugging blind.
    """
    if not printed_raw:
        print("  [debug] raw equityQuote response:", quote)

    return {
        "open_price": quote.get("open"),
        "high_price": quote.get("high"),
        "low_price": quote.get("low"),
        "close_price": quote.get("close"),
        "volume": quote.get("volume"),
    }


def main():
    assets = fetch_nse_assets()
    print(f"Found {len(assets)} NSE assets.")

    download_folder = tempfile.mkdtemp()
    trading_date = date.today().isoformat()

    success = 0
    failed = 0
    printed_raw = False

    with NSE(download_folder=download_folder, server=True) as nse:
        for i, asset in enumerate(assets, 1):
            symbol = asset["symbol"]
            print(f"[{i}/{len(assets)}] {symbol}...")

            try:
                quote = nse.equityQuote(symbol)
                ohlcv = extract_ohlcv(quote, printed_raw)
                printed_raw = True

                if ohlcv["close_price"] is None:
                    failed += 1
                    print(f"  ✗ {symbol}: no close price in response")
                else:
                    resp = (
                        supabase.table("asset_prices")
                        .upsert(
                            {
                                "asset_id": asset["id"],
                                "trading_date": trading_date,
                                **ohlcv,
                            },
                            on_conflict="asset_id,trading_date",
                        )
                        .execute()
                    )
                    success += 1
                    print(f"  ✓ {symbol} ₹{ohlcv['close_price']}")

            except Exception as e:
                failed += 1
                print(f"  ✗ {symbol}: {e}")

            time.sleep(DELAY_SECONDS)

    print(f"\n====================================")
    print(f"NSE Price Update Finished")
    print(f"Success : {success}")
    print(f"Failed  : {failed}")
    print(f"====================================")


if __name__ == "__main__":
    main()
