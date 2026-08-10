# This module contains the core objects for an 
# initial Condor Funds Workflow.
# There is no warranty or guarantee of any kind 

# Analytics dir path *USER SET*
# in the future may want to change this to assume it is the above dir 
# regardless of path
analyticsDir = '/Users/rtasseff/projects/condor_test/analytics'

import sys
# adding analytics to the system path
sys.path.insert(0, analyticsDir)

from functions import genStats as gs
from functions import genFin as gf
from functions import utils
from functions import portOpt as po

from data_mining import load




import numpy as np
import datetime

# a small number that could be considered zero compared to 1.0
eps = 1e-7


# default parameters 

defaultParams = {
        'metric': 'Relative',
        'method': 'Robust',
        'timeFrame': 'M',
        'annualize': True,
        'sampInt': 20
        }


class PriceLoader:
    def __init__(self,path, dateH='Date', priceH='Adj Close', 
        symH='Symbol', syms=None, sep=','):
        # A price loader can be created with just the path for the data
        self.path = path
        self.dateH = dateH 
        self.priceH = priceH
        self.symH = symH
        self.sep = sep
        self.syms = syms

    def set_target_asset_symbols(self,syms):
        # You can set the assets for repeated use if you want
        # by design we do not keep the whole data table in memory 
        # but we can keep all the info to quickly load what is needed
        self.syms = syms

    def get_assets_df(self,syms=None):
        # given a list of strings for asset syms return pandas data frame
        # rows as matching dates, cols as assets, values as listed under price header
        # if no syms are passed we assume the preset values, if they exist
        if syms is not None:
            self.set_target_asset_symbols(syms) 

        if self.syms is None:
            # we warn about this because we initially intended all 
            # data loaders have to be defined with target assets in mind
            # then we moved away to being more general
            # just in case a workflow already exists that may 
            # depend on past function, we are at least notifing for this
            print('Warning: No symbol list is set. All symbols will be used and this could cause confusion in workflows.')
        # get data
        df = load.multiAssetHist_CSV(self.path, dateH=self.dateH, priceH=self.priceH, 
                symH=self.symH, sep=self.sep, verb=False)
        if syms is not None:
            df = df[syms]
        else:
            self.set_target_asset_symbols(syms=df.columns.to_numpy())

        
        return df

    def get_assets_np(self,syms=None):
        if syms is not None:
            self.set_target_asset_symbols(syms) 
        # given a list of strings for asset syms return a set of numpy arrays
        # - price data 2D array rows as matching dates, cols as assets, values as listed under price header
        # - 1D array for dates (should be DateTime format)
        # - 1D array for symbols (should be strs)
        # if no syms are passed we assume the preset values, if they exist
        df = self.get_assets_df(syms=syms)
        
        return utils.df2np(df)

    def get_assets(self,syms=None):
        # given a list of strings for asset syms return a list of asset objects
        # rows as matching dates, cols as assets, values as listed under price header
        # if no syms are passed we assume the preset values, if they exist
        if syms is not None:
            self.set_target_asset_symbols(syms) 

        # get the data
        prices, dates, syms = self.get_assets_np(syms=self.syms)


        # start making the assets
        n = len(syms)
        assets = []
        for i in range(n):
            # setup the data loader for the assets 
            priceLoader = PriceLoader(self.path, dateH=self.dateH, priceH=self.priceH, 
                symH=self.symH, syms=[syms[i]], sep=self.sep)
            data = TimeCourse(dates,prices[:,i],name=self.priceH)
            # at some point we may want to provide an option to the 
            # user so that the name of the price header column 
            # in the data file, does not need to be the same 
            # as the time series data object name
            # as we may be intrested in merging asset data from different files
            # that use different string names for the same data

            # we pass the price loader (for postarity) but we override it
            # since we have all the data here. 
            # why require the user to loop through and load each seperatly 
            assets.append(Asset(syms[i], priceLoader, prices=data))


        return assets

        




class TimeCourse:
    def __init__(self, times, values, name='Time Course', sampInt=1):
        # assuming time as a numpy array of DateTime objects
        # values is a numpy array of corrisponding values
        # name is arbitrary
        # You can also set the sampling interval
        # in the future we may want to create a 'Sampler' object to pass or 
        # use seperatly in between getting values here and the calculation
        # because there are at least two things intervale (frequency) 
        # and period) that we will need, possibly more (like flaging)
        if len(times) != len(values):
            print(len(values))
            print(len(times))
            raise Exception('A TimeCourse must have the same number of values as times.')
        self.times = times
        self.values = values
        self.name = name
        self.lastUpdated = datetime.datetime.now() # need to double check format

        self.sampInt = sampInt

    def _sample(self,array):
        # return the values, but properly sampled
        n = len(array)
        inds = np.arange(0,n,self.sampInt)
        return array[inds]

    def sample_values(self):
        # return the values, but properly sampled
        return self._sample(self.values)
    def sample_dates(self):
        return self._sample(self.dates)

# *** retrospectivly I am starting to think there should be either an 
# AssetSet object that inherits from assets or Assets 
# should be made flexible enough to handel multiple assets 
# for asset sets I keep having to gather up all the individual 
# asset data and then calculate returns seperelty so I can get the 
# squared co disspersion matrix (there are probably other redundencies)
# this is redundant and could lead to inconsistancies 
# after that Portfolio could be a made as an object that 
# inherets from Asset (or AssetSet)
# would look a lot cleaner for example a name feature for each could 
# be asset set as a list of symbols and protfolio as an actual portfolio name ***
# this is nice also because a portfolio is an asset in a real sense, 
# an asset of assets and I expect this to follow through other workflows 
# like joining bonds to stock portfolios to make a super portfolio

class Asset:
    def __init__(self, sym, priceLoader, prices=None):
        # we have purposfully made this object a bit atypical 
        # in terms of how attributes are set and used directly sometimes and not others
        # this is to allow future flexibility in memory space vs compute time
        # for example, in optimization we may not want to 
        # always recalculate the return and related properties
        # but if we are storing tons of assets in memory for real-time investingating 
        # and ultimatly we only really pick apart a few properties of a few assets
        # we may not want to pre calculate all properties for all assets
        # and just hold them in memory
        #
        # the symbol and data loader are the only things required for an asset 
        # but folks may want to regularly define it more
        # completly by passing in prices from the start.
        # Prices is just a TimeCourse object for relevant prices
        self.sym = sym
        self.priceLoader = priceLoader
        self.prices=prices

        if self.priceLoader.syms[0] != sym:
            raise Exception('Passed PriceLoader has a different symbol definintion than the symbol you passed. PriceLoader symbol, '+  priceLoader.syms[0] +', asset symbol '+sym)



        # at this time we do not want to precalculate any returns
        # this will force us to deal with calculation options 
        # in a direct and explicit way later to avoid confusion on how it is calculated
        # at the same time we do not want the user to be forced to make these 
        # decisions if they dont need the return info for this asset
        self.returns=None
        self.expectedReturn = None
        self.returnDispersion = None

        # *** Hard coded from a Project on S&P 500
        # need to find a better way to deal with this
        # like a 'Sampler' object to pass ***
        self.sampInt = 20



    def update_prices(self, prices=None):
        # reload or set prices depnding on what is passed, 
        # clear out other attributes (return stuff), 
        # set update time

        if prices is None:
            # no price, then load data
            # a bit akward but if everything was defined correctly in its setup,
            # we just need (maybe later we can add some checks to loader):
            prices = self.priceLoader.get_assets()[0].prices
        
        # maybe later we can add some checks here on the prices, 
        # which by now were passed by the user or set above by the loader
        self.prices = prices

        # celar out other attributes and update time
        # wait! time was already updated when the TimeCourse object is created

        # incase returns was calculated on a prvious price data we need to reset
        self.returns = None
        self.returns=None
        self.expectedReturn = None
        self.returnDispersion = None


        # we could recalculate, but... 
        # the user may not need the returns, why make them deside on return options
        # and take up memory space and compute time to get them now

    def get_prices_lastUpdated(self):
        # get the time stamp for when the prices were last updated
        if self.prices is None:
            stamp = None
        else:
            stamp = self.prices.lastUpdated

        return(stamp)

    def get_returns_lastUpdated(self):
        # get the time stamp for when the prices were last updated
        if self.returns is None:
            stamp = None
        else:
            stamp = self.returns.lastUpdated

        return(stamp)



    def update_returns(self, timeFrame='M', metric='Relative', method='Robust'):
        # a little open for mess, but we are pushing off all the logic
        # and choices to a returns object

        if self.get_prices_lastUpdated() is None:
            raise Exception('Prices have never been updated.  You need prices to calculate the returns.')
        self.returns = Returns(self.prices, timeFrame=timeFrame, metric=metric, 
                method=method, sampInt=self.sampInt)
        self.expectedReturn = self.returns.calc_expected()
        self.returnDispersion = self.returns.calc_dispersion()


    def update(self, timeFrame='M', metric='Relative', method='Robust'):
        self.update_prices()
        self.update_returns()

    def get_prices(self):
        # returns the prices as a TimeCourse object 
        # 'safer' to use than just refereing to the attribute
        if self.prices is None:
            # no prices yet. Load them
            self.update_prices()

        return self.prices


            

class Returns(TimeCourse):
    def __init__(self, prices, timeFrame='M', metric='Relative', method='Robust', sampInt=1):
        # prices is a TimeCourse object
        if timeFrame == 'D':
            timePeriod = 1
        elif timeFrame == 'M':
            timePeriod = 21
        elif timeFrame == 'Y':
            timePeriod = 21*12
        else:
            raise Exception('The time frame '+timeFrame+' is not known.')

        # *** we are assuming every entry is a day and they are in temporal order
        # in the futrue we should check this first ***
        values = gf.returns(prices.values, period=timePeriod, metric=metric)
        times = prices.times[timePeriod:]

        super().__init__(times, values, name = timeFrame+'ly '+metric+' Returns', sampInt=sampInt)
                
        self.method = method
        self.timeFrame = timeFrame
        self.metric = metric 
        self.sampInt = sampInt

    def calc_expected(self):
        return gf.returnExp(self.sample_values(), method=self.method)

    def calc_dispersion(self):
        # added a way to return co-dispersion squared if this is a matrix
        x = self.sample_values()
        if len(x.shape)==2:
            y = gf.returnCoDispSq(x,method=self.method) 
        else:
            y = gf.returnDisp(x, method=self.method)

        return y
        




class Portfolio:
    def __init__(self, assets, weights, priceLoader=None):
        # a portfolio is just a list of assets (Assets or strs)
        # and there weights (floats).
        # assets can be defined as a string of symbols iff there
        # is a priceLoader defined. This enables loading of all 
        # asset data from a single file, which can a bit faster
        # and easier for the user assuming a proper data flat file exists
        # After initilization a set of Asset objects will be created. 
        # At this time, all future updates will still go through 
        # the individual assets (see update_price below).
        #
        # We note that Portfolio looks a lot like an advanced version of 
        # the Asset object. We may want to force it to be a subclass?

        # if assets are handed, we use the data they have 
        # if there is no price data in an individual asset, 
        # a price update for that asset is triggered
        # the only downside is that it could mean that not all prices 
        # were gathered at the same time so some may be more updated
        # the speed difference is trivial for now but lets note for the future
        # setting the prices here if assets are handed directly to gain some speed

        delta = np.abs(sum(weights)-1)
        if delta > eps:
            raise Exception('Weights must sum to 1. You are off by '+str(delta))
        if len(weights) != len(assets):
            raise Exception('Weights and assets must have the same length')

        self.weights = np.array(weights) # just in case ;)

        # set prices from assets (utils can handle Assets or strs)
        self.prices = utils.asset_list2prices(assets,priceLoader) 

       
        # deal with assets if strs
        if type(assets[0]) is str:
            if priceLoader is None:
                raise Exception('If assets are defined by symbols you must define a PriceLoader to get the data for the assets.  A single file with all asset data must exist. Otherwise assets must be a list of Asset objects')
            # need to make new assets out of str symbols
            self.assets = []
            for sym in assets:
                tmpPriceLoader = priceLoader
                tmpPriceLoader.set_target_asset_symbols([sym])
                self.assets.append(Asset(sym,priceLoader))
        else:
            # assuming this is already an asset object
            self.assets = assets


        
        # book keeping stuff        
        self.returns = None
        self.expectedReturn = None
        self.returnDispersion = None
        self.expectedReturnArray = None
        self.returnCoDispersionSqMatrix = None

        # parameters we may want to persist later
        self.annualizeBy=None
        self.method=None
        self.metric=None
        self.timeFrame=None
        self.sampInt=None


    def update_prices(self):
        # Update all the prices from data and clear out derived info 
        # assuming these are correct asset objects in a list
        # which should have been dealt with in init
        # need to loop through to trigger the update of all data
        # *** Note if there is a price loader set here 
        # it should indicate that you can load everything from one file
        # for increased speed.
        # you could get the prices from utils.asset_list2prices
        # by passing the sym list (not the assets) and the loader
        # but then your asset objects prices' could potentally be
        # out of sync with the updated price matrix,
        # you would need to recreate a new set of assets too either
        # with the new prices or with no price
        # the latter would be odd but it is easier and prvents a sync issue
        # I am not going to deal with this now 
        # but if we are commonly calling large asset sets from 
        # a single file (I doubt it) then this would speed that up a lot***

        for i in range( len(self.assets) ):
            self.assets[i].update_prices()

        self.prices = utils.asset_list2prices(self.assets)
        self.returns=None
        self.expectedReturn = None
        self.returnDispersion = None
        self.expectedReturnArray = None
        self.returnCoDispersionSqMatrix = None

    def get_returns_lastUpdated(self):
        # get the time stamp for when the prices were last updated
        if self.returns is None:
            stamp = None
        else:
            stamp = self.returns.lastUpdated

        return(stamp)

    def get_prices_lastUpdated(self):
        # get the time stamp for when the prices were last updated
        if self.prices is None:
            stamp = None
        else:
            stamp = self.prices.lastUpdated

        return(stamp)


    def update_returns(self, timeFrame=None, metric=None, method=None, sampInt=None):
        # TimeCourse and return functions throughout should be such that 
        # they naturally handel the multi-asset (matrix) form
        # upon first use if parameters not passed then use defaulParams defined above
        # always store params after used which becomes the new default for this instance

        if self.get_prices_lastUpdated() is None:
            raise Exception('Prices have never been updated.  You need prices to calculate the returns.')

        # setup params 
        if timeFrame is None:
            # use default or preset (if not this, then use what was passed, no action needed)
            if self.timeFrame is None:
                # use default
                timeFrame = defaultParams['timeFrame']
            else:
                # we had a preset use that
                timeFrame = self.timeFrame
        # set whatever value is used for the future 
        self.timeFrame =timeFrame

        # setup params 
        if metric is None:
            # use default or preset (if not this, then use what was passed, no action needed)
            if self.metric is None:
                # use default
                metric = defaultParams['metric']
            else:
                # we had a preset use that
                metric = self.metric
        # set whatever value is used for the future 
        self.metric =metric

        # setup params 
        if method is None:
            # use default or preset (if not this, then use what was passed, no action needed)
            if self.method is None:
                # use default
                method = defaultParams['method']
            else:
                # we had a preset use that
                method = self.method
        # set whatever value is used for the future 
        self.method =method

        # setup params 
        if sampInt is None:
            # use default or preset (if not this, then use what was passed, no action needed)
            if self.sampInt is None:
                # use default
                sampInt = defaultParams['sampInt']
            else:
                # we had a preset use that
                sampInt = self.sampInt
        # set whatever value is used for the future 
        self.sampInt =sampInt

        
        self.returns = Returns(self.prices, timeFrame=timeFrame, metric=metric, 
                method=method, sampInt=sampInt)
        self.expectedReturnArray = self.returns.calc_expected()
        self.returnCoDispersionSqMatrix = self.returns.calc_dispersion()

        self.expectedReturn = None
        self.returnDispersion = None
       
    def set_weights(self, weights):
        # setting weights will clear out weight dependnet properties
        delta = np.abs(sum(weights)-1)
        if delta > eps:
            raise Exception('Weights must sum to 1. You are off by '+str(delta))
        self.weights = weights

        self.expectedReturn = None
        self.returnDispersion = None




    def update_properties(self, weights=None, timeFrame=None, metric=None, 
            method=None, annualize=None, sampInt=None):
        # This updates all critical info starting with asset returns to portfolio returns.
        # One can change the weights if a new set of weigths is passed
        self.update_returns(timeFrame=timeFrame, metric=metric, method=method)

        # update the weights if passed
        if weights is not None:
            self.set_weights(weights)

        # setup params 
        if annualize is None:
            # use default or preset (if not this, then use what was passed, no action needed)
            if self.annualize is None:
                # use default
                annualize = defaultParams['annualize']
            else:
                # we had a preset use that
                annualize = self.annualize
        # set whatever value is used for the future 
        self.annualize =annualize

        # to get this far a time frame would have been set
        if annualize:
            annualizeBy = self.timeFrame
        else:
            annualizeBy = 'None'

        self.expectedReturn, self.returnDispersion = gf.asset_set_perform(self.weights, 
                self.expectedReturnArray, self.returnCoDispersionSqMatrix, annualizeBy=annualizeBy)

        


    def calc_properties(self, weights=None, annualize=None, update=True):
        # this assumes asset expected returns and dispersion matrix exist, 
        # which would have required prices and returns.
        # You can only call this after a set of returns for assets has been calculated.
        # Here we only calculate the portfolio properties based on the wieghts, 
        # which can be cahnged with this call if weights are passed
        # This is faster than updating everything over and over if
        # such a function is needed to be looped into a optimization workflow.
        # Note that you can manually pass a choice to annualize
        # if you set it to true, it will choose a baisis based on 
        # how the returns were calculated (timeFrame in anything that updates returns).
        # if it is not set it uses the past setting when the returns were calculated.
        # If somehow nothing is set (which should not work) then it defulats to False
        # in this case we are both returning and overwriting
        # parameters are also overwritten to be default for this instance
        # you can avoid all overwriting by setting update to False
        
        if self.get_returns_lastUpdated() is None:
            raise Exception('Returns have never been updated.  You need returns to calculate the properties.')
        
        if annualize is None:
            # use default or preset (if not this, then use what was passed, no action needed)
            if self.annualize is None:
                # use default
                annualize = defaultParams['annualize']
            else:
                # we had a preset use that
                annualize = self.annualize
        if update:
            # set whatever value is used for the future 
            self.annualize =annualize

        # to get this far a time frame would have been set
        if annualize:
            annualizeBy = self.timeFrame
        else:
            annualizeBy = 'None'


        # update the weights if passed
        if weights is None:
            weights = self.weights
        else:
            # assumes weights passed are ligit and use those
            if update:
                self.set_weights(weights)

        
        expectedReturn, returnDispersion = gf.asset_set_perform(weights, 
                self.expectedReturnArray, self.returnCoDispersionSqMatrix, 
                annualizeBy=annualizeBy)

        if update:
            self.expectedReturn = expectedReturn
            self.returnDispersion = returnDispersion

        return expectedReturn, returnDispersion

    def get_syms(self):
        if type(self.assets[0]) is str:
            # only reasonable choice is this is the symbol list
            syms = assets
        else:
            # assuming it is an asset list
            syms = []
            for asset in self.assets:
                syms.append(asset.sym)

        return syms

    def calc_sharpe_ratio(self,riskFreeRate=0, weights=None, annualize=None):
        # we caculate and return the Sharpe Ratio (see genFin.py for info) of this portfolio.
        # we allow the user to explore different weights by passing them
        # the user can also turn the annualize off or on if passed
        # in this case nothing is overwritten 

        if self.get_returns_lastUpdated() is None:
            raise Exception('No returns set for this portfolio.  You must first update returns.')

        if weights is None:
            # no wieghts passed, use the existing ones:
            weights = self.weights

        # this is the second time I have called similar mess logic on annualize trying to 
        # make the user interface easier at the cost of this mess
        # must be a better way to do this or just shove it all in one function
        if annualize is None:
            # go to previous setting
            annualizeBy = self.timeFrame
        else:
            # decide what to do
            if annualize:
                # we are annualizing
                annualizeBy = self.timeFrame
            else:
                annualizeBy = 'None'



        sr = gf.asset_set_sharpe_ratio(weights, self.expectedReturnArray, 
                self.returnCoDispersionSqMatrix, riskFreeRate=riskFreeRate, 
                annualizeBy=annualizeBy)

        return sr

    def optimal(self, target='Sharpe Ratio', riskFreeRate=0, annualize=None):
        # Finds the optimal weights of this portfolio for target  
        # options include 
        # Shapre Ratio - mazimize its sharpe ratio (default)
        # Dispersion - minimize its dispersion 
        # Does not override anything, old wieghts will still be inplace
        # if you want to optimize this portfolio in full use optimize
        # returns the weights
        if self.get_returns_lastUpdated() is None:
            raise Exception('No returns set for this portfolio.  You must first update returns.')

        # this is the third time I have called similar mess logic on annualize trying to 
        # make the user interface easier at the cost of this mess
        # must be a better way to do this or just shove it all in one function
        if annualize is None:
            # go to previous setting
            annualizeBy = self.timeFrame
        else:
            # decide what to do
            if annualize:
                # we are annualizing
                annualizeBy = self.timeFrame
            else:
                annualizeBy = 'None'
        
        # run existing optimizer
        if target == 'Sharpe Ratio':
            optResults = po.max_sharpe_ratio(self.expectedReturnArray, 
                    self.returnCoDispersionSqMatrix, riskFreeRate=riskFreeRate,
                    annualizeBy=annualizeBy)
        elif target == 'Dispersion':
            optResults = po.min_dispersion(self.expectedReturnArray, 
                    self.returnCoDispersionSqMatrix,
                    annualizeBy=annualizeBy)
        else:
            raise Exception('Target set for optimization not known: '+target)

        
        # get the weights
        wOpt = optResults['x']

        return wOpt





    def optimize(self, target='Sharpe Ratio', riskFreeRate=0, annualize=None):
        # Find the optimal weights of this portfolio for target  
        # options include 
        # Shapre Ratio - mazimize its sharpe ratio (default)
        # Dispersion - minimize its dispersion 
        # Sets (overrides) the current portfolio weights to maximize the sr
        # returns the expected return and return dispersion for the portfolio

        # This calculates and sets (overrides) portfolio properties
        wOpt = self.optimal(target=target, riskFreeRate=riskFreeRate, annualize=annualize)
        expectedReturn, returnDispersion = self.calc_properties(weights=wOpt, 
                annualize=annualize)


        return expectedReturn, returnDispersion





