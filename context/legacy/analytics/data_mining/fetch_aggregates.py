from datetime import datetime, timezone
import json
from urllib.request import urlopen
import time
import signal
import sys
import os
import glob

#set API key
api_key = None
def set_api_key(value):
    """Set the api key."""
    global api_key
    api_key = value

#collect aggregates data from polygon.io 
#checks for existing file saved from manual stop or exception error
#if file exists, create a proceessed_ticker list to avoid collecting duplicate data
#if error or manual stop occrus collected_data will be saved as json file
        
def load_latest_collected_data(filename_prefix: str = ''):
    # Get all files matching the pattern "collected_aggregates_data_*.json"
    files = glob.glob("data/{0}_collected_aggregates_data_*.json".format(filename_prefix))
    
    # If there are no files matching the pattern, return an empty list
    if not files:
        return []

    # Sort files based on the modification time (most recent first)
    files.sort(key=os.path.getmtime, reverse=True)

    # Load the data from the most recent file
    latest_file = files[0]
    with open(latest_file, "r") as file:
        return json.load(file)



def fetch_and_save(tickers: str, date_from: str, date_to: str, filename_prefix: str = ''):
    collected_data = load_latest_collected_data(filename_prefix)  # Load the most recent collected data

    processed_tickers = list(map(lambda d: d.get('name'), collected_data))  # Keep track of tickers that have been processed
    
    def signal_handler(sig, frame):
        print("\nSaving collected data before exiting...")
        save_fetched_data(collected_data, filename_prefix)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)  # Register the signal handler for SIGINT (Ctrl+C)

    try:
        for index, ticker in tickers.iterrows(): 
            ticker_id = ticker['id']
            ticker_name = ticker['ticker']

            # Skip ticker if already processed
            if ticker_name in processed_tickers:
                print(f"Ticker {ticker_name} already processed. Skipping...")
                continue

            ticker_url = 'https://api.polygon.io/v2/aggs/ticker/{0}/range/1/day/{1}/{2}/?adjusted=true&sort=asc&limit=50000&apiKey={3}'.format(ticker_name, date_from, date_to, api_key)

            resp = urlopen(ticker_url)
            print('Fetching ticker aggregates for', ticker_name)
            time.sleep(15)
            aggregate_data_for_tickers = json.loads(resp.read())

            if 'results' in aggregate_data_for_tickers: 
                for daily_ticker_aggregates in aggregate_data_for_tickers['results']:
                    daily_aggregates = daily_ticker_aggregates
                    daily_aggregates['ticker_id'] = ticker_id
                    daily_aggregates['date'] = datetime.fromtimestamp(daily_ticker_aggregates['t'] / 1e3, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    daily_aggregates['name'] = ticker_name

                    collected_data.append(daily_aggregates)

            # # Add ticker to processed set
            # processed_tickers.add(ticker_name)
    except Exception as e:
        print("An error occurred:", e)
        print("Saving collected data before interruption...")
        save_fetched_data(collected_data, filename_prefix)
        raise e  # Re-raise the exception after saving the data

    # Saving fetched data
    save_fetched_data(collected_data, filename_prefix)

def save_fetched_data(data, filename_prefix: str = ''):
    # Get current date and time
    current_datetime = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    # Example saving data to a file with timestamp
    filename = f"data/{filename_prefix}_collected_aggregates_data_{current_datetime}.json"
    with open(filename, 'w') as file:
        json.dump(data, file)
    print(f"Collected data saved to {filename}")

