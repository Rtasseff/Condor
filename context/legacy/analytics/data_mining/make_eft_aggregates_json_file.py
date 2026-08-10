import pandas as pd
import fetch_aggregates
import datetime

#set API key
fetch_aggregates.set_api_key("POLYGON_API_KEY_REDACTED")

#list of dictionaries to iterate through the etfs.
etf_index_tickers = [
    {"id": 0, "ticker": "VOO"},
    {"id": 1, "ticker": "VTI"},
    {"id": 2, "ticker": "SPY"}
]

#create dataframe from the list of etf_index_tickers to iterate through the rows as the dataframe is the parameter of the function 
etf_index_tickers_df = pd.DataFrame(etf_index_tickers)

#(tickers: str, date_from: str, date_to: str, filename_prefix: str = '')
etf_index_tickers_list = fetch_aggregates.fetch_and_save(etf_index_tickers_df, '2022-04-20', '2024-04-18', '2022-04-20_to_2024-04-18_etf')

