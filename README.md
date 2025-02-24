# Bitcoin Track Bot by d0nch4n
Un bot Telegram open source per monitorare transazioni Bitcoin e fee della mempool usando le API di Mempool.space.

## Dati raccolti 

I dati, seppur non personali, sono cifrati AES-256 tramite funzione SQLCipher e sono i seguenti:
- id telegram
- indirizzi in monitoraggio
- transazioni in monitoraggio
- soglie fee impostate
- soglie n. blocchi impostate

## Funzionalità
- Monitora invii e ricezioni da un indirizzo Bitcoin per ricevere una notifica
- Notifica conferme di transazioni con numero personalizzato di blocchi confermati
- Monitora le fee della mempool con soglie personalizzate per ricevere una notifica

## Installazione
1. Clona il repository: `git clone https://github.com/d0nch4n/bitcoin-track-bot.git`
2. Installa le dipendenze: `pip3 install -r requirements.txt`
3. Imposta le variabili d'ambiente:
   - `TELEGRAM_TOKEN`: Il tuo token Telegram.
   - `DB_KEY`: Chiave per il database SQLCipher.
4. Avvia il bot: `python bitrackbot.py`

## Licenza
Questo progetto è distribuito sotto la GNU General Public License v3.0. Vedi il file [LICENSE] per i dettagli.

## Dona
Se questo progetto ti è piaciuto e vuoi sostenerlo, offrimi un caffè fulmineo! Grazie d:-D

lnurl1dp68gurn8ghj7ampd3kx2ar0veekzar0wd5xjtnrdakj7tnhv4kxctttdehhwm30d3h82unvwqhk7ur9dejkgur9deskcarexg6q09lqhz
