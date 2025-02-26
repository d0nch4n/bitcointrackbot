# Bitcoin Track Bot v.1.1
# Copyright (C) 2025 (d0nch4n)
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

import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters, JobQueue, ContextTypes
import requests
from sqlcipher3 import dbapi2 as sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv
import re
from bech32 import decode

# Carica le variabili dal file .env
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

# URL base dell'API pubblica di Mempool.space
MEMPOOL_API_URL = 'https://mempool.space/api'

# Stati per le conversazioni
SEND_ADDRESS_INPUT = 1
RECEIVE_ADDRESS_INPUT = 2
TX_ID_INPUT = 3
TX_CONFIRMATIONS_INPUT = 4
FEE_THRESHOLD_INPUT = 5

    # Funzione per validare indirizzi Bitcoin
def is_valid_bitcoin_address(address):
    # Controllo Legacy e P2SH con regex
    if re.match(r'^(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}$', address):
        return True
    # Controllo Bech32/Bech32m (SegWit e Taproot)
    if address.startswith('bc1'):
        try:
            # Decodifica l'indirizzo
            hrp, data = decode('bc', address)
            # Verifica che hrp sia un numero intero (0 per SegWit v0, 1 per Taproot)
            if isinstance(hrp, int):
                if hrp == 0 and address.startswith('bc1q') and len(address) == 42:
                    return True  # SegWit v0 (P2WPKH)
                elif hrp == 1 and address.startswith('bc1p') and len(address) == 62:
                    return True  # Taproot (P2TR)
            return False
        except ValueError:
            return False
    return False

# Funzione per validare ID transazioni
def is_valid_txid(txid):
    return len(txid) == 64 and all(c in '0123456789abcdefABCDEF' for c in txid)

# Inizializzazione del database SQLite per salvare le sottoscrizioni
def init_db():
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")  # Imposta la chiave
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS address_subscriptions (user_id TEXT, address TEXT, type TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS fee_thresholds (user_id TEXT, threshold REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS tx_subscriptions (user_id TEXT, txid TEXT, confirmations INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS notified_transactions (user_id TEXT, txid TEXT)')  # Nuova tabella
    conn.commit()
    conn.close()

# Comando /start: mostra i comandi disponibili
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Ciao! Usa i seguenti comandi:\n'
        '/track_send - Monitora quando un indirizzo invia BTC\n'
        '/track_receive - Monitora quando un indirizzo riceve BTC\n'
        '/track_tx - Monitora una transazione per conferme specifiche\n'
        '/set_fee_threshold - Imposta una soglia per le fee (priorità media)\n'
        '/current_fees - Mostra le fee attuali (bassa, media, alta priorità)\n'
        '/delete_my_data - Cancella tutti i tuoi dati dal database\n'
        '/donate - Sostieni il progetto con una donazione'
    )

# Funzione per il comando /donate
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    donation_message = (
        "Grazie per voler supportare il Bitcoin Track Bot! ❤️\n\n"
        "Puoi donare Bitcoin usando una transazione Lightning:\n"
        f"   `{LIGHTNING_ADDRESS}`\n\n"
        "Ogni contributo aiuta a mantenere il bot attivo e a migliorarlo!"
    )
    await update.message.reply_text(donation_message, parse_mode='Markdown')

# Funzione per ottenere le transazioni di un indirizzo con gestione eccezioni
def get_address_transactions(address):
    url = f'{MEMPOOL_API_URL}/address/{address}/txs'
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return []
    except requests.exceptions.RequestException:
        return []

# Funzione per ottenere i dettagli di una transazione con gestione eccezioni
def get_transaction_details(txid):
    url = f'{MEMPOOL_API_URL}/tx/{txid}'
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return None
    except requests.exceptions.RequestException:
        return None

# Comando /track_send: inizia la conversazione per monitorare un indirizzo per gli invii
async def track_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Inserisci l\'indirizzo Bitcoin da monitorare per gli invii:')
    return SEND_ADDRESS_INPUT

# Gestione dell'input dell'indirizzo per /track_send con validazione
async def set_send_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    if not is_valid_bitcoin_address(address):
        await update.message.reply_text('Errore: indirizzo Bitcoin non valido. Riprova.')
        return SEND_ADDRESS_INPUT
    user_id = str(update.message.from_user.id)
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")  # Imposta la chiave
    c = conn.cursor()
    c.execute('INSERT INTO address_subscriptions VALUES (?, ?, ?)', (user_id, address, 'send'))
    conn.commit()
    conn.close()
    await update.message.reply_text(f'Monitoraggio invio avviato per l\'indirizzo {address}.')
    return ConversationHandler.END

# Comando /track_receive: inizia la conversazione per monitorare un indirizzo per le ricezioni
async def track_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Inserisci l\'indirizzo Bitcoin da monitorare per le ricezioni:')
    return RECEIVE_ADDRESS_INPUT

# Gestione dell'input dell'indirizzo per /track_receive con validazione
async def set_receive_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    if not is_valid_bitcoin_address(address):
        await update.message.reply_text('Errore: indirizzo Bitcoin non valido. Riprova.')
        return RECEIVE_ADDRESS_INPUT
    user_id = str(update.message.from_user.id)
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")  # Imposta la chiave
    c = conn.cursor()
    c.execute('INSERT INTO address_subscriptions VALUES (?, ?, ?)', (user_id, address, 'receive'))
    conn.commit()
    conn.close()
    await update.message.reply_text(f'Monitoraggio ricezione avviato per l\'indirizzo {address}.')
    return ConversationHandler.END

# Comando /track_tx: inizia la conversazione per monitorare una transazione
async def track_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Inserisci l\'ID della transazione (txid) da monitorare:')
    return TX_ID_INPUT

# Gestione dell'input del txid per /track_tx con validazione
async def set_tx_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txid = update.message.text.strip()
    if not is_valid_txid(txid):
        await update.message.reply_text('Errore: ID transazione non valido. Deve essere una stringa esadecimale di 64 caratteri.')
        return TX_ID_INPUT
    context.user_data['txid'] = txid
    await update.message.reply_text('Quante conferme desideri prima di ricevere la notifica? (Inserisci un numero)')
    return TX_CONFIRMATIONS_INPUT

# Gestione dell'input delle conferme per /track_tx
async def set_tx_confirmations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        confirmations = int(update.message.text)
        if confirmations <= 0:
            await update.message.reply_text('Errore: inserisci un numero positivo.')
            return TX_CONFIRMATIONS_INPUT
        user_id = str(update.message.from_user.id)
        txid = context.user_data['txid']
        conn = sqlite3.connect('subscriptions.db')
        conn.execute(f"PRAGMA key = '{DB_KEY}'")  # Imposta la chiave
        c = conn.cursor()
        c.execute('INSERT INTO tx_subscriptions VALUES (?, ?, ?)', (user_id, txid, confirmations))
        conn.commit()
        conn.close()
        await update.message.reply_text(f'Monitoraggio avviato per la transazione {txid}. Riceverai una notifica a {confirmations} conferme.')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Errore: inserisci un numero valido.')
        return TX_CONFIRMATIONS_INPUT

# Funzione di monitoraggio degli indirizzi sottoscritti con tracciamento delle transazioni notificate
async def monitor_addresses(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")  # Imposta la chiave
    c = conn.cursor()
    c.execute('SELECT DISTINCT user_id, address, type FROM address_subscriptions')
    subscriptions = c.fetchall()
    for user_id, address, sub_type in subscriptions:
        txs = get_address_transactions(address)
        for tx in txs:
            txid = tx['txid']
            # Controlla se la transazione è già stata notificata
            c.execute('SELECT 1 FROM notified_transactions WHERE user_id = ? AND txid = ?', (user_id, txid))
            if c.fetchone():
                continue  # Salta se già notificata
            tx_details = get_transaction_details(txid)
            if tx_details and tx_details.get('status', {}).get('confirmed', False):
                # Controlla se l'indirizzo è mittente (input)
                if sub_type == 'send' and any(inp['prevout']['scriptpubkey_address'] == address for inp in tx_details.get('vin', [])):
                    block_time = datetime.fromtimestamp(tx_details["status"]["block_time"]).strftime('%Y-%m-%d %H:%M:%S')
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f'L\'indirizzo {address} ha inviato una transazione!\nTx: {txid}\nData: {block_time}'
                    )
                    c.execute('INSERT INTO notified_transactions VALUES (?, ?)', (user_id, txid))
                # Controlla se l'indirizzo è destinatario (output)
                elif sub_type == 'receive' and any(out['scriptpubkey_address'] == address for out in tx_details.get('vout', [])):
                    block_time = datetime.fromtimestamp(tx_details["status"]["block_time"]).strftime('%Y-%m-%d %H:%M:%S')
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f'L\'indirizzo {address} ha ricevuto una transazione!\nTx: {txid}\nData: {block_time}'
                    )
                    c.execute('INSERT INTO notified_transactions VALUES (?, ?)', (user_id, txid))
        conn.commit()  # Commit dopo aver processato tutte le transazioni per questa sottoscrizione
    conn.close()

# Funzione di monitoraggio delle transazioni con conferme
async def monitor_transactions(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")  # Imposta la chiave
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
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f'La transazione {txid} ha raggiunto {confirmations} conferme!\nData: {block_time}'
                    )
                    c.execute('DELETE FROM tx_subscriptions WHERE user_id = ? AND txid = ?', (user_id, txid))
                    conn.commit()
            except (requests.exceptions.RequestException, ValueError):
                continue  # Salta questa iterazione in caso di errore
    conn.close()

# Funzione per ottenere le fee attuali della mempool con gestione eccezioni
def get_mempool_fees():
    url = f'{MEMPOOL_API_URL}/v1/fees/recommended'
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return None
    except requests.exceptions.RequestException:
        return None

# Comando /set_fee_threshold: inizia la conversazione per impostare la soglia
async def set_fee_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Inserisci la soglia per le fee (sat/byte) per la priorità media (conferma entro ~30 min):')
    return FEE_THRESHOLD_INPUT

# Gestione dell'input della soglia per /set_fee_threshold
async def set_fee_threshold_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        threshold = float(update.message.text)
        if threshold <= 0:
            await update.message.reply_text('Errore: inserisci un numero positivo.')
            return FEE_THRESHOLD_INPUT
        user_id = str(update.message.from_user.id)
        conn = sqlite3.connect('subscriptions.db')
        conn.execute(f"PRAGMA key = '{DB_KEY}'")  # Imposta la chiave
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO fee_thresholds VALUES (?, ?)', (user_id, threshold))
        conn.commit()
        conn.close()
        await update.message.reply_text(f'Soglia fee impostata a {threshold} sat/byte per priorità media.')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Errore: inserisci un numero valido.')
        return FEE_THRESHOLD_INPUT

# Comando /current_fees: mostra le fee attuali per tutte le priorità
async def current_fees(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fees = get_mempool_fees()
    if fees:
        response = (
            f'Fee attuali della mempool (sat/byte):\n'
            f'- Bassa priorità (~1-3 ora): {fees["hourFee"]}\n'
            f'- Media priorità (~30 min): {fees["halfHourFee"]}\n'
            f'- Alta priorità (~10 min): {fees["fastestFee"]}'
        )
        await update.message.reply_text(response)
    else:
        await update.message.reply_text('Errore: impossibile ottenere le fee.')

# Funzione di monitoraggio delle fee (priorità media) con stop alla prima notifica
async def monitor_fees(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")  # Imposta la chiave
    c = conn.cursor()
    c.execute('SELECT user_id, threshold FROM fee_thresholds')
    thresholds = c.fetchall()
    fees = get_mempool_fees()
    if fees:
        current_fee = fees['halfHourFee']  # Priorità media
        for user_id, threshold in thresholds:
            if current_fee < threshold:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f'Le fee (priorità media) sono scese a {current_fee} sat/byte, '
                        f'sotto la tua soglia di {threshold}!\n\n'
                        'Il monitoraggio per questa soglia è stato disattivato. '
                        'Usa /set_fee_threshold per impostarne una nuova.'
                    )
                )
                # Rimuovi la soglia dal database per l'utente
                c.execute('DELETE FROM fee_thresholds WHERE user_id = ?', (user_id,))
                conn.commit()
    conn.close()

# Comando /delete_my_data: cancella i dati dell'utente
async def delete_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    conn = sqlite3.connect('subscriptions.db')
    conn.execute(f"PRAGMA key = '{DB_KEY}'")  # Imposta la chiave
    c = conn.cursor()
    c.execute('DELETE FROM address_subscriptions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM fee_thresholds WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM tx_subscriptions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM notified_transactions WHERE user_id = ?', (user_id,))  # Cancella anche le transazioni notificate
    conn.commit()
    conn.close()
    await update.message.reply_text('Tutti i tuoi dati sono stati cancellati dal database.')

# Configurazione e avvio del bot
def main():
    init_db()
    
    # Crea l'applicazione
    application = Application.builder().token(TOKEN).build()

    # Conversazione per /track_send
    send_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('track_send', track_send)],
        states={
            SEND_ADDRESS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_send_address)],
        },
        fallbacks=[]
    )

    # Conversazione per /track_receive
    receive_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('track_receive', track_receive)],
        states={
            RECEIVE_ADDRESS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_receive_address)],
        },
        fallbacks=[]
    )

    # Conversazione per /track_tx
    tx_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('track_tx', track_tx)],
        states={
            TX_ID_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_tx_id)],
            TX_CONFIRMATIONS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_tx_confirmations)],
        },
        fallbacks=[]
    )

    # Conversazione per /set_fee_threshold
    fee_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('set_fee_threshold', set_fee_threshold)],
        states={
            FEE_THRESHOLD_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_fee_threshold_value)],
        },
        fallbacks=[]
    )

    # Registrazione dei comandi e conversazioni
    application.add_handler(CommandHandler("start", start))
    application.add_handler(send_conv_handler)
    application.add_handler(receive_conv_handler)
    application.add_handler(tx_conv_handler)
    application.add_handler(fee_conv_handler)
    application.add_handler(CommandHandler("current_fees", current_fees))
    application.add_handler(CommandHandler("delete_my_data", delete_my_data))
    application.add_handler(CommandHandler("donate", donate))

    # Avvio dei job di monitoraggio (ogni 5 minuti = 300 secondi)
    application.job_queue.run_repeating(monitor_addresses, interval=300, first=0)
    application.job_queue.run_repeating(monitor_fees, interval=300, first=0)
    application.job_queue.run_repeating(monitor_transactions, interval=300, first=0)

    # Avvio del bot con polling
    application.run_polling()

if __name__ == '__main__':
    main()