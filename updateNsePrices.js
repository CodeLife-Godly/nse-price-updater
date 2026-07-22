import YahooFinance from "yahoo-finance2";
import { createClient } from "@supabase/supabase-js";
import dotenv from "dotenv";

// Runs on a schedule via GitHub Actions during NSE market hours.
// Filtered to NSE-listed assets only.

dotenv.config();

const yahoo = new YahooFinance({
    suppressNotices: ["yahooSurvey"]
});

const supabase = createClient(
    process.env.SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
);

async function updateNsePrices() {

    const { data: assets, error: assetError } = await supabase
        .from("assets")
        .select("id, symbol, provider_symbol, markets!inner(code)")
        .eq("markets.code", "NSE")
        .eq("is_active", true);

    if (assetError) {
        throw assetError;
    }

    console.log(`Found ${assets.length} NSE assets.`);

    let success = 0;
    let failed = 0;

    console.time("NSE Price Update");

    const BATCH_SIZE = 5;

    for (let start = 0; start < assets.length; start += BATCH_SIZE) {

        const batch = assets.slice(start, start + BATCH_SIZE);

        await Promise.all(

            batch.map(async (asset, index) => {

                console.log(
                    `[${start + index + 1}/${assets.length}] ${asset.symbol}`
                );

                try {

                    const quote = await yahoo.quote(
                        asset.provider_symbol
                    );

                    if (!quote?.regularMarketPrice) {

                        failed++;

                        console.log(
                            `✗ ${asset.symbol}: No market data`
                        );

                        return;

                    }

                    const tradingDate =
                        quote.regularMarketTime
                            .toISOString()
                            .split("T")[0];

                    const { error } = await supabase
                        .from("asset_prices")
                        .upsert(
                            {
                                asset_id: asset.id,
                                trading_date: tradingDate,
                                open_price: quote.regularMarketOpen,
                                high_price: quote.regularMarketDayHigh,
                                low_price: quote.regularMarketDayLow,
                                close_price: quote.regularMarketPrice,
                                volume: quote.regularMarketVolume
                            },
                            {
                                onConflict: "asset_id,trading_date"
                            }
                        );

                    if (error) {

                        failed++;

                        console.error(
                            `✗ ${asset.symbol}: ${error.message}`
                        );

                        return;

                    }

                    success++;

                    console.log(
                        `✓ ${asset.symbol} ₹${quote.regularMarketPrice}`
                    );

                }
                catch (err) {

                    failed++;

                    console.error(
                        `✗ ${asset.symbol}: ${err.message}`
                    );

                }

            })

        );

        // Small pause between batches — gentler pacing for Yahoo,
        // since this script is the one most exposed to scraping-block risk.
        await new Promise((resolve) => setTimeout(resolve, 500));

    }

    console.timeEnd("NSE Price Update");

    console.log(`
====================================
NSE Price Update Finished
------------------------------------
Success : ${success}
Failed  : ${failed}
====================================
`);
}

updateNsePrices().catch((err) => {
    console.error("Fatal error:", err);
    process.exit(1);
});
