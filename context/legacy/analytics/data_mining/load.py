# scripts to load simple files for condor 

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


def assetHist_CSV(path, dateH='Date', priceH='Adj Close**',
        sep=',', disp=True, verb=True, assetN='Asset', sortByDate=True):
    """Load a simple flat file for asset data date and price.
    :param path:    path to file
    :param dateH:   date header
    :param priceH:  price header
    :param sep: seperation char
    :param disp:    display plot if true
    :param verb:    display verbose details if true
    :param assetN:  asset name string
    :return x:  date string list
    :return y:  closing price numpy array
    """

    data = pd.read_csv(path, sep=sep)
    # Convert date column to datetime
    data[dateH] = pd.to_datetime(data[dateH])


    
    # Preference to see data start to end so flip it if needed
    if sortByDate:
        data.sort_values(dateH, axis=0, ascending=True, inplace=True)

    #take a look
    if verb:
        data.info()
        data

    if disp:
        # Plot the data for sanity check
        plt.figure(figsize=(8, 6))
        plt.plot(data[dateH], data[priceH])
        plt.xlabel('Date')
        plt.ylabel('Adjusted Close Price ($)')
        plt.title(assetN+' Pricing History')
        plt.show()

    return data[dateH].to_numpy(), data[priceH].to_numpy()


def multiAssetHist_CSV(path, dateH='Date', priceH='Adj Close', 
        symH='Symbol', sep=',', verb=True):
    """Load a simple flat file for historical data of multiple assets.
    :param path:    str, path to file
    :param dateH:   str, date header
    :param priceH:  str, price header
    :param symH:    str, symbol header
    :param sep: str, seperation char
    :return data:  pandas dataframe, a matrixed table of prices for dates vs assets
    """

    data = pd.read_csv(path, sep=sep)
    # Convert date column to datetime
    data[dateH] = pd.to_datetime(data[dateH])

    # rearrange table as dates vs symbols
    data = data.pivot_table(index=dateH, columns=symH, values=priceH)


    return data

def df2np(df):
    """Convert a dataframe into a numpy data matrix, 
    a numpy array for index and column headers.
    in the condor workflow we have been using simple numpy arrays 
    and not much on panads after the data is orginized .
    To facilitate this it is easier for us to just pull out the parts.
    We typically expect the index to be the dates and the collumns to 
    be the asset symbols.
    """
    return df.to_numpy(), df.index.to_numpy(), df.columns.to_numpy()






