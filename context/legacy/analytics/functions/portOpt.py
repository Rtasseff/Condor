# This module contains python functions to optimize a portfolio 
# of risk assets based on historical data over multiple years.
#
# There is no warranty or guarantee of any kind 

import numpy as np
import scipy.optimize as spOpt
from . import genStats as gs
from . import genFin as gf

def max_sharpe_ratio(rExps, rCoDispSq, riskFreeRate=0, constraintSet=(0, 1), annualizeBy='None'):
    # number of assets
    n = len(rExps)
    # set the additional, fixed, arguments for the 
    # function to be minimized, asset_set_neg_sharpe_ratio
    args = (rExps, rCoDispSq, riskFreeRate, annualizeBy)
    # set initial guess for the function to be mined
    initGuess = n * [1. / n]
    # set constraints, f(output)=0, for function to be mined
    constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1})
    # set the bounds, (min,max), for the function to be mined
    bounds = tuple(constraintSet for asset in range(n))
    # call scipy optimal minimizer by sequental least squares quadratic programing
    result = spOpt.minimize(gf.asset_set_neg_sharpe_ratio, initGuess, 
            args=args, method='SLSQP', bounds=bounds, constraints=constraints)
    return result

# sub function to calculate the performace and only return the dispersion
def _asset_set_disp(w, rExps, rCoDispSq, annualizeBy='None'):
    tmp = gf.asset_set_perform(w, rExps, rCoDispSq, annualizeBy=annualizeBy)[1]
    return tmp


# sub function to calculate the performace and only return the expected return
def _asset_set_exp(w, rExps, rCoDispSq, annualizeBy='None'):
    tmp = gf.asset_set_perform(w, rExps, rCoDispSq, annualizeBy=annualizeBy)[0]
    return tmp


def min_dispersion(rExps, rCoDispSq, constraintSet=(0, 1), annualizeBy='None',returnTarget=''):
    # note that the targets sent in have to match the annulization 
    # but the properties are pre annualized and then annualized here.
    # we need to clean this up
    # number of assets
    n = len(rExps)
    # set the additional, fixed, arguments for the 
    # function to be minimized, asset_set_disp
    args = (rExps, rCoDispSq, annualizeBy)
    # set initial guess for the function to be mined
    initGuess = n * [1. / n]
    # set constraints, f(output)=0, for function to be mined
    if returnTarget == '':
        # no target return so no constraint there, just on the wieghts summing to zero
        constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1})
    else:
        # a target return constraint needs to be included
        constraints = ({'type': 'eq', 'fun': lambda x: _asset_set_exp(x, rExps, rCoDispSq, annualizeBy) - returnTarget},
                {'type': 'eq', 'fun': lambda x: np.sum(x) - 1})

    # set the bounds, (min,max), for the function to be mined
    bounds = tuple(constraintSet for asset in range(n))
    # call scipy optimal minimizer by sequental least squares quadratic programing        
    result = spOpt.minimize(_asset_set_disp, initGuess, args=args,
                         method='SLSQP', bounds=bounds, constraints=constraints)
    return result

def calc_efficient_frontier(rExps, rCoDispSq, rTargetRange, riskFreeRate=0, constraintSet=(0, 1), annualizeBy='None'):
    # init solution vars
    n = len(rTargetRange)
    m = len(rExps)
    weights = np.zeros((n,m))*np.nan

    for i in range(n):
        rTarget = rTargetRange[i]
        optResult = min_dispersion(rExps, rCoDispSq, annualizeBy=annualizeBy,returnTarget=rTarget)
        weights[i]=optResult['x']

    return weights


