# Bitcoin Track Bot v.1.0.0
# Copyright (C) 2025 Brienza Donato (d0nch4n)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# Thanks to Pieter Wuille for his segwit_addr.py program for Taproot checksum verify


import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters, ContextTypes
import requests
from sqlcipher3 import dbapi2 as sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv
import re
from segwit_addr import decode as segwit_decode

# Caricamento delle variabili d'ambiente dal file .env
load_dotenv()

# Token del bot Telegram dal file .env
TOKEN = os.getenv('TELEGRAM_TOKEN')
if TOKEN is None:
    raise ValueError("La variabile TELEGRAM_TOKEN non è definita nel file .env.")

# Chiave del database dal file .env
DB_KEY = os.getenv('DB_KEY')
if DB_KEY is None:
    raise ValueError("La variabile DB_KEY non è definita nel file .env.")

# Indirizzo Lightning dal file .env
LIGHTNING_ADDRESS = os.getenv('LIGHTNING_ADDRESS')
if LIGHTNING_ADDRESS is None:
    raise ValueError("La variabile LIGHTNING_ADDRESS non è definita nel file .env.")

# URL base dell'API di Mempool.space
MEMPOOL_API_URL = 'https://mempool.space/api'

# Stati per le conversazioni
SEND_ADDRESS_INPUT = 1
RECEIVE_ADDRESS_INPUT = 2
TX_ID_INPUT = 3
TX_CONFIRMATIONS_INPUT = 4
FEE_THRESHOLD_INPUT = 5
DELETE_MONITOR_INPUT = 6

# Dizionario per mappare i comandi alle loro funzioni
COMMAND_MAP = {
    '/start': 'start',
    '/track_send': 'track_send',
    '/track_receive': 'track_receive',
    '/track_tx': 'track_tx',
    '/set_fee_threshold': 'set_fee_threshold',
    '/current_fees': 'current_fees',
    '/list_monitors': 'list_monitors',
    '/delete_monitor': 'delete_monitor',
    '/delete_my_data': 'delete_my_data',
    '/donate': 'donate',
}

# Funzione per validare indirizzi Bitcoin
def is_valid_bitcoin_address(address):
    if re.match(r'^(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}$', address):
        return True
    if address.startswith('bc1'):
        try:
            result = segwit_decode('bc', address)
            if result is None:
                return False
            version, data = result
            if version == 0 and len(address) == 42 and address.startswith('bc1q'):
                return True
            elif version == 1 and len(address) == 62 and address.startswith('bc1p'):
                return True
            return False
        except Exception:
            return False
    return False

# Funzione per validare ID transazioni
def is_valid_txid(txid):
    return len(txid) == 64 and all(c in '0123456789abcdefABCDEF' for c in txid)

# Inizializzazione del database SQLite
def init_db():
    try:
        conn = sqlite3.connect('subscriptions.db')
        conn.execute(f"PRAGMA key = '{DB_KEY}'")
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS address_subscriptions (user_id TEXT, address TEXT, type TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS fee_thresholds (user_id TEXT, threshold REAL)')
        c.execute('CREATE TABLE IF NOT EXISTS tx_subscriptions (user_id TEXT, txid TEXT, confirmations INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS notified_transactions (user_id TEXT, txid TEXT)')
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Ciao! Usa i seguenti comandi:\n'
        '/track_send - Monitora invii BTC\n'
        '/track_receive - Monitora ricezioni BTC\n'
        '/track_tx - Monitora transazioni\n'
        '/set_fee_threshold - Imposta soglia fee\n'
        '/current_fees - Fee attuali\n'
        '/list_monitors - Lista monitoraggi\n'
        '/delete_monitor - Cancella monitoraggio\n'
        '/delete_my_data - Cancella dati\n'
        '/donate - Sostieni il progetto'
    )

# Comando /donate
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Supporta il bot! ❤️\n\n"
        f"Lightning: `{LIGHTNING_ADDRESS}`\n\n"
        "Grazie!",
        parse_mode='Markdown'
    )

# Funzione per ottenere transazioni di un indirizzo
def get_address_transactions(address):
    url = f'{MEMPOOL_API_URL}/address/{address}/txs'
    try:
        response = requests.get(url)
        return response.json() if response.status_code == 200 else []
    except requests.RequestException:
        return []

# Funzione per ottenere dettagli di una transazione
def get_transaction_details(txid):
    url = f'{MEMPOOL_API_URL}/tx/{txid}'
    try:
        response = requests.get(url)
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        return None

# Funzione async per terminare la conversazione e avviare il nuovo comando
async def end_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message and update.message.text.startswith('/'):
        command = update.message.text.split()[0]
        if command in COMMAND_MAP:
            await update.message.reply_text(f'Conversazione precedente terminata. Avvio del comando: {command}')
            await globals()[COMMAND_MAP[command]](update, context)
        else:
            await update.message.reply_text(f'Comando non riconosciuto: {command}')
    context.user_data.clear()
    return ConversationHandler.END

# Comando /track_send
async def track_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text('Inserisci l\'indirizzo BTC da monitorare per invii:')
    return SEND_ADDRESS_INPUT

async def set_send_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    if not is_valid_bitcoin_address(address):
        await update.message.reply_text('Indirizzo non valido. Riprova.')
        return SEND_ADDRESS_INPUT
    user_id = str(update.effective_user.id)
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    c = conn.cursor()
    c.execute('INSERT INTO address_subscriptions VALUES (?, ?, ?)', (user_id, address, 'send'))
    conn.commit()
    conn.close()
    await update.message.reply_text(f'Monitoraggio invio avviato per {address}.')
    return ConversationHandler.END

# Comando /track_receive
async def track_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text('Inserisci l\'indirizzo BTC da monitorare per ricezioni:')
    return RECEIVE_ADDRESS_INPUT

async def set_receive_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    if not is_valid_bitcoin_address(address):
        await update.message.reply_text('Indirizzo non valido. Riprova.')
        return RECEIVE_ADDRESS_INPUT
    user_id = str(update.effective_user.id)
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    c = conn.cursor()
    c.execute('INSERT INTO address_subscriptions VALUES (?, ?, ?)', (user_id, address, 'receive'))
    conn.commit()
    conn.close()
    await update.message.reply_text(f'Monitoraggio ricezione avviato per {address}.')
    return ConversationHandler.END

# Comando /track_tx
async def track_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text('Inserisci l\'ID della transazione (txid):')
    return TX_ID_INPUT

async def set_tx_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txid = update.message.text.strip()
    if not is_valid_txid(txid):
        await update.message.reply_text('TxID non valido. Riprova.')
        return TX_ID_INPUT
    context.user_data['txid'] = txid
    await update.message.reply_text('Numero di conferme desiderate?')
    return TX_CONFIRMATIONS_INPUT

async def set_tx_confirmations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        confirmations = int(update.message.text)
        if confirmations <= 0:
            await update.message.reply_text('Numero positivo richiesto.')
            return TX_CONFIRMATIONS_INPUT
        user_id = str(update.effective_user.id)
        txid = context.user_data['txid']
        conn = sqlite3.connect('subscriptions.db')
        conn.execute(f"PRAGMA key = '{DB_KEY}'")
        c = conn.cursor()
        c.execute('INSERT INTO tx_subscriptions VALUES (?, ?, ?)', (user_id, txid, confirmations))
        conn.commit()
        conn.close()
        await update.message.reply_text(f'Monitoraggio tx {txid} per {confirmations} conferme.')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Numero non valido. Riprova.')
        return TX_CONFIRMATIONS_INPUT

# Monitoraggio indirizzi
async def monitor_addresses(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    c = conn.cursor()
    c.execute('SELECT DISTINCT user_id, address, type FROM address_subscriptions')
    subscriptions = c.fetchall()
    for user_id, address, sub_type in subscriptions:
        txs = get_address_transactions(address)
        for tx in txs:
            txid = tx['txid']
            c.execute('SELECT 1 FROM notified_transactions WHERE user_id = ? AND txid = ?', (user_id, txid))
            if c.fetchone():
                continue
            tx_details = get_transaction_details(txid)
            if tx_details and tx_details.get('status', {}).get('confirmed', False):
                block_time = datetime.fromtimestamp(tx_details["status"]["block_time"]).strftime('%Y-%m-%d %H:%M:%S')
                if sub_type == 'send' and any(inp['prevout']['scriptpubkey_address'] == address for inp in tx_details.get('vin', [])):
                    await context.bot.send_message(chat_id=user_id, text=f'Invio da {address}: {txid} il {block_time}')
                    c.execute('INSERT INTO notified_transactions VALUES (?, ?)', (user_id, txid))
                elif sub_type == 'receive' and any(out['scriptpubkey_address'] == address for out in tx_details.get('vout', [])):
                    await context.bot.send_message(chat_id=user_id, text=f'Ricezione su {address}: {txid} il {block_time}')
                    c.execute('INSERT INTO notified_transactions VALUES (?, ?)', (user_id, txid))
        conn.commit()
    conn.close()

# Monitoraggio transazioni
async def monitor_transactions(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    c = conn.cursor()
    c.execute('SELECT user_id, txid, confirmations FROM tx_subscriptions')
    subscriptions = c.fetchall()
    for user_id, txid, target_confirmations in subscriptions:
        tx_details = get_transaction_details(txid)
        if tx_details and tx_details.get('status', {}).get('confirmed', False):
            block_height = tx_details['status'].get('block_height', 0)
            try:
                latest_block_height = requests.get(f'{MEMPOOL_API_URL}/blocks/tip/height').json()
                confirmations = latest_block_height - block_height + 1
                if confirmations >= target_confirmations:
                    block_time = datetime.fromtimestamp(tx_details["status"]["block_time"]).strftime('%Y-%m-%d %H:%M:%S')
                    await context.bot.send_message(chat_id=user_id, text=f'Tx {txid} ha {confirmations} conferme il {block_time}')
                    c.execute('DELETE FROM tx_subscriptions WHERE user_id = ? AND txid = ?', (user_id, txid))
                    conn.commit()
            except (requests.RequestException, ValueError):
                continue
    conn.close()

# Ottenere fee dalla mempool
def get_mempool_fees():
    url = f'{MEMPOOL_API_URL}/v1/fees/recommended'
    try:
        response = requests.get(url)
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        return None

# Comando /set_fee_threshold
async def set_fee_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text('Inserisci la soglia fee (sat/byte):')
    return FEE_THRESHOLD_INPUT

async def set_fee_threshold_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        threshold = float(update.message.text)
        if threshold <= 0:
            await update.message.reply_text('Numero positivo richiesto.')
            return FEE_THRESHOLD_INPUT
        user_id = str(update.effective_user.id)
        conn = sqlite3.connect('subscriptions.db')
        conn.execute(f"PRAGMA key = '{DB_KEY}'")
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO fee_thresholds VALUES (?, ?)', (user_id, threshold))
        conn.commit()
        conn.close()
        await update.message.reply_text(f'Soglia fee impostata a {threshold} sat/byte.')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Numero non valido. Riprova.')
        return FEE_THRESHOLD_INPUT

# Comando /current_fees
async def current_fees(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    fees = get_mempool_fees()
    if fees:
        response = (
            f'Fee attuali:\n'
            f'- Bassa: {fees["hourFee"]} sat/byte\n'
            f'- Media: {fees["halfHourFee"]} sat/byte\n'
            f'- Alta: {fees["fastestFee"]} sat/byte'
        )
        await update.message.reply_text(response)
    else:
        await update.message.reply_text('Impossibile ottenere le fee.')

# Monitoraggio fee
async def monitor_fees(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    c = conn.cursor()
    c.execute('SELECT user_id, threshold FROM fee_thresholds')
    thresholds = c.fetchall()
    fees = get_mempool_fees()
    if fees:
        current_fee = fees['halfHourFee']
        for user_id, threshold in thresholds:
            if current_fee < threshold:
                await context.bot.send_message(chat_id=user_id, text=f'Fee scese a {current_fee} sat/byte (sotto {threshold})')
                c.execute('DELETE FROM fee_thresholds WHERE user_id = ? AND threshold = ?', (user_id, threshold))
                conn.commit()
    conn.close()

# Comando /delete_my_data
async def delete_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = str(update.effective_user.id)
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    c = conn.cursor()
    c.execute('DELETE FROM address_subscriptions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM fee_thresholds WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM tx_subscriptions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM notified_transactions WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text('Dati cancellati.')

# Comando /list_monitors
async def list_monitors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    c = conn.cursor()
    c.execute('SELECT address, type FROM address_subscriptions WHERE user_id = ?', (user_id,))
    address_subs = c.fetchall()
    c.execute('SELECT txid, confirmations FROM tx_subscriptions WHERE user_id = ?', (user_id,))
    tx_subs = c.fetchall()
    c.execute('SELECT threshold FROM fee_thresholds WHERE user_id = ?', (user_id,))
    fee_thresholds = c.fetchall()
    conn.close()

    all_monitors = []
    if address_subs:
        all_monitors.extend([('address', addr, typ) for addr, typ in address_subs])
    if tx_subs:
        all_monitors.extend([('tx', txid, conf) for txid, conf in tx_subs])
    if fee_thresholds:
        all_monitors.extend([('fee', threshold[0], None) for threshold in fee_thresholds])

    if not all_monitors:
        await update.message.reply_text('Nessun monitoraggio attivo.')
        return

    # Costruzione del messaggio con sezioni separate e spazi tra di esse
    message = 'Monitoraggi attivi:\n'
    index = 1

    # Sezione Indirizzi
    if any(m[0] == 'address' for m in all_monitors):
        message += 'Indirizzi:\n'
        for typ, val1, val2 in all_monitors:
            if typ == 'address':
                message += f'{index}. {val1}, Tipo: {val2}\n'
                index += 1
        message += '\n'  # Spazio tra sezioni

    # Sezione Transazioni
    if any(m[0] == 'tx' for m in all_monitors):
        message += 'Transazioni:\n'
        for typ, val1, val2 in all_monitors:
            if typ == 'tx':
                message += f'{index}. {val1}, Conferme: {val2}\n'
                index += 1
        message += '\n'  # Spazio tra sezioni

    # Sezione Soglie fee
    if any(m[0] == 'fee' for m in all_monitors):
        message += 'Soglie fee:\n'
        for typ, val1, _ in all_monitors:
            if typ == 'fee':
                message += f'{index}. {val1} sat/byte\n'
                index += 1

    await update.message.reply_text(message)

# Comando /delete_monitor
async def delete_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = str(update.effective_user.id)
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    c = conn.cursor()
    c.execute('SELECT address, type FROM address_subscriptions WHERE user_id = ?', (user_id,))
    address_subs = c.fetchall()
    c.execute('SELECT txid, confirmations FROM tx_subscriptions WHERE user_id = ?', (user_id,))
    tx_subs = c.fetchall()
    c.execute('SELECT threshold FROM fee_thresholds WHERE user_id = ?', (user_id,))
    fee_thresholds = c.fetchall()
    conn.close()

    all_monitors = []
    if address_subs:
        all_monitors.extend([('address', addr, typ) for addr, typ in address_subs])
    if tx_subs:
        all_monitors.extend([('tx', txid, conf) for txid, conf in tx_subs])
    if fee_thresholds:
        all_monitors.extend([('fee', threshold[0], None) for threshold in fee_thresholds])

    if not all_monitors:
        await update.message.reply_text('Nessun monitoraggio da cancellare.')
        return ConversationHandler.END

    # Costruzione del messaggio con sezioni separate e spazi tra di esse
    message = 'Monitoraggi attivi:\n'
    index = 1

    # Sezione Indirizzi
    if any(m[0] == 'address' for m in all_monitors):
        message += 'Indirizzi:\n'
        for typ, val1, val2 in all_monitors:
            if typ == 'address':
                message += f'{index}. {val1}, Tipo: {val2}\n'
                index += 1
        message += '\n'  # Spazio tra sezioni

    # Sezione Transazioni
    if any(m[0] == 'tx' for m in all_monitors):
        message += 'Transazioni:\n'
        for typ, val1, val2 in all_monitors:
            if typ == 'tx':
                message += f'{index}. {val1}, Conferme: {val2}\n'
                index += 1
        message += '\n'  # Spazio tra sezioni

    # Sezione Soglie fee
    if any(m[0] == 'fee' for m in all_monitors):
        message += 'Soglie fee:\n'
        for typ, val1, _ in all_monitors:
            if typ == 'fee':
                message += f'{index}. {val1} sat/byte\n'
                index += 1

    context.user_data['all_monitors'] = all_monitors
    await update.message.reply_text(message + '\nInserisci il numero da cancellare:')
    return DELETE_MONITOR_INPUT

async def set_delete_monitor_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        monitor_number = int(update.message.text) - 1
        all_monitors = context.user_data.get('all_monitors', [])
        if monitor_number < 0 or monitor_number >= len(all_monitors):
            await update.message.reply_text('Numero non valido. Riprova.')
            return DELETE_MONITOR_INPUT
        typ, val1, val2 = all_monitors[monitor_number]
        user_id = str(update.effective_user.id)
        conn = sqlite3.connect('subscriptions.db')
        conn.execute(f"PRAGMA key = '{DB_KEY}'")
        c = conn.cursor()
        if typ == 'address':
            c.execute('DELETE FROM address_subscriptions WHERE user_id = ? AND address = ? AND type = ?', (user_id, val1, val2))
        elif typ == 'tx':
            c.execute('DELETE FROM tx_subscriptions WHERE user_id = ? AND txid = ?', (user_id, val1))
        elif typ == 'fee':
            c.execute('DELETE FROM fee_thresholds WHERE user_id = ? AND threshold = ?', (user_id, val1))
        conn.commit()
        conn.close()
        await update.message.reply_text(f'Monitoraggio {typ} cancellato.')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Numero non valido. Riprova.')
        return DELETE_MONITOR_INPUT

# Configurazione e avvio del bot
def main():
    init_db()
    application = Application.builder().token(TOKEN).build()

    # Handler per /track_send
    send_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('track_send', track_send)],
        states={SEND_ADDRESS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_send_address)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    )

    # Handler per /track_receive
    receive_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('track_receive', track_receive)],
        states={RECEIVE_ADDRESS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_receive_address)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    )

    # Handler per /track_tx
    tx_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('track_tx', track_tx)],
        states={
            TX_ID_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_tx_id)],
            TX_CONFIRMATIONS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_tx_confirmations)],
        },
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    )

    # Handler per /set_fee_threshold
    fee_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('set_fee_threshold', set_fee_threshold)],
        states={FEE_THRESHOLD_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_fee_threshold_value)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    )

    # Handler per /delete_monitor
    delete_monitor_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('delete_monitor', delete_monitor)],
        states={DELETE_MONITOR_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_delete_monitor_number)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    )

    # Aggiunta degli handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(send_conv_handler)
    application.add_handler(receive_conv_handler)
    application.add_handler(tx_conv_handler)
    application.add_handler(fee_conv_handler)
    application.add_handler(delete_monitor_conv_handler)
    application.add_handler(CommandHandler("current_fees", current_fees))
    application.add_handler(CommandHandler("list_monitors", list_monitors))
    application.add_handler(CommandHandler("delete_my_data", delete_my_data))
    application.add_handler(CommandHandler("donate", donate))

    # Configurazione job di monitoraggio
    application.job_queue.run_repeating(monitor_addresses, interval=300, first=0)
    application.job_queue.run_repeating(monitor_fees, interval=300, first=0)
    application.job_queue.run_repeating(monitor_transactions, interval=300, first=0)

    # Avvio bot
    application.run_polling()

if __name__ == '__main__':
    main()