import time

import requests
from time import sleep
import signal

from values import *
import numpy as np

# this class definition allows us to print error messages and stop the program when needed
class ApiException(Exception):
    pass

# this signal handler allows for a graceful shutdown when CTRL+C is pressed
def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True

API_HEADER = {'X-API-key': API_KEY}  # Make sure you use YOUR API Key
shutdown = False

# Constants
ORDER_SIZE_LIST = [500, 1000]

DEPTH = 3

POSITION_LIMIT = 10000
INVENTORY_THRESHOLD_1 = 0.6 * POSITION_LIMIT
INVENTORY_THRESHOLD_2 = 0.4 * POSITION_LIMIT
INVENTORY_THRESHOLD_3 = 0.2 * POSITION_LIMIT
INVENTORY_THRESHOLD_4 = -0.4 * POSITION_LIMIT
INVENTORY_THRESHOLD_5 = -0.2 * POSITION_LIMIT

SAFE_VALUE_1 = 0.2 * POSITION_LIMIT
SAFE_VALUE_2 = 0.2 * POSITION_LIMIT

MIN_SPREAD_LIST = [0.02, 0.1]

K = 1
Q = 2500000

ITER_TIME = 0.2

# this helper method handles rate-limiting to pause for the next cycle.
def handle_rate_limit(response):
    if response.status_code == 429:
        wait_time = float(response.headers.get('Retry-After', response.json().get('wait', 1)))
        print(f"Rate limit exceeded. Waiting for {wait_time} seconds before retrying.")
        sleep(wait_time)
        return True
    return False

# this helper method handles authorization failure.
def handle_auth_failure(response):
    if response.status_code == 401:
        print("Authentication failed. Please check you API Key.")
        global shutdown
        shutdown = True
        return True
    return False


# this helper method compiles possible API responses and handlers.
def api_request(session, method, endpoint, params=None):
    while True:
        url = f"{API_URL}/{endpoint}"
        if method == 'GET':
            resp = session.get(url, params=params)
        elif method == 'POST':
            resp = session.post(url, params=params)
        elif method == 'DELETE':
            resp == session.delete(url, params=params)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        if handle_auth_failure(resp):
            return None
        if handle_rate_limit(resp):
            continue
        if resp.ok:
            return resp.json()
        raise ApiException(f"API request failed: {resp.text}")

def get_tick(session):
    response = api_request(session, 'GET', 'case')
    return response['tick'], response['status'] if response else None

def get_bid_ask_book(session, ticker, depth):
    payload = {'ticker': ticker, 'limit': depth}
    resp = api_request(session, 'GET', 'securities/book', params=payload)
    book = resp

    bid_book = book['bids']
    ask_book = book['asks']

    bid_prices = np.array([item["price"] for item in bid_book])
    ask_prices = np.array([item["price"] for item in ask_book])
    bid_sizes = np.array([item["quantity"] for item in bid_book])
    ask_sizes = np.array([item["quantity"] for item in ask_book])

    bid_prices_v2, bid_sizes_v2, ask_prices_v2, ask_sizes_v2 = np.array([]), np.array([]), np.array([]), np.array([])
    curr_bid, curr_ask = 0, 0

    max_iter = min(len(bid_prices), len(ask_prices))
    i = 0
    bid_index = -1
    ask_index = -1
    while i < max_iter:
        if bid_prices[i] != curr_bid:
            bid_prices_v2 = np.append(bid_prices_v2, bid_prices[i])
            bid_sizes_v2 = np.append(bid_sizes_v2, bid_sizes[i])
            curr_bid = bid_prices[i]
            bid_index += 1
        else:
            bid_sizes_v2[bid_index] += bid_sizes[i]

        if ask_prices[i] != curr_ask:
            ask_prices_v2 = np.append(ask_prices_v2, ask_prices[i])
            ask_sizes_v2 = np.append(ask_sizes_v2, ask_sizes[i])
            curr_ask = ask_prices[i]
            ask_index += 1
        else:
            ask_sizes_v2[ask_index] += ask_sizes[i]

        i += 1
        cutoff = min(len(bid_prices_v2), len(ask_prices_v2))


    return np.array(bid_prices_v2[:cutoff]), np.array(bid_sizes_v2[:cutoff]), np.array(ask_prices_v2[:cutoff]), np.array(ask_sizes_v2[:cutoff])

def calculate_obs(bid_sizes, ask_sizes, depth):
    bid_obs = []
    ask_obs = []

    for i in range(depth):
        bid_obs.append(np.sum(bid_sizes[:i+1]) / np.sum(ask_sizes[:i+1]))
        ask_obs.append(np.sum(ask_sizes[:i+1]) / np.sum(bid_sizes[:i+1]))

    return np.array(bid_obs), np.array(ask_obs)

def get_best_bid_ask(session, ticker):
    bid_prices, bid_sizes, ask_prices, ask_sizes = get_bid_ask_book(session, ticker, 1)
    return bid_prices[0], ask_prices[0]


def get_time_sales(session, ticker):
    payload = {'ticker': ticker}
    book = api_request(session, 'GET', 'securitues/tas', params=payload)

    time_sales_book = [item["quantity"] for item in book]
    return time_sales_book


def get_position(session, ticker):
    payload = {'ticker': ticker}
    resp = api_request(session, 'GET', 'securities', params=payload)
    return resp[0]['position'], resp[0]['vwap']


def get_open_orders(session, ticker):
    payload = {'ticker': ticker}
    orders = api_request(session, 'GET', 'orders', params=payload)

    buy_orders = [item for item in orders if item["action"] == "BUY"]
    sell_orders = [item for item in orders if item["action"] == "SELL"]
    return buy_orders, sell_orders

def num_open_order(session, ticker):
    payload = {'ticker': ticker}
    orders = api_request(session, 'GET', 'orders', params=payload)
    return len(orders)

# def get_order_status(order_id):
#     resp = s.get('http://localhost:9999/v1/orders' + '/' + str(order_id))
#     if resp.ok:
#         order = resp.json()
#         return order['status']

def cancel_all_orders(session, ticker):
    payload = {'ticker': ticker}
    api_request(session, 'POST', 'commands/cancel', params=payload)

def cancel_order(session, id):
    api_request(session, 'DELETE', f"orders/{id}")

def place_order(session, ticker, order_type, quantity, price, action):
    payload = {'ticker': ticker, 'type': order_type, 'quantity': quantity, 'price': price, 'action': action}
    resp = api_request(session, 'POST', 'orders', params=payload)
    return resp

def calculate_VAMP(bid_prices, bid_sizes, ask_prices, ask_sizes):
    bid_volumes = np.array([bid_sizes[i] * bid_prices[i] for i in range(len(bid_sizes))])
    ask_volumes = np.array([ask_sizes[i] * ask_prices[i] for i in range(len(ask_sizes))])

    i = 1
    while np.sum(bid_volumes[:i]) <= Q:
        i += 1
    bid_vwap = np.dot(np.append(bid_volumes[:i-1], Q - np.sum(bid_volumes[:i-1])), bid_prices[:i]) / Q

    i = 1
    while np.sum(ask_volumes[:i]) <= Q:
        i += 1
    ask_vwap = np.dot(np.append(ask_volumes[:i-1], Q - np.sum(ask_volumes[:i-1])), ask_prices[:i]) / Q

    return (bid_vwap + ask_vwap) / 2

def main():
    with requests.Session() as s:
        s.headers.update(API_HEADER)
        tick, status = get_tick(s)
        last_tick = tick
        ticker_list = ['OWL', 'DUCK', 'CROW', 'DOVE']

        while status == 'ACTIVE' or tick < 599:
            for ticker, MIN_SPREAD, ORDER_SIZE in zip(ticker_list[:2], MIN_SPREAD_LIST, ORDER_SIZE_LIST):
                position, vwap = get_position(s, ticker)
                bid_prices, bid_sizes, ask_prices, ask_sizes = get_bid_ask_book(s, ticker, 3 * DEPTH)
                bid_obs, ask_obs = calculate_obs(bid_sizes, ask_sizes, DEPTH)
                spread = round(ask_prices[0] - bid_prices[0], 2)
                bid_id, ask_id = 0, 0
                adjusted_delta = -0.02 * (position / POSITION_LIMIT)
                #buy_orders, sell_orders = get_open_orders(s, ticker)
                #buy_order_prices = [order['price'] for order in buy_orders]
                #sell_order_prices = [order['price'] for order in sell_orders]
                #print(ticker, spread, position, MIN_SPREAD)

                # for i in range(len(bid_prices)): print(f"Ticker: {ticker} : Bid size: {bid_sizes[i]} -> Bid price: {bid_prices[i]} <--> Ask price: {ask_prices[i]} <- Ask size: {ask_sizes[i]}")

                if spread >= MIN_SPREAD:
                    if abs(position) < INVENTORY_THRESHOLD_1:
                        #cancel_all_orders(s, ticker)
                        if bid_id > 0:
                            cancel_order(s, bid_id)
                            cancel_order(s, ask_id)
                        bid = min(max(bid_prices[0] + 0.01 + adjusted_delta, bid_prices[0] + 0.01), ask_prices[0] - 0.01)
                        ask = max(min(ask_prices[0] - 0.01 + adjusted_delta, ask_prices[0] - 0.01), bid_prices[0] + 0.01)
                        bid_order = place_order(s, ticker, 'LIMIT', ORDER_SIZE, bid, 'BUY')
                        ask_order = place_order(s, ticker, 'LIMIT', ORDER_SIZE, ask, 'SELL')
                        bid_id, ask_id = bid_order['order_id'], ask_order['order_id']
                else:
                    #print("here")
                    if position < INVENTORY_THRESHOLD_2:
                        if bid_obs[1] < K and bid_obs[2] > K:
                            bid = min(max(bid_prices[2] + 0.01 + adjusted_delta, bid_prices[2] + 0.01), ask_prices[0] - 0.01)
                            place_order(s, ticker, 'LIMIT', ORDER_SIZE, bid, 'BUY')
                        elif bid_obs[0] < K and bid_obs[1] > K:
                            bid = min(max(bid_prices[1] + 0.01 + adjusted_delta, bid_prices[1] + 0.01), ask_prices[0] - 0.01)
                            place_order(s, ticker, 'LIMIT', ORDER_SIZE, bid, 'BUY')
                        elif bid_obs[0] > K:
                            bid = min(max(bid_prices[0] + adjusted_delta, bid_prices[0]), ask_prices[0] - 0.01)
                            place_order(s, ticker, 'LIMIT', ORDER_SIZE, bid, 'BUY')
                    elif position > INVENTORY_THRESHOLD_3 and ask_obs[0] > K:
                        ask = max(min(ask_prices[0] - 0.01 + adjusted_delta, ask_prices[0] - 0.01), bid_prices[0] + 0.01)
                        place_order(s, ticker, 'LIMIT', ORDER_SIZE, ask, 'SELL')

                    if position > INVENTORY_THRESHOLD_4:
                        if ask_obs[1] < K and ask_obs[2] > K:
                            ask = max(min(ask_prices[2] - 0.01 + adjusted_delta, ask_prices[2] - 0.01), bid_prices[0] + 0.01)
                            place_order(s, ticker, 'LIMIT', ORDER_SIZE, ask, 'SELL')
                        elif ask_obs[0] < K and ask_obs[1] > K:
                            ask = max(min(ask_prices[1] - 0.01 + adjusted_delta, ask_prices[1] - 0.01), bid_prices[0] + 0.01)
                            place_order(s, ticker, 'LIMIT', ORDER_SIZE, ask, 'SELL')
                        elif ask_obs[0] > K:
                            ask = max(min(ask_prices[0] + adjusted_delta, ask_prices[0]), bid_prices[0] + 0.01)
                            place_order(s, ticker, 'LIMIT', ORDER_SIZE, ask, 'SELL')
                    elif position < INVENTORY_THRESHOLD_5 and bid_obs[0] > K:
                        bid = min(max(bid_prices[0] + 0.01 + adjusted_delta, bid_prices[0] + 0.01), ask_prices[0] - 0.01)
                        place_order(s, ticker, 'LIMIT', ORDER_SIZE, bid, 'BUY')
                    #time.sleep(0.1)

                tick, status = get_tick(s)

                num_orders = num_open_order(s, ticker)
                if abs(position) > SAFE_VALUE_1 and num_orders > 8:
                    cancel_all_orders(s, ticker)
                elif abs(position) > SAFE_VALUE_1 and num_orders > 16:
                    cancel_all_orders(s, ticker)

            # for ticker in ticker_list[2:]:
            #     position, vwap = get_position(s, ticker)
            #     bid_prices, bid_sizes, ask_prices, ask_sizes = get_bid_ask_book(s, ticker, 3 * DEPTH)
            #     bid_obs, ask_obs = calculate_obs(bid_sizes, ask_sizes, DEPTH)
            #     vamp = calculate_VAMP(bid_prices, bid_sizes, ask_prices, ask_sizes)
            #     cost = {ticker_list[2] : 0, ticker_list[3] : 0}

            #     if bid_prices[0] > vamp and position == 0:
            #         place_order(s, ticker, 'MARKET', ORDER_SIZE, bid_prices[0], action='SELL')
            #         cost[ticker] = bid_prices[0]
            #     elif ask_prices[0] < vamp and position == 0:
            #         place_order(s, ticker, 'MARKET', ORDER_SIZE, ask_prices[0], action='BUY')
            #         cost[ticker] = ask_prices[0]
            #     if position > 0 and bid_prices[0] > cost[ticker]:
            #         place_order(s, ticker, 'MARKET', abs(position), bid_prices[0], action='SELL')
            #         cost[ticker] = 0
            #     elif position < 0 and ask_prices[0] < cost[ticker]:
            #         place_order(s, ticker, 'MARKET', abs(position), ask_prices[0], action='BUY')
            #         cost[ticker] = 0

            print("beat", tick)


if __name__ == '__main__':
    # register the custom signal handler for graceful shutdowns
    signal.signal(signal.SIGINT, signal_handler)
    main()
    print("yo")



