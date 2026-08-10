# general finance functions for Condor workflows

import numpy as np
import pandas as pd

from . import genStats


# a small number that could be considered zero compared to 1.0
eps = 1e-7

def calc_return(x0,xi,metric):
    """Calculate return given price x at 0 and i.

    :param x0:  float, start price
    :param xi:  float, end price
    :param metric:  str, what type of return, 
        Possibilities
            Relative (default)      ( xi - x0 ) / x0
            Delta                   xi - x0 )
            Simple                  xi / x0
            Log                     log( xi / x0 )

    """

    if metric=='Simple':
        r = xi/x0
    elif metric=='Log':
        r = np.log(xi/x0)
    elif metric=='Relative':
        r = (xi-x0)/x0
    elif metric=='Delta':
        r = ( xi-x0 )

    else:
        raise Exception('Metric not known: '+metric)
    return(r)

def returns(x,period=21,metric='Relative'):
    """Calculate the returns over a set period
    given an array of asset prices, x.
    
    Assumes all entries in x are consecutive.

    :param x:   float array, consecutive prices
    :param period:  int, period for returns,period or 
        lag or number of consecutive points to consider,
        default = 21 (rough estimate of consecutive open
        market days in a month).
    :param metric:  str, what type of return, 
        Possibilities
            Relative (default)      ( x_[t=period] - x_0 ) / x_0
            Delta                   x_[t=period] - x_0 )
            Simple                  x_[t=period] / x_0
            Log                     log( x_[t=period] / x_0 )
    :return r:  float array, seris of returns using set metric  
    """
    n = len(x)

    
    # is this a vector or a matrix?
    if len(x.shape)==1:
        r = np.zeros(n-period)
        # I should remove this loop and use a shifting function
        # https://stackoverflow.com/questions/62377978/numpy-array-equivalent-of-pandas-shift-function
        for i in range(0,n-period,1):
            r[i] = calc_return(x[i],x[i+period],metric=metric)

    elif len(x.shape)==2:
        # just apply the 1D part of this function over all columns
        # faster and cleaner than looping here
        def alt_func(a): return(returns(a,period=period,metric=metric))
        r = np.apply_along_axis(alt_func, 0, x)



    return r


def returnExp(r, method='Robust'):
    """Calculate the expected return given a
    set of returns,r.

    :param r:   float array, precalculated returns (if 2D rows=time, cols=assets)
    :param method:  str, what method to use,
        Possibilities
            Robust (default)    robsut statistics, median of set
            Normal              assume normal dist, mean of set
    :return rExp:   float (float array if r is 2D), expected value of return set
    """
    
    # added to deal with matrix
    def alt_func(a): return(genStats.expected(a,method=method))
    rExp = np.apply_along_axis(alt_func, 0, r)

    return rExp

def returnDisp(r, method='Robust'):
    """Calculate the dispersion of returns given a
    set of returns,r.

    :param r:   float array, precalculated returns (if 2D rows=time, cols=assets)
    :param method:  str, what method to use,
        Possibilities
            Robust (default)    robsut statistics, MAD normal adjusted 
            Normal              assume normal dist, standard deviation
    :return rDisp:   float (float array if r is 2D), dispersion value of return set
    """
    if method=='Robust':
        # currently assuming MAD for robust, other options exist
        method='MAD'

    # added to deal with matrix
    def alt_func(a): return(genStats.disper(a,method=method))
    rDisp = np.apply_along_axis(alt_func, 0, r)
    return rDisp

def returnCoDispSq(r,method='Robust'):
    """Calculate the squared co-dispersion of pairs of returns given a
    set of returns,r. For example, using the Normal method simply returns
    the standard covariance matrix.

    :param r:   float array, precalculated returns (2D rows=time, cols=assets) 
    :param method:  str, what method to use,
        Possibilities
            Robust (default)    robsut statistics, sq coMAD normal adjusted 
            Normal              assume normal dist, covariance
    :return:    float (float array if r is 2D), dispersion value of return set
    """
    if method=='Robust':
        # currently assuming Co-MAD for robust, other options exist later
        method='CoMAD'

    return genStats.codisper_sq(r,method=method)

def calc_return_prop(r,method='Robust'):
    """Calculate the key properties of a set of returns,r.
    This will be the expected value and the measure of 
    disspersion, which is often used as a measure of risk.
    
    See supporting methods for more comments:
    calls returnExp for the expected value
    calls returnDisp for the dispersion metric 

    :param r:   float array, precalculated returns
    :param method:  str, what method to use,
        Possibilities
            Robust (default)    robsut statistics - no dist assumption 
            Normal              assume normal dist
    :return rExp:   float, expected value of return set
    :return rDisp:   float, dispersion value of return set
    """
    rExp = returnExp(r,method=method)
    rDisp = returnDisp(r,method=method)
    return rExp, rDisp
 


def prices2returnExp(x,period,metric='Relative', method='Robust'):
    """Convert array of prices,x, to an array of returns.
    Assumes all entries in x are consecutive.

    :param x:   float array, consecutive prices
    :param period:  int, period for returns, period or 
        lag or number of consecutive points to consider,
        default = 21 (rough estimate of consecutive open
        market days in a month).
    :param metric:  str, what type of return, 
        Possibilities
            Relative (default)      ( x_[t=period] - x_0 ) / x_0
            Simple                  x_[t=period] / x_0
            Log                     log( x_[t=period] / x_0 )
    :param method:  str, what method to for estimating return,
        Possibilities
            Robust (default)    use robust statistics 
            Normal              assume normal dist
    :return rExp:   float, expected value of return set
    """
    r = returns(x,period=21,metric=metric)
    rExp = returnExp(r, method=method)
    return(rExp)

def dev(price,exp):
    """ Give the deviation of the actual price, price,
    from the expected price, exp, relative to the 
    expected price.
    """
    dev = (price - exp)/exp
    return dev

def asset_set_perform(w, rExps, rCoDispSq, annualizeBy='None'):
    """Calculates asset performance, i.e. overall expected return and 
    dispersion, based on statistical metrics of the underlying assets, expected 
    return vector and co-dispersion squared matrix (rExp and rCoDispSq) as well 
    as the portfolio weights (w) for each asset.
    The returns can be annualized by providing further info to annualizeBy. 

    :param w:   float array, asset weights, sum must equal one
    :param rExp:    float array, asset expected returns corrisponding to w, 
                    same length as w
    :param rCoDispSq:   float array 2D, estimated co-dispersion squared of 
                        returns, nxn with n same as length w, for normally 
                        distributed data the standard is the co-varriance 
                        matrix
    :param annualizeBy: str, what time frame to annualize by, which is the 
                        time frame used to calculate the returns.
                            Possibilities
                                'None' (default)    Do not annualize
                                'D'                 Annualize by day, rEXPs
                                                    are in daily returns
                                                    (note 253 trading days 
                                                    in year)
                                'M'                 Annualize by month, rExps
                                                    are in monthly returns
                                                    (note 21 trading days in
                                                    month on average)
    :return portReturn: float, expected return of the portfolio 
    :return portDisp:   float, estimated dispersion of portfolio returns, if
                        data is normally distributed the standard estimate is 
                        the standard deviation, in stats common statistical 
                        analysis this is a measure of one type of portfolio 
                        risk
    """


    # ensure that weights add to one
    if np.abs(1 - np.sum(w)) > eps:
        raise Exception('Weights in w do not add to one: '+str(sum(w)))

    if annualizeBy=='None':
        annFact = 1
    elif annualizeBy=='M':
        annFact = 12
    elif annualizeBy=='D':
        annFact = 252 # number of open trading days a year
    else:
        raise Exception('Unknown way to annualize by '+annualizeBy)

        
    portReturn = np.sum(rExps * w)
    portDisp = np.sqrt(np.dot(w.T, np.dot(rCoDispSq, w)))

    portReturn *= annFact
    portDisp *= np.sqrt(annFact) # double check this error propigation

    return portReturn, portDisp

def asset_set_sharpe_ratio(w, rExps, rCoDispSq, riskFreeRate=0, annualizeBy='None'):
    """Return the Sharpe Ratio for a portfolio defined by its assets' weights, 
    expected returns and squared co-dispersion matrix (w, rExps and rCoDispSq). 
    The Sharpe ratio compares 'excess' returns to volitility. Excess returns
    are the portfolios returns compared to a risk free, i.e.guaranteed, return
    (riskFreeRate). Typically a US Tresuary yeild is used like the 3 month T-bill, 
    10 year T-note or the 20 year T-bond.

    More at: https://www.investopedia.com/terms/s/sharperatio.asp

    :param w:   float array, asset weights, sum must equal one
    :param rExp:    float array, asset expected returns corrisponding to w, 
                    same length as w
    :param rCoDispSq:   float array 2D, estimated co-dispersion squared of 
                        returns, nxn with n same as length w, for normally 
                        distributed data the standard is the co-varriance 
                        matrix
    :param annualizeBy: str, what time frame to annualize by, which is the 
                        time frame used to calculate the returns.
                            Possibilities
                                'None' (default)    Do not annualize
                                'D'                 Annualize by day, rEXPs
                                                    are in daily returns
                                                    (note 253 trading days 
                                                    in year)
                                'M'                 Annualize by month, rExps
                                                    are in monthly returns
                                                    (note 21 trading days in
                                                    month on average)
    :return:    float, Sharpe Ratio
    """
    rExp, rDisp = asset_set_perform(w, rExps, rCoDispSq, annualizeBy)

    sr = (rExp - riskFreeRate) / rDisp
    return sr


def asset_set_neg_sharpe_ratio(w, rExps, rCoDispSq, riskFreeRate=0, annualizeBy='None'):
    """Return the negative (-1x) Sharpe Ratio for a portfolio defined by its assets' 
    weights, expected returns and squared co-dispersion matrix (w, rExps and rCoDispSq). 
    The Sharpe ratio compares 'excess' returns to volitility. Excess returns
    are the portfolios returns compared to a risk free, i.e.guaranteed, return
    (riskFreeRate). Typically a US Tresuary yeild is used like the 3 month T-bill, 
    10 year T-note or the 20 year T-bond. 

    The negative value is typically used in optimization (minimize the ngative 
    to maximize the positive).

    More at: https://www.investopedia.com/terms/s/sharperatio.asp

    :param w:   float array, asset weights, sum must equal one
    :param rExp:    float array, asset expected returns corrisponding to w, 
                    same length as w
    :param rCoDispSq:   float array 2D, estimated co-dispersion squared of 
                        returns, nxn with n same as length w, for normally 
                        distributed data the standard is the co-varriance 
                        matrix
    :param annualizeBy: str, what time frame to annualize by, which is the 
                        time frame used to calculate the returns.
                            Possibilities
                                'None' (default)    Do not annualize
                                'D'                 Annualize by day, rEXPs
                                                    are in daily returns
                                                    (note 253 trading days 
                                                    in year)
                                'M'                 Annualize by month, rExps
                                                    are in monthly returns
                                                    (note 21 trading days in
                                                    month on average)
    :return:    float, Sharpe Ratio
    """
    sr = asset_set_sharpe_ratio(w, rExps, rCoDispSq, 
            riskFreeRate=riskFreeRate, annualizeBy=annualizeBy)
    return -1 * sr


def annualize(rExp,rDisp,annualizeBy):
    """ Annualize the return expected values and dispersion values.

    :param rExp:    float array, asset expected returns corrisponding to w, 
                    same length as w
    :param rCoDispSq:   float array 2D, estimated co-dispersion squared of 
                        returns, nxn with n same as length w, for normally 
                        distributed data the standard is the co-varriance 
                        matrix
    :param annualizeBy: str, what time frame to annualize by, which is the 
                        time frame used to calculate the returns.
                            Possibilities
                                'None' (default)    Do not annualize
                                'D'                 Annualize by day, rEXPs
                                                    are in daily returns
                                                    (note 253 trading days 
                                                    in year)
                                'M'                 Annualize by month, rExps
                                                    are in monthly returns
                                                    (note 21 trading days in
                                                    month on average)
                                'Y'                 Annualize by year, same as None
    :return:    float (array if array passed), 
                annualized expected and dispersion values
    """

    if annualizeBy=='None' or annualizeBy=='Y':
        annFact = 1
    elif annualizeBy=='M':
        annFact = 12
    elif annualizeBy=='D':
        annFact = 252 # number of open trading days a year
    else:
        raise Exception('Unknown way to annualize by '+annualizeBy)

    return (rExp * annFact), (rDisp * np.sqrt(annFact))


