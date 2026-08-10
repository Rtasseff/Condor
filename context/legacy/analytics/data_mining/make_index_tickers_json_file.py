import fetch_tickers
import pandas as pd
from datetime import datetime
import json

# return or where to save output
outputPath = '' 
# outputPath = "data/index_tickers_dataframe_{0}.json".format(datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))

#set api key
fetch_tickers.set_api_key("POLYGON_API_KEY_REDACTED")

#fetch ticker data from polygon.io
#parameters (market: str, exchange: str = '', date: str = today_date, active: bool = True, limit: int = 1000, sleeptime: int = 15)
index_ticker_list = fetch_tickers.fetch(market = "indices")

#convert stock_tickers_list to stock_ticker_dataframe
index_ticker_dataframe = pd.DataFrame(index_ticker_list)

#add 'id' column to dataframe and set ID of ticker to 1
index_ticker_dataframe['id'] = index_ticker_dataframe.index + 1

if outputPath != '':
    #save stock_tickers_dataframe to json file to upload to Google Drive / S3 Bucket
    index_ticker_dataframe.to_json(outputPath)
