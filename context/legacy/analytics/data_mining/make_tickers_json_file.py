import fetch_tickers
import pandas as pd
from datetime import datetime
import json

#set api key
fetch_tickers.set_api_key("POLYGON_API_KEY_REDACTED")

#fetch ticker data from polygon.io
#parameters (market: str, exchange: str = " ", date: str = today_date, active: bool = True, limit: int = 1000, sleeptime: int = 15)
stock_tickers_list = fetch_tickers.fetch(market = "stocks", exchange="XNYS")

#convert stock_tickers_list to stock_ticker_dataframe
stock_tickers_dataframe = pd.DataFrame(stock_tickers_list)

#add 'id' column to dataframe and set ID of ticker to 1
stock_tickers_dataframe['id'] = stock_tickers_dataframe.index + 1

#save stock_tickers_dataframe to json file to upload to Google Drive / S3 Bucket
stock_tickers_dataframe.to_json("data/stock_tickers_dataframe_{0}.json".format(datetime.now().strftime('%Y-%m-%d_%H-%M-%S')))
