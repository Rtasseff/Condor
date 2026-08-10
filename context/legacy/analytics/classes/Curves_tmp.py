# *** I think this is trash ***
#def calc_eiffcient_frontier(meanReturns, covMatrix, riskFreeRate=.03, constraintSet=(0, 1), annualize=True):
#    maxSR_Portfolio = maxSR(meanReturns, covMatrix, riskFreeRate, constraintSet, annualize)
#    maxSR_returns, maxSR_std = portfolioPerformance(maxSR_Portfolio['x'], meanReturns, covMatrix, annualize)
#    maxSR_allocation = pd.DataFrame(maxSR_Portfolio['x'], index=meanReturns.index, columns=["allocation"])
#    maxSR_allocation.allocation = [round(i * 100, 0) for i in maxSR_allocation.allocation]
#
#    minVol_Portfolio = minimizeVariance(meanReturns, covMatrix, constraintSet, annualize)
#    minVol_returns, minVol_std = portfolioPerformance(minVol_Portfolio['x'], meanReturns, covMatrix, annualize)
#    minVol_allocation = pd.DataFrame(minVol_Portfolio['x'], index=meanReturns.index, columns=["allocation"])
#
#    efficientList = []
#    targetReturns = np.linspace(minVol_returns, maxSR_returns, 100)
#    efficientAllocations = []
#    for target in targetReturns:
#        opt_result = efficientOpt(meanReturns, covMatrix, target, constraintSet, annualize)
#        efficientList.append(opt_result['fun'])
#        efficientAllocations.append(opt_result['x'])
#
#    return maxSR_returns, maxSR_std, maxSR_allocation, minVol_returns, minVol_std, minVol_allocation, efficientList, targetReturns, efficientAllocations

# This module contains the core objects for important curves in analysis 
# for the initial Condor Funds Workflow.
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


class EF:
    def __init__(self, assets, returnRange=None, riskFreeRate=0, annualizeBy='None',
            method='Robust', metric='Relative', timeFrame='M',sampInt=1):
        # this is the Efficent Frontier given a set of assets.
        # Now this is a list of Asset objects but in the future we will 
        # changes this to a dedicated AssetSet object in CondorCoreObs
        # if assets have pre calculated returns, these will be used
        # be sure that they were calculated with the same parameters and methods
        # all passed parameters will be overwriten by the parameters in 
        # pre-calculated assets

        # check to see if any of the assets have a return calculated,
        # if so, uses its properties for all further work.

        # *** --> All this could be avoided if we had a Asset like AssetSet object
        
        for asset in assets:
            if asset.get_returns_lastUpdated() is not None:
               method = asset.returns.method
               metric = asset.returns.metric
               timeFrame = asset.returns.timeFrame
               sampInt = asset.returns.sampInt
               break

        # update assets if needed
        for asset in assets:
            if asset.get_prices_lastUpdated() is None:
                asset.update_prices()

            if asset.get_returns_lastUpdated() is None:
                asset.update_returns()

        # get data altogether 
        returnNP,_,_ = utils.df2np(utils.asset_list2df(assets,getReturns=True))
        returnCoDispSq = gf.returnCoDispSq(returnNP,method=method)
        returnExp = gf.returnExp(returnNP, method=method)

        # <-- ***


        # this is no good for the solver, but not going to worry now
        if returnRange is None:
            returnRange = (0, max(returnExp))

        returnTargets = np.linspace(returnRange[0], returnRange[1], 101)

        # calculate the frontier weights 
        wEF = po.calc_efficient_frontier(returnExp, returnCoDispSq, 
                returnTargets, riskFreeRate=riskFreeRate, annualizeBy=annualizeBy)

        # calculate the properties for each wighting 
        # optimization is not exact so while the target return was set as a goal
# it may not have been achived, need to recalculate 
        n = len(wEF)
        returnExps_EF = np.zeros(n) * np.nan
        returnDisps_EF = np.zeros(n) * np.nan

        for i in range(n):
            returnExps_EF[i], returnDisps_EF[i] = genFin.asset_set_perform(wEF[i], 
                    returnExps, returnCoDispsSq, annualizeBy='M')

            

       self.expectedReturns = returnExps_EF
       self.returnDispersions = returnDisps_EF
       



#class CAL:
#    def __init__(self,

#class Ploter
