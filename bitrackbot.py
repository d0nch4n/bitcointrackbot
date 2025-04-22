# Bitcoin Track Bot v.1.4.1
# Copyright (C) 2025 d0nch4n
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
# Thanks to Pieter Wuille for his segwit_addr.py program useful for Taproot checksum verify

import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters, ContextTypes
import requests
from sqlcipher3 import dbapi2 as sqlite3
import os
from datetime import datetime, timedelta, timezone
from time import time, sleep
from dotenv import load_dotenv
import re
from segwit_addr import decode as segwit_decode

# Caricamento delle variabili d'ambiente
load_dotenv()
TOKEN = os.getenv('TELEGRAM_TOKEN')
DB_KEY = os.getenv('DB_KEY')
LIGHTNING_ADDRESS = os.getenv('LIGHTNING_ADDRESS')

if not TOKEN or not DB_KEY or not LIGHTNING_ADDRESS:
    raise ValueError("Variabili d'ambiente TELEGRAM_TOKEN, DB_KEY o LIGHTNING_ADDRESS non definite nel file .env.")

# URL base dell'API di Mempool.space
MEMPOOL_API_URL = 'https://mempool.space/api'

# Stati per le conversazioni
SEND_ADDRESS_INPUT = 1
RECEIVE_ADDRESS_INPUT = 2
TX_ID_INPUT = 3
TX_CONFIRMATIONS_INPUT = 4
FEE_THRESHOLD_INPUT = 5
DELETE_MONITOR_INPUT = 6
SEND_ADDRESS_INPUT_MEMPOOL = 7
RECEIVE_ADDRESS_INPUT_MEMPOOL = 8
TX_FEE_INPUT = 9
FREQUENCY_INPUT = 10
CURRENCY_INPUT = 11
PRICE_THRESHOLD_CURRENCY_INPUT = 12
PRICE_THRESHOLD_VALUE_INPUT = 13
CONVERT_CHOICE = 14
CONVERT_AMOUNT = 15

# Mappa dei comandi
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
    '/recent_blocks': 'recent_blocks',
    '/fee_forecast': 'fee_forecast',
    '/tx_fee': 'tx_fee',
    '/status': 'status',
    '/track_send_mempool': 'track_send_mempool',
    '/track_receive_mempool': 'track_receive_mempool',
    '/track_solo_miner': 'track_solo_miner',
    '/price': 'current_price',
    '/set_price_alert': 'set_price_alert',
    '/set_price_threshold': 'set_price_threshold',
    '/convert': 'convert',
}


# Connessione persistente al database
DB_CONN = sqlite3.connect('subscriptions.db')
DB_CONN.execute(f"PRAGMA key = '{DB_KEY}'")

# Funzioni di validazione
def is_valid_bitcoin_address(address):
    """Valida un indirizzo Bitcoin (legacy, SegWit o Taproot)."""
    address = re.sub(r'[^a-zA-Z0-9]', '', address)  # Sanitizzazione
    if re.match(r'^(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}$', address):
        return True
    if address.startswith('bc1'):
        try:
            result = segwit_decode('bc', address)
            if result is None:
                return False
            version, data = result
            return (version == 0 and len(address) == 42 and address.startswith('bc1q')) or \
                   (version == 1 and len(address) == 62 and address.startswith('bc1p'))
        except Exception:
            return False
    return False

def is_valid_txid(txid):
    """Valida un transaction ID (txid) Bitcoin."""
    txid = re.sub(r'[^a-fA-F0-9]', '', txid)  # Sanitizzazione
    return len(txid) == 64 and all(c in '0123456789abcdefABCDEF' for c in txid)

# Inizializzazione del database con indici
def init_db():
    """Inizializza il database con tabelle e indici per migliorare le prestazioni."""
    c = DB_CONN.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS address_subscriptions (user_id TEXT, address TEXT, type TEXT, timestamp INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS fee_thresholds (user_id TEXT, threshold REAL, direction TEXT, notified INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS tx_subscriptions (user_id TEXT, txid TEXT, confirmations INTEGER, timestamp INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS notified_transactions (user_id TEXT, txid TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS mempool_address_subscriptions (user_id TEXT, address TEXT, type TEXT, timestamp INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS notified_mempool_transactions (user_id TEXT, txid TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS solo_miner_subscriptions (user_id TEXT, last_checked_height INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS price_thresholds (user_id TEXT, currency TEXT, threshold REAL, notified INTEGER, direction TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS price_alerts (user_id TEXT PRIMARY KEY, frequency TEXT, currency TEXT, next_notification_time INTEGER)')
    # Aggiunta di indici per velocizzare le query
    c.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON address_subscriptions(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_address ON address_subscriptions(address)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_txid ON tx_subscriptions(txid)')
    DB_CONN.commit()

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra il messaggio di benvenuto con l'elenco dei comandi disponibili."""
    await update.message.reply_text(
        'Ciao! Usa i seguenti comandi:\n'
        '/track_send <indirizzo> - Monitora invii BTC\n'
        '/track_receive <indirizzo> - Monitora ricezioni BTC\n'
        '/track_send_mempool <indirizzo> - Monitora invii non confermati\n'
        '/track_receive_mempool <indirizzo> - Monitora ricezioni non confermate\n'
        '/track_tx <txid> - Monitora transazioni\n'
        '/tx_fee <txid> - Calcola fee transazione\n'
        '/current_fees - Fee attuali\n'
        '/set_fee_threshold <soglia> - Imposta soglia fee\n'
        '/fee_forecast - Previsioni fee\n'
        '/recent_blocks - Statistiche blocchi recenti\n'
        '/status - Stato della rete\n'
        '/track_solo_miner - Monitora blocchi da solo miner\n'
        '/price - Ottieni il prezzo attuale di Bitcoin\n'
        '/set_price_alert - Imposta notifiche periodiche del prezzo\n'
        '/set_price_threshold - Imposta soglia di prezzo per notifiche\n'
        '/convert <importo> <valuta> - Converti EUR/USD in sats o sats in EUR/USD\n'
        '/list_monitors - Lista monitoraggi attivi\n'
        '/delete_monitor - Cancella un monitoraggio attivo\n'
        '/delete_my_data - Cancella tutti i miei dati\n'
        '/donate - Sostieni il progetto'
    )

# Comando /donate
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra l'indirizzo Lightning per donazioni."""
    await update.message.reply_text(
        f"Supporta il bot! ❤️\n\nLightning: `{LIGHTNING_ADDRESS}`\n\nGrazie!",
        parse_mode='Markdown'
    )

# Funzioni API Mempool con cache e rate limiting
TX_CACHE = {}
LAST_API_CALL = 0

def get_address_transactions(address):
    """Recupera le transazioni confermate di un indirizzo con cache."""
    global LAST_API_CALL
    try:
        if address in TX_CACHE and time() - TX_CACHE[address]['timestamp'] < 300:
            return TX_CACHE[address]['data']
        if time() - LAST_API_CALL < 1:
            sleep(1 - (time() - LAST_API_CALL))
        LAST_API_CALL = time()
        response = requests.get(f'{MEMPOOL_API_URL}/address/{address}/txs')
        data = response.json() if response.status_code == 200 else []
        TX_CACHE[address] = {'data': data, 'timestamp': time()}
        return data
    except requests.RequestException:
        return []

def get_mempool_transactions(address):
    """Recupera le transazioni non confermate di un indirizzo."""
    try:
        response = requests.get(f'{MEMPOOL_API_URL}/address/{address}/txs/mempool')
        return response.json() if response.status_code == 200 else []
    except requests.RequestException:
        return []

def get_transaction_details(txid):
    """Recupera i dettagli di una transazione specifica."""
    try:
        response = requests.get(f'{MEMPOOL_API_URL}/tx/{txid}')
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        return None

def get_last_block_height():
    """Ottiene l'altezza dell'ultimo blocco."""
    try:
        response = requests.get(f'{MEMPOOL_API_URL}/blocks/tip/height')
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        return None

def get_block_details(height):
    """Recupera i dettagli di un blocco specifico."""
    try:
        response = requests.get(f'{MEMPOOL_API_URL}/block/{height}')
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        return None

def get_block_miner(block_details):
    """Estrae il nome del miner da un blocco."""
    return block_details.get('extras', {}).get('pool', {}).get('name', 'Unknown')

def get_mempool_fees():
    """Ottiene le fee raccomandate dalla mempool."""
    try:
        response = requests.get(f'{MEMPOOL_API_URL}/v1/fees/recommended')
        return response.json() if response.status_code == 200 else None
    except requests.RequestException:
        return None

def get_mempool_size():
    """Ottiene il numero di transazioni nella mempool."""
    try:
        response = requests.get(f'{MEMPOOL_API_URL}/mempool')
        return response.json()['count'] if response.status_code == 200 else None
    except requests.RequestException:
        return None

# Funzione per aggiornare la cache dei prezzi
async def update_price_cache(context: ContextTypes.DEFAULT_TYPE):
    """Aggiorna la cache dei prezzi di Bitcoin in EUR e USD."""
    try:
        # Prova con CoinDesk
        response = requests.get('https://api.coindesk.com/v1/bpi/currentprice.json')
        data = response.json()
        context.bot_data['btc_prices']['eur'] = data['bpi']['EUR']['rate_float']
        context.bot_data['btc_prices']['usd'] = data['bpi']['USD']['rate_float']
        context.bot_data['last_price_update'] = time()
    except Exception:
        try:
            # Fallback a Blockchain.com
            response = requests.get('https://blockchain.info/ticker')
            data = response.json()
            context.bot_data['btc_prices']['eur'] = data['EUR']['last']
            context.bot_data['btc_prices']['usd'] = data['USD']['last']
            context.bot_data['last_price_update'] = time()
        except Exception as e:
            print(f"Errore fallback aggiornamento cache prezzi: {e}")

# Gestione conversazioni
async def end_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Termina una conversazione e avvia un nuovo comando se fornito."""
    if update.message.text.startswith('/'):
        command = update.message.text.split()[0]
        if command in COMMAND_MAP:
            await update.message.reply_text(f'Conversazione terminata. Avvio: {command}')
            await globals()[COMMAND_MAP[command]](update, context)
        else:
            await update.message.reply_text(f'Comando non riconosciuto: {command}')
    context.user_data.clear()
    return ConversationHandler.END

# Comando /track_send
async def track_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvia il monitoraggio degli invii da un indirizzo Bitcoin."""
    context.user_data.clear()
    await update.message.reply_text('Inserisci l\'indirizzo BTC da monitorare per invii:')
    return SEND_ADDRESS_INPUT

async def set_send_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta l'indirizzo per il monitoraggio degli invii."""
    address = update.message.text.strip()
    if not is_valid_bitcoin_address(address):
        await update.message.reply_text('Indirizzo non valido. Riprova.')
        return SEND_ADDRESS_INPUT
    user_id = str(update.effective_user.id)
    timestamp = int(time())
    c = DB_CONN.cursor()
    c.execute('INSERT INTO address_subscriptions VALUES (?, ?, ?, ?)', (user_id, address, 'send', timestamp))
    DB_CONN.commit()
    await update.message.reply_text(f'Monitoraggio invio avviato per {address}.')
    return ConversationHandler.END

# Comando /track_receive
async def track_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvia il monitoraggio delle ricezioni su un indirizzo Bitcoin."""
    context.user_data.clear()
    await update.message.reply_text('Inserisci l\'indirizzo BTC da monitorare per ricezioni:')
    return RECEIVE_ADDRESS_INPUT

async def set_receive_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta l'indirizzo per il monitoraggio delle ricezioni."""
    address = update.message.text.strip()
    if not is_valid_bitcoin_address(address):
        await update.message.reply_text('Indirizzo non valido. Riprova.')
        return RECEIVE_ADDRESS_INPUT
    user_id = str(update.effective_user.id)
    timestamp = int(time())
    c = DB_CONN.cursor()
    c.execute('INSERT INTO address_subscriptions VALUES (?, ?, ?, ?)', (user_id, address, 'receive', timestamp))
    DB_CONN.commit()
    await update.message.reply_text(f'Monitoraggio ricezione avviato per {address}.')
    return ConversationHandler.END

# Comando /track_tx
async def track_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvia il monitoraggio di una transazione specifica."""
    context.user_data.clear()
    await update.message.reply_text('Inserisci l\'ID della transazione (txid):')
    return TX_ID_INPUT

async def set_tx_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta il txid per il monitoraggio della transazione."""
    txid = update.message.text.strip()
    if not is_valid_txid(txid):
        await update.message.reply_text('TxID non valido. Riprova.')
        return TX_ID_INPUT
    context.user_data['txid'] = txid
    await update.message.reply_text('Numero di conferme desiderate?')
    return TX_CONFIRMATIONS_INPUT

async def set_tx_confirmations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta il numero di conferme per il monitoraggio della transazione."""
    try:
        confirmations = int(update.message.text)
        if confirmations <= 0:
            await update.message.reply_text('Numero positivo richiesto.')
            return TX_CONFIRMATIONS_INPUT
        user_id = str(update.effective_user.id)
        txid = context.user_data['txid']
        timestamp = int(time())
        c = DB_CONN.cursor()
        c.execute('INSERT INTO tx_subscriptions VALUES (?, ?, ?, ?)', (user_id, txid, confirmations, timestamp))
        DB_CONN.commit()
        await update.message.reply_text(f'Monitoraggio tx {txid} per {confirmations} conferme.')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Numero non valido. Riprova.')
        return TX_CONFIRMATIONS_INPUT

# Funzioni di monitoraggio
async def monitor_addresses(context: ContextTypes.DEFAULT_TYPE):
    """Monitora gli indirizzi per invii e ricezioni confermati."""
    c = DB_CONN.cursor()
    c.execute('SELECT user_id, address, type, timestamp FROM address_subscriptions')
    subscriptions = c.fetchall()
    notified_list = []
    for user_id, address, sub_type, activation_timestamp in subscriptions:
        txs = get_address_transactions(address)
        for tx in txs:
            txid = tx['txid']
            c.execute('SELECT 1 FROM notified_transactions WHERE user_id = ? AND txid = ?', (user_id, txid))
            if c.fetchone():
                continue
            tx_details = get_transaction_details(txid)
            if tx_details and tx_details.get('status', {}).get('confirmed', False):
                block_time = tx_details["status"]["block_time"]
                if block_time < activation_timestamp:
                    continue
                block_time_str = datetime.fromtimestamp(block_time).strftime('%Y-%m-%d %H:%M:%S')
                if sub_type == 'send' and any(inp['prevout']['scriptpubkey_address'] == address for inp in tx_details.get('vin', [])):
                    await context.bot.send_message(chat_id=user_id, text=f'Invio da {address}: {txid} il {block_time_str}')
                    notified_list.append((user_id, txid))
                elif sub_type == 'receive' and any(out['scriptpubkey_address'] == address for out in tx_details.get('vout', [])):
                    await context.bot.send_message(chat_id=user_id, text=f'Ricezione su {address}: {txid} il {block_time_str}')
                    notified_list.append((user_id, txid))
    if notified_list:
        c.executemany('INSERT INTO notified_transactions VALUES (?, ?)', notified_list)
        DB_CONN.commit()

async def monitor_transactions(context: ContextTypes.DEFAULT_TYPE):
    """Monitora le transazioni per il numero di conferme specificato."""
    c = DB_CONN.cursor()
    c.execute('SELECT user_id, txid, confirmations, timestamp FROM tx_subscriptions')
    subscriptions = c.fetchall()
    for user_id, txid, target_confirmations, activation_timestamp in subscriptions:
        tx_details = get_transaction_details(txid)
        if tx_details and tx_details.get('status', {}).get('confirmed', False):
            block_time = tx_details["status"]["block_time"]
            if block_time < activation_timestamp:
                continue
            block_height = tx_details['status'].get('block_height', 0)
            try:
                latest_block_height = requests.get(f'{MEMPOOL_API_URL}/blocks/tip/height').json()
                confirmations = latest_block_height - block_height + 1
                if confirmations >= target_confirmations:
                    block_time_str = datetime.fromtimestamp(block_time).strftime('%Y-%m-%d %H:%M:%S')
                    await context.bot.send_message(chat_id=user_id, text=f'Tx {txid} ha {confirmations} conferme il {block_time_str}.')
                    c.execute('DELETE FROM tx_subscriptions WHERE user_id = ? AND txid = ?', (user_id, txid))
                    DB_CONN.commit()
            except (requests.RequestException, ValueError):
                pass

async def monitor_fees(context: ContextTypes.DEFAULT_TYPE):
    """Monitora le fee medie rispetto alle soglie impostate, considerando la direzione."""
    c = DB_CONN.cursor()
    c.execute('SELECT user_id, threshold, direction FROM fee_thresholds WHERE notified = 0')
    thresholds = c.fetchall()
    fees = get_mempool_fees()
    if fees:
        current_fee = fees['halfHourFee']
        for user_id, threshold, direction in thresholds:
            if (direction == 'below' and current_fee < threshold) or (direction == 'above' and current_fee > threshold):
                await context.bot.send_message(chat_id=user_id,
                                              text=f'La fee media è ora {current_fee} sat/byte, che è {direction} la tua soglia di {threshold} sat/byte.')
                c.execute('UPDATE fee_thresholds SET notified = 1 WHERE user_id = ? AND threshold = ? AND direction = ?',
                          (user_id, threshold, direction))
        DB_CONN.commit()

# Comando /set_fee_threshold
async def set_fee_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta una soglia per le fee medie."""
    context.user_data.clear()
    await update.message.reply_text('Inserisci la soglia fee media (sat/byte):')
    return FEE_THRESHOLD_INPUT

async def set_fee_threshold_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Salva la soglia fee specificata dall'utente, considerando la fee attuale."""
    try:
        threshold = float(update.message.text)
        if threshold <= 0:
            await update.message.reply_text('Numero positivo richiesto.')
            return FEE_THRESHOLD_INPUT
        user_id = str(update.effective_user.id)
        fees = get_mempool_fees()
        if not fees:
            await update.message.reply_text('Impossibile ottenere le fee attuali. Riprova più tardi.')
            return FEE_THRESHOLD_INPUT
        current_fee = fees['halfHourFee']
        # Determina la direzione
        if current_fee < threshold:
            direction = 'above'
            message = f'Soglia fee impostata a {threshold} sat/byte. Riceverai una notifica quando la fee sale sopra questa soglia.'
        else:
            direction = 'below'
            message = f'Soglia fee impostata a {threshold} sat/byte. Riceverai una notifica quando la fee scende sotto questa soglia.'
        c = DB_CONN.cursor()
        c.execute('INSERT OR REPLACE INTO fee_thresholds (user_id, threshold, direction, notified) VALUES (?, ?, ?, 0)',
                  (user_id, threshold, direction))
        DB_CONN.commit()
        await update.message.reply_text(message)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Numero non valido. Riprova.')
        return FEE_THRESHOLD_INPUT

# Comando /current_fees
async def current_fees(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra le fee attuali raccomandate."""
    fees = get_mempool_fees()
    if fees:
        await update.message.reply_text(
            f'Fee attuali:\n'
            f'- Bassa: {fees["hourFee"]} sat/byte\n'
            f'- Media: {fees["halfHourFee"]} sat/byte\n'
            f'- Alta: {fees["fastestFee"]} sat/byte'
        )
    else:
        await update.message.reply_text('Impossibile ottenere le fee.')

# Comando /delete_my_data
async def delete_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancella tutti i dati dell'utente dal database."""
    user_id = str(update.effective_user.id)
    c = DB_CONN.cursor()
    c.execute('DELETE FROM address_subscriptions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM fee_thresholds WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM tx_subscriptions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM notified_transactions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM mempool_address_subscriptions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM notified_mempool_transactions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM solo_miner_subscriptions WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM price_alerts WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM price_thresholds WHERE user_id = ?', (user_id,))
    DB_CONN.commit()
    await update.message.reply_text('Dati cancellati.')

# Comando /list_monitors
async def list_monitors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Elenca tutti i monitoraggi attivi dell'utente."""
    user_id = str(update.effective_user.id)
    c = DB_CONN.cursor()
    c.execute('SELECT address, type FROM address_subscriptions WHERE user_id = ?', (user_id,))
    address_subs = c.fetchall()
    c.execute('SELECT txid, confirmations FROM tx_subscriptions WHERE user_id = ?', (user_id,))
    tx_subs = c.fetchall()
    c.execute('SELECT threshold FROM fee_thresholds WHERE user_id = ?', (user_id,))
    fee_thresholds = c.fetchall()
    c.execute('SELECT address, type FROM mempool_address_subscriptions WHERE user_id = ?', (user_id,))
    mempool_subs = c.fetchall()
    c.execute('SELECT last_checked_height FROM solo_miner_subscriptions WHERE user_id = ?', (user_id,))
    solo_miner_subs = c.fetchall()
    c.execute('SELECT frequency, currency FROM price_alerts WHERE user_id = ?', (user_id,))
    price_alert = c.fetchone()
    c.execute('SELECT currency, threshold FROM price_thresholds WHERE user_id = ? AND notified = 0', (user_id,))
    price_thresholds = c.fetchall()

    all_monitors = []
    if address_subs:
        all_monitors.extend([('address', addr, typ) for addr, typ in address_subs])
    if tx_subs:
        all_monitors.extend([('tx', txid, conf) for txid, conf in tx_subs])
    if fee_thresholds:
        all_monitors.extend([('fee', threshold[0], None) for threshold in fee_thresholds])
    if mempool_subs:
        all_monitors.extend([('mempool', addr, typ) for addr, typ in mempool_subs])
    if solo_miner_subs:
        all_monitors.append(('solo_miner', 'Monitoraggio solo miner', None))
    if price_alert:
        all_monitors.append(('price_alert', price_alert[0], price_alert[1]))
    if price_thresholds:
        all_monitors.extend([('price_threshold', currency, threshold) for currency, threshold in price_thresholds])

    if not all_monitors:
        await update.message.reply_text('Nessun monitoraggio attivo.')
        return

    message = 'Monitoraggi attivi:\n'
    index = 1
    for section, title in [
        ('address', 'Indirizzi (confermate)'),
        ('tx', 'Transazioni'),
        ('fee', 'Soglie fee'),
        ('mempool', 'Indirizzi (non confermate)'),
        ('solo_miner', 'Monitoraggio solo miner'),
        ('price_alert', 'Notifiche prezzo'),
        ('price_threshold', 'Soglie prezzo')
    ]:
        if any(m[0] == section for m in all_monitors):
            message += f'{title}:\n'
            for typ, val1, val2 in all_monitors:
                if typ == section:
                    if section == 'address' or section == 'mempool':
                        message += f'{index}. {val1}, Tipo: {val2}\n'
                    elif section == 'tx':
                        message += f'{index}. {val1}, Conferme: {val2}\n'
                    elif section == 'fee':
                        message += f'{index}. {val1} sat/byte\n'
                    elif section == 'solo_miner':
                        message += f'{index}. {val1}\n'
                    elif section == 'price_alert':
                        message += f'{index}. Frequenza: {val1}, Valuta: {val2}\n'
                    elif section == 'price_threshold':
                        message += f'{index}. Valuta: {val1}, Soglia: {val2}\n'
                    index += 1
            message += '\n'
    await update.message.reply_text(message)

# Comando /delete_monitor
async def delete_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permette all'utente di cancellare un monitoraggio attivo."""
    context.user_data.clear()
    user_id = str(update.effective_user.id)
    c = DB_CONN.cursor()
    c.execute('SELECT address, type FROM address_subscriptions WHERE user_id = ?', (user_id,))
    address_subs = c.fetchall()
    c.execute('SELECT txid, confirmations FROM tx_subscriptions WHERE user_id = ?', (user_id,))
    tx_subs = c.fetchall()
    c.execute('SELECT threshold FROM fee_thresholds WHERE user_id = ?', (user_id,))
    fee_thresholds = c.fetchall()
    c.execute('SELECT address, type FROM mempool_address_subscriptions WHERE user_id = ?', (user_id,))
    mempool_subs = c.fetchall()
    c.execute('SELECT last_checked_height FROM solo_miner_subscriptions WHERE user_id = ?', (user_id,))
    solo_miner_subs = c.fetchall()
    c.execute('SELECT frequency, currency FROM price_alerts WHERE user_id = ?', (user_id,))
    price_alert = c.fetchone()
    c.execute('SELECT currency, threshold FROM price_thresholds WHERE user_id = ? AND notified = 0', (user_id,))
    price_thresholds = c.fetchall()

    all_monitors = []
    if address_subs:
        all_monitors.extend([('address', addr, typ) for addr, typ in address_subs])
    if tx_subs:
        all_monitors.extend([('tx', txid, conf) for txid, conf in tx_subs])
    if fee_thresholds:
        all_monitors.extend([('fee', threshold[0], None) for threshold in fee_thresholds])
    if mempool_subs:
        all_monitors.extend([('mempool', addr, typ) for addr, typ in mempool_subs])
    if solo_miner_subs:
        all_monitors.append(('solo_miner', 'Monitoraggio solo miner', None))
    if price_alert:
        all_monitors.append(('price_alert', price_alert[0], price_alert[1]))
    if price_thresholds:
        all_monitors.extend([('price_threshold', currency, threshold) for currency, threshold in price_thresholds])

    if not all_monitors:
        await update.message.reply_text('Nessun monitoraggio da cancellare.')
        return ConversationHandler.END

    message = 'Monitoraggi attivi:\n'
    index = 1
    for section, title in [
        ('address', 'Indirizzi (confermate)'),
        ('tx', 'Transazioni'),
        ('fee', 'Soglie fee'),
        ('mempool', 'Indirizzi (non confermate)'),
        ('solo_miner', 'Monitoraggio solo miner'),
        ('price_alert', 'Notifiche prezzo'),
        ('price_threshold', 'Soglie prezzo')
    ]:
        if any(m[0] == section for m in all_monitors):
            message += f'{title}:\n'
            for typ, val1, val2 in all_monitors:
                if typ == section:
                    if section == 'address' or section == 'mempool':
                        message += f'{index}. {val1}, Tipo: {val2}\n'
                    elif section == 'tx':
                        message += f'{index}. {val1}, Conferme: {val2}\n'
                    elif section == 'fee':
                        message += f'{index}. {val1} sat/byte\n'
                    elif section == 'solo_miner':
                        message += f'{index}. {val1}\n'
                    elif section == 'price_alert':
                        message += f'{index}. Frequenza: {val1}, Valuta: {val2}\n'
                    elif section == 'price_threshold':
                        message += f'{index}. Valuta: {val1}, Soglia: {val2}\n'
                    index += 1
            message += '\n'

    context.user_data['all_monitors'] = all_monitors
    await update.message.reply_text(message + 'Inserisci il numero da cancellare:')
    return DELETE_MONITOR_INPUT

async def set_delete_monitor_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancella il monitoraggio selezionato dall'utente."""
    try:
        monitor_number = int(update.message.text) - 1
        all_monitors = context.user_data.get('all_monitors', [])
        if monitor_number < 0 or monitor_number >= len(all_monitors):
            await update.message.reply_text('Numero non valido. Riprova.')
            return DELETE_MONITOR_INPUT
        typ, val1, val2 = all_monitors[monitor_number]
        user_id = str(update.effective_user.id)
        c = DB_CONN.cursor()
        if typ == 'address':
            c.execute('DELETE FROM address_subscriptions WHERE user_id = ? AND address = ? AND type = ?', (user_id, val1, val2))
        elif typ == 'tx':
            c.execute('DELETE FROM tx_subscriptions WHERE user_id = ? AND txid = ?', (user_id, val1))
        elif typ == 'fee':
            c.execute('DELETE FROM fee_thresholds WHERE user_id = ? AND threshold = ?', (user_id, val1))
        elif typ == 'mempool':
            c.execute('DELETE FROM mempool_address_subscriptions WHERE user_id = ? AND address = ? AND type = ?', (user_id, val1, val2))
        elif typ == 'solo_miner':
            c.execute('DELETE FROM solo_miner_subscriptions WHERE user_id = ?', (user_id,))
        elif typ == 'price_alert':
            c.execute('DELETE FROM price_alerts WHERE user_id = ?', (user_id,))
        elif typ == 'price_threshold':
            c.execute('DELETE FROM price_thresholds WHERE user_id = ? AND currency = ? AND threshold = ?', (user_id, val1, val2))
        DB_CONN.commit()
        await update.message.reply_text(f'Monitoraggio {typ} cancellato.')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Numero non valido. Riprova.')
        return DELETE_MONITOR_INPUT

# Comando /tx_fee
async def tx_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calcola la fee di una transazione specifica."""
    context.user_data.clear()
    await update.message.reply_text('Inserisci l\'ID della transazione (txid) per calcolare la fee:')
    return TX_FEE_INPUT

async def set_tx_fee_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Elabora il txid e calcola la fee della transazione."""
    txid = update.message.text.strip()
    if not is_valid_txid(txid):
        await update.message.reply_text('TxID non valido. Riprova.')
        return TX_FEE_INPUT
    tx_details = get_transaction_details(txid)
    if tx_details:
        input_sum = sum(inp['prevout']['value'] for inp in tx_details['vin'] if 'prevout' in inp)
        output_sum = sum(out['value'] for out in tx_details['vout'])
        fee = input_sum - output_sum
        if fee >= 0:
            await update.message.reply_text(f"Fee pagata per tx {txid}: {fee} sat")
        else:
            await update.message.reply_text("Dati transazione incompleti o errati.")
    else:
        await update.message.reply_text("Impossibile ottenere i dettagli della transazione.")
    return ConversationHandler.END

# Comando /recent_blocks
async def recent_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra informazioni sugli ultimi blocchi minati."""
    try:
        response = requests.get(f'{MEMPOOL_API_URL}/v1/blocks')
        if response.status_code == 200:
            blocks = response.json()
            message = "Ultimi blocchi minati:\n"
            for block in blocks[:5]:
                height = block['height']
                tx_count = block['tx_count']
                total_fees_btc = block['extras']['totalFees'] / 100_000_000
                miner = get_block_miner(block)
                message += f"Blocco {height}: {tx_count} tx, fee totali: {total_fees_btc:.8f} BTC, Miner: {miner}\n"
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("Impossibile ottenere i dati dei blocchi.")
    except requests.RequestException:
        await update.message.reply_text("Errore di rete.")

# Comando /fee_forecast
async def fee_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra le previsioni delle fee per i prossimi blocchi."""
    try:
        response = requests.get(f'{MEMPOOL_API_URL}/v1/fees/mempool-blocks')
        if response.status_code == 200:
            blocks = response.json()
            message = "Previsioni fee per blocchi futuri:\n"
            for i, block in enumerate(blocks[:3], 1):
                fee_range = block['feeRange']
                min_fee = round(fee_range[0])
                max_fee = round(fee_range[-1])
                message += f"Blocco {i}: {min_fee} - {max_fee} sat/byte\n"
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("Impossibile ottenere le previsioni fee.")
    except requests.RequestException:
        await update.message.reply_text("Errore di rete.")

# Comando /status
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra lo stato attuale della rete Bitcoin."""
    fees = get_mempool_fees()
    mempool_size = get_mempool_size()
    tip_height = get_last_block_height()
    message = "Stato rete Bitcoin:\n"
    message += f"- Fee attuali: {fees['hourFee']}/{fees['halfHourFee']}/{fees['fastestFee']} sat/byte\n" if fees else "- Impossibile ottenere le fee.\n"
    message += f"- Mempool: {mempool_size} transazioni\n" if mempool_size is not None else "- Impossibile ottenere la dimensione della mempool.\n"
    message += f"- Ultimo blocco: altezza {tip_height}\n" if tip_height is not None else "- Impossibile ottenere l'altezza del blocco.\n"
    await update.message.reply_text(message)

# Comando /track_send_mempool
async def track_send_mempool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvia il monitoraggio degli invii non confermati da un indirizzo."""
    context.user_data.clear()
    await update.message.reply_text('Inserisci l\'indirizzo BTC da monitorare per invii non confermati:')
    return SEND_ADDRESS_INPUT_MEMPOOL

async def set_send_address_mempool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta l'indirizzo per il monitoraggio degli invii non confermati."""
    address = update.message.text.strip()
    if not is_valid_bitcoin_address(address):
        await update.message.reply_text('Indirizzo non valido. Riprova.')
        return SEND_ADDRESS_INPUT_MEMPOOL
    user_id = str(update.effective_user.id)
    timestamp = int(time())
    c = DB_CONN.cursor()
    c.execute('INSERT INTO mempool_address_subscriptions VALUES (?, ?, ?, ?)', (user_id, address, 'send', timestamp))
    DB_CONN.commit()
    await update.message.reply_text(f'Monitoraggio invio non confermato avviato per {address}.')
    return ConversationHandler.END

# Comando /track_receive_mempool
async def track_receive_mempool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvia il monitoraggio delle ricezioni non confermate su un indirizzo."""
    context.user_data.clear()
    await update.message.reply_text('Inserisci l\'indirizzo BTC da monitorare per ricezioni non confermate:')
    return RECEIVE_ADDRESS_INPUT_MEMPOOL

async def set_receive_address_mempool(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta l'indirizzo per il monitoraggio delle ricezioni non confermate."""
    address = update.message.text.strip()
    if not is_valid_bitcoin_address(address):
        await update.message.reply_text('Indirizzo non valido. Riprova.')
        return RECEIVE_ADDRESS_INPUT_MEMPOOL
    user_id = str(update.effective_user.id)
    timestamp = int(time())
    c = DB_CONN.cursor()
    c.execute('INSERT INTO mempool_address_subscriptions VALUES (?, ?, ?, ?)', (user_id, address, 'receive', timestamp))
    DB_CONN.commit()
    await update.message.reply_text(f'Monitoraggio ricezione non confermata avviato per {address}.')
    return ConversationHandler.END

# Monitoraggio mempool
async def monitor_mempool_addresses(context: ContextTypes.DEFAULT_TYPE):
    """Monitora gli indirizzi per invii e ricezioni non confermati nella mempool."""
    c = DB_CONN.cursor()
    c.execute('SELECT user_id, address, type, timestamp FROM mempool_address_subscriptions')
    subscriptions = c.fetchall()
    notified_list = []
    for user_id, address, sub_type, activation_timestamp in subscriptions:
        txs = get_mempool_transactions(address)
        for tx in txs:
            txid = tx['txid']
            c.execute('SELECT 1 FROM notified_mempool_transactions WHERE user_id = ? AND txid = ?', (user_id, txid))
            if c.fetchone():
                continue
            if sub_type == 'send' and any(inp['prevout']['scriptpubkey_address'] == address for inp in tx.get('vin', [])):
                await context.bot.send_message(chat_id=user_id, text=f'Invio non confermato da {address}: {txid}')
                notified_list.append((user_id, txid))
            elif sub_type == 'receive' and any(out['scriptpubkey_address'] == address for out in tx.get('vout', [])):
                await context.bot.send_message(chat_id=user_id, text=f'Ricezione non confermata su {address}: {txid}')
                notified_list.append((user_id, txid))
    if notified_list:
        c.executemany('INSERT INTO notified_mempool_transactions VALUES (?, ?)', notified_list)
        DB_CONN.commit()

# Comando /track_solo_miner
async def track_solo_miner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvia il monitoraggio dei blocchi minati da solo miner."""
    user_id = str(update.effective_user.id)
    height = get_last_block_height()
    if height is None:
        await update.message.reply_text('Impossibile avviare il monitoraggio.')
        return
    c = DB_CONN.cursor()
    c.execute('INSERT OR REPLACE INTO solo_miner_subscriptions (user_id, last_checked_height) VALUES (?, ?)', (user_id, height))
    DB_CONN.commit()
    await update.message.reply_text('Monitoraggio dei blocchi minati da "solo miner" avviato.')

# Monitoraggio solo miner
async def monitor_solo_miners(context: ContextTypes.DEFAULT_TYPE):
    """Controlla i nuovi blocchi per identificare quelli minati da solo miner."""
    c = DB_CONN.cursor()
    c.execute('SELECT user_id, last_checked_height FROM solo_miner_subscriptions')
    subscriptions = c.fetchall()
    current_height = get_last_block_height()
    if current_height is None:
        return
    for user_id, last_height in subscriptions:
        if current_height > last_height:
            for height in range(last_height + 1, current_height + 1):
                block_details = get_block_details(height)
                if block_details:
                    miner = get_block_miner(block_details)
                    if miner == 'Unknown':
                        timestamp = datetime.fromtimestamp(block_details["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                        message = (
                            f'Blocco minato da "solo miner":\n'
                            f'Altezza: {height}\n'
                            f'Hash: {block_details["id"]}\n'
                            f'Timestamp: {timestamp}'
                        )
                        await context.bot.send_message(chat_id=user_id, text=message)
            c.execute('UPDATE solo_miner_subscriptions SET last_checked_height = ? WHERE user_id = ?', (current_height, user_id))
            DB_CONN.commit()

# Comando /price
async def current_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra il prezzo attuale di Bitcoin in EUR e USD."""
    if 'last_price_update' not in context.bot_data or time() - context.bot_data['last_price_update'] > 300:
        await update_price_cache(context)
    eur_price = context.bot_data['btc_prices'].get('eur')
    usd_price = context.bot_data['btc_prices'].get('usd')
    if eur_price is not None and usd_price is not None:
        await update.message.reply_text(f'Prezzo attuale di Bitcoin:\nEUR: {eur_price}\nUSD: {usd_price}')
    else:
        await update.message.reply_text('Prezzo non disponibile al momento.')

# Funzione per calcolare il prossimo orario di notifica
def calculate_next_notification_time(frequency):
    """Calcola il timestamp del prossimo invio di una notifica prezzo."""
    now = datetime.now(timezone.utc)
    if frequency == 'daily':
        next_time = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if now >= next_time:
            next_time += timedelta(days=1)
    elif frequency == 'weekly':
        days_ahead = (7 - now.weekday()) % 7
        if days_ahead == 0 and now.time() >= time(7, 0):
            days_ahead = 7
        next_time = (now + timedelta(days=days_ahead)).replace(hour=7, minute=0, second=0, microsecond=0)
    elif frequency == 'monthly':
        if now.day == 1 and now.time() < time(7, 0):
            next_time = now.replace(hour=7, minute=0, second=0, microsecond=0)
        else:
            next_month = now.month % 12 + 1
            next_year = now.year + (now.month // 12)
            if next_month == 13:
                next_month = 1
                next_year += 1
            next_time = datetime(next_year, next_month, 1, 7, 0, 0, tzinfo=timezone.utc)
    return int(next_time.timestamp())

# Callback per inviare la notifica del prezzo
async def send_price_alert(context: ContextTypes.DEFAULT_TYPE):
    """Invia una notifica periodica del prezzo di Bitcoin."""
    job = context.job
    user_id = job.data['user_id']
    c = DB_CONN.cursor()
    c.execute('SELECT frequency, currency, next_notification_time FROM price_alerts WHERE user_id = ?', (user_id,))
    alert = c.fetchone()
    if alert:
        frequency, currency, next_notification_time = alert
        now = int(time())
        if next_notification_time <= now:
            btc_price = context.bot_data['btc_prices'].get(currency.lower())
            if btc_price is not None:
                await context.bot.send_message(chat_id=user_id, text=f'Prezzo attuale di Bitcoin in {currency}: {btc_price}')
            else:
                await context.bot.send_message(chat_id=user_id, text='Prezzo non disponibile al momento.')
            
            next_time = calculate_next_notification_time(frequency)
            while next_time <= now:
                if frequency == 'daily':
                    next_time += 86400
                elif frequency == 'weekly':
                    next_time += 604800
                elif frequency == 'monthly':
                    next_time = calculate_next_notification_time(frequency)
            c.execute('UPDATE price_alerts SET next_notification_time = ? WHERE user_id = ?', (next_time, user_id))
            DB_CONN.commit()
            delay = next_time - now
            context.job_queue.run_once(send_price_alert, delay, data={'user_id': user_id})

# Funzione per schedulare le notifiche
def schedule_price_alert_job(context: ContextTypes.DEFAULT_TYPE, user_id, next_notification_time):
    """Schedula una notifica prezzo per un utente."""
    now = int(time())
    delay = next_notification_time - now
    if delay > 0:
        context.job_queue.run_once(send_price_alert, delay, data={'user_id': user_id})

# Comando /set_price_alert
async def set_price_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta notifiche periodiche del prezzo di Bitcoin."""
    context.user_data.clear()
    await update.message.reply_text('Scegli la frequenza delle notifiche:\n1. Daily\n2. Weekly\n3. Monthly\nInserisci il numero corrispondente:')
    return FREQUENCY_INPUT

async def set_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta la frequenza delle notifiche prezzo."""
    try:
        choice = int(update.message.text)
        if choice == 1:
            frequency = 'daily'
        elif choice == 2:
            frequency = 'weekly'
        elif choice == 3:
            frequency = 'monthly'
        else:
            await update.message.reply_text('Numero non valido. Scegli 1, 2 o 3.')
            return FREQUENCY_INPUT
        context.user_data['frequency'] = frequency
        await update.message.reply_text('Scegli la valuta:\n1. EUR\n2. USD\nInserisci il numero corrispondente:')
        return CURRENCY_INPUT
    except ValueError:
        await update.message.reply_text('Input non valido. Inserisci un numero.')
        return FREQUENCY_INPUT

async def set_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta la valuta per le notifiche prezzo."""
    try:
        choice = int(update.message.text)
        if choice == 1:
            currency = 'EUR'
        elif choice == 2:
            currency = 'USD'
        else:
            await update.message.reply_text('Numero non valido. Scegli 1 o 2.')
            return CURRENCY_INPUT
        user_id = str(update.effective_user.id)
        frequency = context.user_data['frequency']
        next_notification_time = calculate_next_notification_time(frequency)
        c = DB_CONN.cursor()
        c.execute('INSERT OR REPLACE INTO price_alerts VALUES (?, ?, ?, ?)', (user_id, frequency, currency, next_notification_time))
        DB_CONN.commit()
        schedule_price_alert_job(context, user_id, next_notification_time)
        await update.message.reply_text(f'Notifica prezzo impostata: {frequency} in {currency}. Le notifiche saranno inviate alle 07:00 UTC.')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Input non valido. Inserisci un numero.')
        return CURRENCY_INPUT

# Comando /set_price_threshold
async def set_price_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta una soglia di prezzo per ricevere notifiche."""
    context.user_data.clear()
    await update.message.reply_text('Scegli la valuta per la soglia di prezzo:\n1. EUR\n2. USD\nInserisci il numero corrispondente:')
    return PRICE_THRESHOLD_CURRENCY_INPUT

async def set_price_threshold_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta la valuta per la soglia di prezzo."""
    try:
        choice = int(update.message.text)
        if choice == 1:
            currency = 'EUR'
        elif choice == 2:
            currency = 'USD'
        else:
            await update.message.reply_text('Numero non valido. Scegli 1 o 2.')
            return PRICE_THRESHOLD_CURRENCY_INPUT
        context.user_data['currency'] = currency
        await update.message.reply_text(f'Inserisci la soglia di prezzo in {currency}:')
        return PRICE_THRESHOLD_VALUE_INPUT
    except ValueError:
        await update.message.reply_text('Input non valido. Inserisci un numero.')
        return PRICE_THRESHOLD_CURRENCY_INPUT

async def set_price_threshold_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta il valore della soglia di prezzo."""
    try:
        threshold = float(update.message.text)
        if threshold < 0:
            await update.message.reply_text('La soglia deve essere un numero positivo.')
            return PRICE_THRESHOLD_VALUE_INPUT
        user_id = str(update.effective_user.id)
        currency = context.user_data['currency']
        current_price = context.bot_data['btc_prices'].get(currency.lower())
        if current_price is None:
            await update.message.reply_text('Prezzo non disponibile al momento. Riprova più tardi.')
            return PRICE_THRESHOLD_VALUE_INPUT

        # Determina la direzione
        if current_price < threshold:
            direction = 'above'
            message = f'Soglia di prezzo impostata a {threshold} {currency}. Riceverai una notifica quando il prezzo supera questa soglia.'
        else:
            direction = 'below'
            message = f'Soglia di prezzo impostata a {threshold} {currency}. Riceverai una notifica quando il prezzo scende sotto questa soglia.'

        # Salva nel database
        c = DB_CONN.cursor()
        c.execute('INSERT INTO price_thresholds VALUES (?, ?, ?, 0, ?)', (user_id, currency, threshold, direction))
        DB_CONN.commit()

        await update.message.reply_text(message)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Input non valido. Inserisci un numero.')
        return PRICE_THRESHOLD_VALUE_INPUT

async def monitor_price_thresholds(context: ContextTypes.DEFAULT_TYPE):
    """Monitora le soglie di prezzo e invia notifiche quando raggiunte."""
    c = DB_CONN.cursor()
    c.execute('SELECT user_id, currency, threshold, direction FROM price_thresholds WHERE notified = 0')
    thresholds = c.fetchall()

    for user_id, currency, threshold, direction in thresholds:
        current_price = context.bot_data['btc_prices'].get(currency.lower())
        if current_price is None:
            continue
        if direction == 'above' and current_price >= threshold:
            await context.bot.send_message(
                chat_id=user_id,
                text=f'Il prezzo del Bitcoin ha raggiunto o superato la tua soglia di {threshold} {currency}: ora è {current_price} {currency}.'
            )
            c.execute('UPDATE price_thresholds SET notified = 1 WHERE user_id = ? AND currency = ? AND threshold = ?',
                      (user_id, currency, threshold))
        elif direction == 'below' and current_price <= threshold:
            await context.bot.send_message(
                chat_id=user_id,
                text=f'Il prezzo del Bitcoin è sceso a o sotto la tua soglia di {threshold} {currency}: ora è {current_price} {currency}.'
            )
            c.execute('UPDATE price_thresholds SET notified = 1 WHERE user_id = ? AND currency = ? AND threshold = ?',
                      (user_id, currency, threshold))

    DB_CONN.commit()

# Comando /convert
async def convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Converte tra EUR/USD e sats o viceversa."""
    if context.args:
        if len(context.args) != 2:
            await update.message.reply_text('Uso: /convert <importo> <valuta>\nEsempio: /convert 100 eur o /convert 100000 sats')
            return
        try:
            amount = float(context.args[0].replace(',', '.'))
            if amount <= 0:
                await update.message.reply_text('L\'importo deve essere positivo.')
                return
            currency = context.args[1].lower()
            if currency not in ['eur', 'sats']:
                await update.message.reply_text('Valuta non supportata. Usa "eur" o "sats".')
                return
            btc_price_eur = context.bot_data['btc_prices'].get('eur')
            if btc_price_eur is None:
                await update.message.reply_text('Prezzo non disponibile al momento.')
                return
            if currency == 'eur':
                btc_amount = amount / btc_price_eur
                sats_amount = int(btc_amount * 1e8)
                await update.message.reply_text(f'{amount} EUR = {sats_amount} sats')
            elif currency == 'sats':
                btc_amount = amount / 1e8
                eur_amount = btc_amount * btc_price_eur
                await update.message.reply_text(f'{amount} sats = {eur_amount:.2f} EUR')
        except ValueError:
            await update.message.reply_text('Importo non valido. Usa un numero.')
        except Exception:
            await update.message.reply_text('Errore durante la conversione.')
    else:
        context.user_data.clear()
        await update.message.reply_text('Vuoi convertire:\n1. Da euro a sats\n2. Da sats a euro\nInserisci 1 o 2:')
        return CONVERT_CHOICE

async def set_convert_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imposta la direzione della conversione."""
    choice = update.message.text.strip()
    if choice == '1':
        context.user_data['convert_direction'] = 'eur_to_sats'
        await update.message.reply_text('Inserisci l\'importo in euro:')
    elif choice == '2':
        context.user_data['convert_direction'] = 'sats_to_eur'
        await update.message.reply_text('Inserisci l\'importo in sats:')
    else:
        await update.message.reply_text('Scelta non valida. Inserisci 1 o 2.')
        return CONVERT_CHOICE
    return CONVERT_AMOUNT

async def set_convert_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Esegue la conversione in base all'importo fornito."""
    try:
        amount = float(update.message.text.replace(',', '.'))
        if amount <= 0:
            await update.message.reply_text('L\'importo deve essere positivo.')
            return CONVERT_AMOUNT
        direction = context.user_data['convert_direction']
        btc_price_eur = context.bot_data['btc_prices'].get('eur')
        if btc_price_eur is None:
            await update.message.reply_text('Prezzo non disponibile al momento.')
            return ConversationHandler.END
        if direction == 'eur_to_sats':
            btc_amount = amount / btc_price_eur
            sats_amount = int(btc_amount * 1e8)
            await update.message.reply_text(f'{amount} EUR = {sats_amount} sats')
        elif direction == 'sats_to_eur':
            btc_amount = amount / 1e8
            eur_amount = btc_amount * btc_price_eur
            await update.message.reply_text(f'{amount} sats = {eur_amount:.2f} EUR')
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Importo non valido. Inserisci un numero.')
        return CONVERT_AMOUNT
    except Exception:
        await update.message.reply_text('Errore durante la conversione.')
        return ConversationHandler.END

# Main
def main():
    """Avvia il bot e configura i job di monitoraggio."""
    init_db()
    application = Application.builder().token(TOKEN).build()

    # Inizializzazione del cache dei prezzi
    application.bot_data['btc_prices'] = {'eur': None, 'usd': None}
    application.bot_data['last_price_update'] = 0
    application.job_queue.run_repeating(update_price_cache, interval=300, first=0)

    # Handler delle conversazioni
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('track_send', track_send)],
        states={SEND_ADDRESS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_send_address)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('track_receive', track_receive)],
        states={RECEIVE_ADDRESS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_receive_address)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('track_tx', track_tx)],
        states={
            TX_ID_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_tx_id)],
            TX_CONFIRMATIONS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_tx_confirmations)],
        },
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('set_fee_threshold', set_fee_threshold)],
        states={FEE_THRESHOLD_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_fee_threshold_value)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('delete_monitor', delete_monitor)],
        states={DELETE_MONITOR_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_delete_monitor_number)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('tx_fee', tx_fee)],
        states={TX_FEE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_tx_fee_id)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('track_send_mempool', track_send_mempool)],
        states={SEND_ADDRESS_INPUT_MEMPOOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_send_address_mempool)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('track_receive_mempool', track_receive_mempool)],
        states={RECEIVE_ADDRESS_INPUT_MEMPOOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_receive_address_mempool)]},
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('set_price_alert', set_price_alert)],
        states={
            FREQUENCY_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_frequency)],
            CURRENCY_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_currency)],
        },
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('set_price_threshold', set_price_threshold)],
        states={
            PRICE_THRESHOLD_CURRENCY_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_threshold_currency)],
            PRICE_THRESHOLD_VALUE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_price_threshold_value)],
        },
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('convert', convert)],
        states={
            CONVERT_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_convert_choice)],
            CONVERT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_convert_amount)],
        },
        fallbacks=[MessageHandler(filters.COMMAND, end_conversation)],
    ))

    # Comandi semplici
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("current_fees", current_fees))
    application.add_handler(CommandHandler("list_monitors", list_monitors))
    application.add_handler(CommandHandler("delete_my_data", delete_my_data))
    application.add_handler(CommandHandler("donate", donate))
    application.add_handler(CommandHandler("recent_blocks", recent_blocks))
    application.add_handler(CommandHandler("fee_forecast", fee_forecast))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("track_solo_miner", track_solo_miner))
    application.add_handler(CommandHandler("price", current_price))

    # Job di monitoraggio
    application.job_queue.run_repeating(monitor_addresses, interval=300, first=0)
    application.job_queue.run_repeating(monitor_fees, interval=300, first=0)
    application.job_queue.run_repeating(monitor_transactions, interval=300, first=0)
    application.job_queue.run_repeating(monitor_mempool_addresses, interval=300, first=0)
    application.job_queue.run_repeating(monitor_solo_miners, interval=300, first=0)
    application.job_queue.run_repeating(monitor_price_thresholds, interval=300, first=0)

    # Schedulazione delle notifiche prezzo esistenti
    c = DB_CONN.cursor()
    c.execute('SELECT user_id, frequency, next_notification_time FROM price_alerts')
    alerts = c.fetchall()
    for user_id, frequency, next_notification_time in alerts:
        now = int(time())
        if next_notification_time < now:
            next_time = calculate_next_notification_time(frequency)
            c.execute('UPDATE price_alerts SET next_notification_time = ? WHERE user_id = ?', (next_time, user_id))
            DB_CONN.commit()
        else:
            next_time = next_notification_time
        delay = next_time - now
        application.job_queue.run_once(send_price_alert, delay, data={'user_id': user_id})

    application.run_polling()

if __name__ == '__main__':
    main()