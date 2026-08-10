from urllib.request import urlopen
import time
import json
from datetime import datetime

today_date = datetime.today().strftime('%Y-%m-%d')

api_key = None

def set_api_key(value):
    """Set the api key."""
    global api_key
    api_key = value

##fetching ticker data
def fetch(market: str, exchange: str = '', date: str = today_date, active: bool = True, limit: int = 1000, sleeptime: int = 15):
    
    stockTickersList = []
    url = 'https://api.polygon.io/v3/reference/tickers?market={0}&exchange={1}&date={2}&active={3}&limit={4}'.format(market, exchange, date, str(active).lower(), str(limit))

    while url != '':
        requestUrl = "{0}&apiKey={1}".format(url, api_key)
        resp = urlopen(requestUrl)
        print ("requesting data from {0}".format(requestUrl))
        time.sleep(sleeptime)
        stockTicker = json.loads(resp.read())
        stockTickersList.extend(stockTicker['results'])  
        
        if 'next_url' in stockTicker:
            url = stockTicker['next_url']
            
        else:
            print('done fetching data')
            url = ''

    return stockTickersList

