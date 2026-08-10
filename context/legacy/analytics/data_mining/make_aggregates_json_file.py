import pandas as pd
import fetch_aggregates
import datetime

#set API key
fetch_aggregates.set_api_key("POLYGON_API_KEY_REDACTED")

#create variable from stock_tickers_dataframe json file as parameter for fetch_save aggregated data
#jsonfile is the most recent json file obtained from tickers
stock_tickers = pd.read_json("data/stock_tickers_dataframe_2024-04-19_23-25-51.json")

#fetch & save daily aggregates data 
#parameters (tickers: str, date_from: str, date_to: str, filename_prefix: str = '')
stock_historical_daily_aggregates_list = fetch_aggregates.fetch_and_save(stock_tickers, '2022-04-20', '2024-04-18', '22-04-20_to_2024-04-18_stocks')

# #convert stock_historical_daily_aggregates_list to stock_historical_daily_aggregates_dataframe
# stock_historical_daily_aggregates_dataframe = pd.DataFrame(stock_historical_daily_aggregates_list)


# #save stock_historical_daily_aggregates_dataframe to json file to upload to Google Drive or S3 Bucket
# stock_historical_daily_aggregates_dataframe.to_json("data/stock_tickers_dataframe_{0}.json".format(datetime.now().strftime('%Y-%m-%d_%H-%M- %S')))




