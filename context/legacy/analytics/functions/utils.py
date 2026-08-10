# assorted utilities for condor funds


# Analytics dir path *USER SET*
# in the future may want to change this to assume it is the above dir 
# regardless of path
analyticsDir = '/Users/rtasseff/projects/condor_test/analytics'

from classes import CondorCoreObs as condor

import numpy as np
import pandas as pd


def ns2days(ns):
    """Convert an array, ns, of numpy.timedelta64 
    objects in nanoseconds to an numpy array of 
    floats in days.

    :param ns:  timedelta64 array, series of nanoseconds
    
    :return days:   float array, same series converted to days
    """
    # check to see if it is nano seconds

    if ns[0].dtype != np.dtype('<m8[ns]'):
        raise Exception('Passed object is not an numpy timedelta array in nanoseconds')

    # how many nanoseconds in a day?
    nsInDay = 86400000000000


    n = len(ns)
    days = np.ones(n)

    # no need to be fancy, just run through and convert
    for i in range(n):
        days[i] = float(ns[i])/nsInDay
    
    return days

def asset_list_syms(assetList):
    """return a list of symbols for this list of assets in the same order"""
    syms = []
    for asset in assetList:
        syms.append(asset.sym)

    return syms







def asset_list2df(assets, getReturns=False):
    """Take a list of Asset objects, assets, and create a price DataFrame.  
    A 2D pandas df for the data with rows as dates and cols as the price values
    # you can override this to get returns instead of prices
    """
    # need to capture the ordering 
    assetSyms = asset_list_syms(assets)
    symH = 'Symbol'
    dateH = 'Date'
    asset = assets[0]
    priceH = asset.get_prices().name
    sym = asset.sym
    if getReturns:
        prices =  asset.returns.values
        dates = asset.returns.times
    else:
        prices =  asset.get_prices().values
        dates = asset.get_prices().times

    n = len(prices)
    if n != len(dates):
        raise Exception('Asset '+sym+' has a different number of times and values')
    #tmp = np.stack(([sym]*n,dates,prices),axis=1)
    tmp = { symH : [sym]*n , dateH : dates , priceH : prices }
    #df = pd.DataFrame(data=tmp,columns=[symH,dateH,prcieH])
    df = pd.DataFrame(tmp)

    for i in range(1,len(assets),1):
        asset = assets[i]
        if priceH != asset.get_prices().name:
            raise Exception('Cannot join asset values with different time course names')
        sym = asset.sym
        if getReturns:
            prices =  asset.returns.values
            dates = asset.returns.times
        else:
            prices =  asset.get_prices().values
            dates = asset.get_prices().times

        n = len(prices)
        if n != len(dates):
            raise Exception('Asset '+sym+' has a different number of times and values')

        #tmp = np.stack(([sym]*n,dates,prices),axis=1)
        tmp = pd.DataFrame( { symH : [sym]*n , dateH : dates , priceH : prices } )
        df = pd.concat([df,tmp], ignore_index=True)

    # rearrange table as dates vs symbols
    data = df.pivot_table(index=dateH, columns=symH, values=priceH)
    # the pivot is great for lineing up dates and formating the table 
    # but it will reorder the symbols abc, so we want the original order to persist
    data = data[assetSyms]


    return data


def asset_list2prices(asset_list,priceLoader=None):
    # crates a Prices object for for a matrix of the prices of the assets
    # The asset list can be a list of str symbols or a list of Asset objects
    # if it is a list of strs then the PriceLoader that points to the full 
    # dataset must be provided
    # if it is a list of Assets then we call for a price update ONLY 
    # when there is no prices in a specific asset

    if type(asset_list[0]) is str:
        # a direct load from one data source
        values, dates, syms = priceLoader.get_assets_np(syms=asset_list)
        # although not originally designed for it, we can still use TimeCourse
        prices = condor.TimeCourse(dates,values,name=priceLoader.priceH)

    else:
        # assuming these are correct asset objects in a list
        # need to loop through to trigger the update if no data yet
        for asset in asset_list:
            if asset.prices is None:
                asset.update_prices()
        # get table from the list 
        df = asset_list2df(asset_list)
        # convert to numpys
        values, dates, syms = df2np(df)
        # although not originally designed for it, we can still use TimeCourse
        prices = condor.TimeCourse(dates,values,name=asset_list[0].prices.name)

    return prices



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



