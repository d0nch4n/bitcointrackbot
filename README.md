# Bitcoin Track Bot by Donato ₿rienza (d0nch4n)
Un bot Telegram open source per monitorare transazioni Bitcoin e fee della mempool usando le API di Mempool.space.

## Dati raccolti 

I dati, seppur non personali, sono cifrati AES-256 tramite funzione SQLCipher e sono i seguenti:
- id telegram
- indirizzi in monitoraggio
- transazioni in monitoraggio
- soglie fee in monitoraggio

## Funzionalità
- Monitora invii e ricezioni di uno o più indirizzi Bitcoin per ricevere una notifica
- Monitora una o più transazioni -impostando un numero personalizzato di blocchi confermati- per ricevere una notifica
- Monitora le fee della mempool -con soglie personalizzate- per ricevere una notifica
- Visualizza le fee della mempool in tempo reale
- Visualizza la lista di ciò che stai monitorando
- Cancella un monitoraggio precedentemente impostato
- Visualizza lo stato della mempool: fee, altezza blocco, numero transazioni ultimo blocco
- Visualizza dati relativi ad ultimo blocco confermato
- Visualizza le fee di una transazione specifica
- Cancella tutti i tuoi dati dal database
- Effettua una donazione

## Installazione
1. Clona il repository: `git clone https://github.com/d0nch4n/bitcointrackbot.git`
2. Installa le dipendenze: `pip3 install -r requirements.txt`
3. Imposta le variabili d'ambiente all'interno del file .env
   - `TELEGRAM_TOKEN`: Il tuo token Telegram.
   - `DB_KEY`: Chiave per il database SQLCipher.
   - `LIGHTNING_ADDRESS`: Indirizzo per le donazioni
4. Avvia il bot: `python3 bitrackbot.py`

## Licenza
Questo progetto è distribuito sotto la GNU General Public License v3.0. Vedi il file [LICENSE] per i dettagli. Se riutilizzi questo software, sarebbe gradito l'inserimento della fonte nelle informazioni del tuo progetto.

## Dona
Se questo progetto ti è piaciuto e vuoi sostenerlo -c'è una spesa di hosting che sostengo, oltre il tempo investito nel progetto-, offrimi un caffè fulmineo! Grazie d:-D

<img src="https://github.com/d0nch4n/bitcointrackbot/blob/main/donate.png?raw=true" alt="Tips" width="200">

lnurl1dp68gurn8ghj7ampd3kx2ar0veekzar0wd5xjtnrdakj7tnhv4kxctttdehhwm30d3h82unvwqhk7ur9dejkgur9deskcarexg6q09lqhz