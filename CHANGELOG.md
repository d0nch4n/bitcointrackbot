# Changelog

## [Unreleased]
- Some implementations about Lightning in analysis.

## [1.2.0] - 2025-03-20

- [Added] New `/track_solo_miner` to receive alert if a block is mined by a solo miner
- [Added] New `/price` to receive the current bitcoin price in eur or usd
- [Added] New `/set_price_alert` to receive a notification daily/weekly/monthly with bitcoin price
- [Added] New `/set_price_threshold` to set bitcoin price threshold to receive alert 
- [Added] New `/convert` to convert sats in eur/usd or eur/usd in sats

## [1.1.1] - 2025-03-07
- [Changed] Modified `/recent_blocks` to display total fees in BTC instead of satoshis (converted by dividing by 100,000,000 with 8 decimal places).
- [Changed] Modified `/fee_forecast` to round fee predictions to whole numbers using `round()` for better readability.
- [Changed] Updated `/start` command message to reorder commands for clarity and consistency with added features.

## [1.1.0] - 2025-03-06
- [Added] Added timestamp to `address_subscriptions` and `tx_subscriptions` tables to monitor only transactions occurring after activation.
- [Added] New `/recent_blocks` command to display statistics on recent blocks (height, transaction count, total fees in satoshis).
- [Added] New `/fee_forecast` command to show fee predictions for upcoming blocks.
- [Added] New `/status` command to display a dashboard with current fees, mempool size, and block height.
- [Added] Imported `time` module to handle timestamps.
- [Added] New `get_mempool_size` function to retrieve mempool size via the Mempool.space API.
- [Added] New commands `/track_send_mempool` and `/track_receive_mempool` to monitor unconfirmed sends and receives in the mempool.
- [Added] New database tables: `mempool_address_subscriptions` and `notified_mempool_transactions` for mempool monitoring.
- [Added] New `monitor_mempool_addresses` function to handle monitoring of unconfirmed transactions.
- [Added] New conversation states: `SEND_ADDRESS_INPUT_MEMPOOL` and `RECEIVE_ADDRESS_INPUT_MEMPOOL`.
- [Added] New `get_mempool_transactions` function to fetch unconfirmed transactions for an address via the Mempool.space API.
- [Added] New `/tx_fee` command as a conversation to calculate the fee paid for a specific transaction (in satoshis).
- [Added] New conversation state `TX_FEE_INPUT` to handle input for the `/tx_fee` command.
- [Changed] Modified `monitor_addresses` to filter transactions based on activation timestamp.
- [Changed] Modified `monitor_transactions` to filter transactions by timestamp and automatically remove completed subscriptions.
- [Changed] Modified the `monitor_transactions` function to include a monitoring termination notification ("Monitoring terminated") when a transaction reaches the desired confirmations.
- [Changed] Updated the `/delete_my_data` function to include deletion of `mempool_address_subscriptions` and `notified_mempool_transactions` tables.
- [Changed] Updated `/list_monitors` and `/delete_monitor` functions to display and manage mempool monitors as well.
- [Fixed] Removed `DISTINCT` from the query in `monitor_addresses` (no longer needed with the new timestamp system).

## [1.0.0] - 2025-03-04
- [Added] First stable release with basic features.