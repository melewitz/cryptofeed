import json

from feed import Feed


class Bitfinex(Feed):
    def __init__(self, pairs=None, channels=None, callbacks=None):
        super(Bitfinex, self).__init__('wss://api.bitfinex.com/ws/2')
        self.pairs = pairs
        self.channels = channels
        '''
        maps channel id (int) to a dict of
           symbol: channel's currency
           channel: channel name
           handler: the handler for this channel type
        '''
        self.channel_map = {}
        self.book = {}
        self.order_map = {}
        self.callbacks = callbacks
        if self.callbacks is None:
            self.callbacks = {'trades': self._print,
                              'ticker': self._print,
                              'book': self._print}
        
    async def _print(self, update):
        print(update)
    
    async def _ticker(self, msg):
        chan_id = msg[0]
        if msg[1] == 'hb':
            # ignore heartbeats
            pass
        else:
            bid, bid_size, ask, ask_size, \
            daily_change, daily_change_perc, \
            last_price, volume, high, low = msg[1]
            pair = self.channel_map[chan_id]['symbol']
            channel = self.channel_map[chan_id]['channel']
            await self.callbacks['ticker']({'feed': 'bitfinex', 
                                            'channel': 'ticker',
                                            'pair': pair,
                                            'bid': bid,
                                            'ask': ask})
    
    async def _trades(self, msg):
        chan_id = msg[0]
        pair = self.channel_map[chan_id]['symbol']
        async def _trade_update(trade):
            trade_id, timestamp, amount, price = trade
            if amount < 0:
                side = 'SELL'
            else:
                side = 'BUY'
            amount = abs(amount)
            channel = self.channel_map[chan_id]['channel']
            await self.callbacks['trades']({'feed': 'bitfinex', 'channel': 'trade', 'pair': pair, 'side': side, 'amount': amount, 'price': price})
        
        if isinstance(msg[1], list):
            # snapshot
            for trade_update in msg[1]:
                _trade_update(trade_update)
        else:
            # update
            if msg[1] == 'te':
                _trade_update(msg[2])
            elif msg[1] == 'tu':
                # ignore trade updates
                pass
            elif msg[1] == 'hb':
                # ignore heartbeats
                pass
            else:
                print("Unexpected trade message {}".format(msg))
    
    async def _book(self, msg):
        chan_id = msg[0]
        pair = self.channel_map[chan_id]['symbol']

        if isinstance(msg[1], list):
            if isinstance(msg[1][0], list):
                # snapshot so clear book
                self.book[pair] = {'bid': {}, 'ask': {}}
                for update in msg[1]:
                    price, count, amount = update
                    if amount > 0:
                        side = 'bid'
                    else:
                        side = 'ask'
                        amount = abs(amount)
                    self.book[pair][side][price] = {'count': count, 'amount': amount}
            else:
                # book update
                price, count, amount = msg[1]

                if amount > 0:
                    side = 'bid'
                else:
                    side = 'ask'
                    amount = abs(amount)

                if count > 0:
                    # change at price level
                    if price in self.book[pair][side]:
                        print(self.book[pair][side][price])
                    self.book[pair][side][price] = {'count': count, 'amount': amount}
                else:
                    # remove price level
                    del self.book[pair][side][price]
        elif msg[1] == 'hb':
            pass
        else:
            print("Unexpected book msg {}".format(msg))
        await self.callbacks['book']({'feed': 'bitfinex', 'channel': 'book', 'book': self.book})

    async def _raw_book(self, msg):
        chan_id = msg[0]
        pair = self.channel_map[chan_id]['symbol']
        if isinstance(msg[1], list):
            if isinstance(msg[1][0], list):
                # snapshot so clear book
                self.book[pair] = {'bid': {}, 'ask': {}}
                for update in msg[1]:
                    order_id, price, amount = update
                    if amount > 0:
                        side = 'bid'
                    else:
                        side = 'ask'
                        amount = abs(amount)
                    if price not in self.book[pair][side]:
                        self.book[pair][side][price] = {'count': 1, 'amount': amount}
                        self.order_map[order_id] = {'price': price, 'amount': amount, 'side': side}
                    else:
                        self.book[pair][side][price]['count'] += 1
                        self.book[pair][side][price]['amount'] += amount
                        self.order_map[order_id] = {'price': price, 'amount': amount, 'side': side}
            else:
                # book update
                order_id, price, amount = msg[1]

                if amount > 0:
                    side = 'bid'
                else:
                    side = 'ask'
                    amount = abs(amount)

                if price == 0:
                    price = self.order_map[order_id]['price']
                    self.book[pair][side][price]['count'] -= 1
                    if self.book[pair][side][price]['count'] == 0:
                        del self.book[pair][side][price]
                    del self.order_map[order_id]
                else:
                    self.order_map[order_id] = {'price': price, 'amount': amount, 'side': side}
                    if price in self.book[pair][side]:
                        self.book[pair][side][price]['count'] += 1
                        self.book[pair][side][price]['amount'] += amount
                    else:
                        self.book[pair][side][price] = {'count': 1, 'amount': amount}                    
        elif msg[1] == 'hb':
            pass
        else:
            print("Unexpected book msg {}".format(msg))
        await self.callbacks['book']({'feed': 'bitfinex', 'channel': 'book', 'book': self.book})

    async def message_handler(self, msg):
        msg = json.loads(msg)
        if isinstance(msg, list):
            chan_id = msg[0]
            if chan_id in self.channel_map:
                await self.channel_map[chan_id]['handler'](msg)
            else:
               print("Unexpected message on unregistered channel {}".format(msg))

        elif 'chanId' in msg and 'symbol' in msg:
            handler = None
            if msg['channel'] == 'ticker':
                handler = self._ticker
            elif msg['channel'] == 'trades':
                handler = self._trades
            elif msg['channel'] == 'book':
                if msg['prec'] == 'R0':
                    handler = self._raw_book
                else:
                    handler = self._book
            else:
                print('Invalid message type {}'.format(msg))
                return
            self.channel_map[msg['chanId']] = {'symbol': msg['symbol'], 
                                               'channel': msg['channel'],
                                               'handler': handler}

    async def subscribe(self, websocket):
        for channel in self.channels:
            for pair in self.pairs:
                message = {'event': 'subscribe',
                            'channel': channel,
                            'symbol': pair
                          }
                if 'book' in channel:
                    parts = channel.split('-')
                    if len(parts) != 1:
                        message['channel'] = 'book'
                        try:
                            message['prec'] = parts[1]
                            message['freq'] = parts[2]
                            message['len'] = parts[3]
                        except IndexError:
                            # any non specified params will be defaulted
                            pass
                await websocket.send(json.dumps(message))