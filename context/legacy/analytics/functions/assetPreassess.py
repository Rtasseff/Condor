# This module contains python functions to pre assess risk assets
# based on historical data over multiple years.
#
# It is intended to first gather key meta parameters for statistical analysis:
# - Sampling Frequency 
# - Sample Period 
# And to inform very basic expectations in behaviour 
# - Expectations on abnormal events (and how long they typically last)
# - Expectations on typical returns for long-term holding of the asset
#
# These functions were written specifcally for the Condor Funds Pipeline 
# Updates, supporting functions, other modules and project notebooks:
# https://github.com/Rtasseff/condor_test
#
# There is no warranty or guarantee of any kind 

import numpy as np
from . import genStats as gs
from . import genFin as gf

def flag_dev_event(time,price,priceTrend,thresh):
    """Move through the time series, (time ,price), 
    and flag the deviation events, values that the 
    price deviates from the price trend by a given 
    threshold. 

    :param t:   datetime array, n time points for time series data
    :param price:   float array, n prices for time series data
    :param priceTrend:  float array, n predicted trend values for 
                        prices in time series data
    :param thresh:  float, threshold value for flagable deviation
    
    :return eventInd:   int list, m index values corresponding to 
                        the index, i, in array t at which a deviation 
                        event occured: |price_i-priceTrend_i|>thresh
    :return eventTime:  datetime list, m time points at which a deviation
                        event occured
    :return eventLength:    timedelta('ns') list, m lenghts in nanoseconds, 
                            corresponding to each deviation event
    """
    n = len(time)
    value = np.abs(gf.dev(price,priceTrend))
    eventTime=[]
    eventInd=[]
    eventLength=[]
    started=False 
    for i in range(n):
        if (value[i]>=thresh) and (started==False):
            # deviation past threshold, start timer
            started=True
            # track when this event started
            startTime=time[i]
            # record
            eventTime.append(time[i])
            eventInd.append(i)

        elif started and (((value[i]<thresh) and (started==True)) or i==(n-1)):
            # deviation under threshold threshold or series end, end timer
            # note: logic writen so events only end after they started
            # note: logic writen to end open events at end of time series
            started=False
            # get length of event that just ended
            endTime=time[i]
            # record
            eventLength.append(endTime-startTime)

            

    return eventInd, eventTime, eventLength

def calc_period_error(r,pMin,pMax,actDelta,scale='None',method='Robust'):
    """Calculate the mean 'error' for a range of 
    period lengths, pMin to pMax, of the predicted 
    return compared to the actual return.
    For a set of evenly spaced consecutive returns, r.
    Here the predicted return is the expected value
    of all the returns within a period and 
    the actual return is the return at some point, 
    actDelta steps, in the future.

    The error is the squared difference between
    actual and predicted over some scaling factor,
    scale.

    the errors are averaged over history, that is
    all possible sequences of returns within the 
    array of returns.

    Every possible period within the range is tested 
    one time step at a time.

    :param r:   float array, evenly spaced sequance of return values
    :param pMin:    int, starting period
    :param pMax:    int, ending period
    :actDelta:  int, number of time steps after the return sequence
        to use as an actual return
    :param scale:   str, type of scaleing factor to use
        possibilities
            None    no factor (ie 1)
            Expected    scale by the expected (predicted) return
            Disp    scale by the disperion of the returns used to 
                calculated the expected return
    :param method:    str, what method to use,
        Possibilities
            Robust (default)    robsut statistics - no dist assumption 
            Normal              assume normal dist
    :return error:  float array, errors 
    """

    n = len(r)
    error = np.array([])

    # loop through all possible period lengths
    for period in range(pMin,pMax,1):
        # loop through all periods within the return sequence
        tmpError = np.array([])
        for j in range(period,n-actDelta,1):
            # get the future or 'actual' return
            rAct = r[j+actDelta]
            # cant include this if rAct nan
            if not np.isnan(rAct):
                # get the sequence of returns
                rSeq = r[j-period:j]
                # get the properties for this sequence of returns
                rExp, rDisp = gf.calc_return_prop(rSeq,method=method)
                # determine scaling factor for denominator
                if scale == 'None':
                    denom = 1
                elif scale == 'Expected':
                    denom = rExp
                    # there are cases when an nan can lead
                    # to a zero and odd cases where 
                    # this can lead to a zero median 
                    # need to check the robust cases
                    if method=='Robust' and denom == 0:
                        # in this case we will try the mean
                        denom = np.mean(rSeq)

                elif scale == 'Disp':
                    denom = rDisp
                else:
                    raise Exception('No scaling factor for '+scale)
    
                # calculate and append error
                tmp = ((rExp-rAct) / denom)**2
                tmpError = np.append(tmpError,tmp)

        # calculate and append the mean error
            
        error = np.append(error,gs.expected(tmpError,method=method))

    return error

def calc_running_returns(prices,maxHoldFrac=0.666,metric='Relative',method='Robust'):
    """Given evenly spaced historical pricing data, prices, 
    we calculate the expected return and the dispersion,
    based on method indicated, running over increasinglly longer hold times.


    :param prices:  float array, consecutive historical prices, evenly spaced
    :param metric:  str, what type of return, 
        Possibilities
            Relative (default)      ( x_[t=period] - x_0 ) / x_0
            Delta                   x_[t=period] - x_0 )
            Simple                  x_[t=period] / x_0
            Log                     log( x_[t=period] / x_0 )
    :param method:    str, what method to use,
        Possibilities
            Robust (default)    robsut statistics - no dist assumption 
            Normal              assume normal dist
     """

    
    n = len(prices)
    returns = np.array([])
    disp = np.array([])
    lags = np.array([])

    # use MAD for rodust method dispersion estimate
    if method=='Robust':
        dispMethod = 'MAD'
    else:
        dispMethod = method
    
    for lag in range(int(n*maxHoldFrac)):
        
        temp = np.array([])
        for j in range(0,n-lag,1):
            temp = np.append(temp,gf.calc_return(prices[j],prices[j+lag],metric=metric))
            

        returns = np.append(returns,gs.expected(temp,method=method))
        disp = np.append(disp,gs.disper(temp,method=dispMethod))
        lags = np.append(lags,lag)
        
    return returns, disp, lags

def find_samp_freq(x, cutoff=0.05, period=21,ci=95, fracLag = 0.1):
    """Finds the appropriate sampiling period for an 
    *evenly spaced* sequance of data, x, by using the
    autocorrelation function, genStats.acf, and the 
    +/- cuttoff for 'near' zero to be maintained over 
    the given period.

    :param x:   float array, consecutive and evenly spaced (in time) data points
    :param cutoff:  float, acf value considered statistically 'near' zero, default 0.05
    :param period:  int, number of conseutive data points covering the period to maintain the cutoff
    :param ci:  float, percentage for acf confidence interval, the estimated acf ci must contain the zero for the proceedig period of the sampiling frequency

    :return sampFreq:   int, sampiling frequency, consecutive points to skip in the data sequence for a sufficently uncorrelated observations
    """
    
    # get the acf using above function def
    ac, lag, acConf = gs.acf(x,fracLag=fracLag,ci=ci)
    
    # prep bounds for searching for the sampFreq
    sampFreq = 100000
    n = len(lag)
    
    # start sampFreq search
    for i in range(n-period):
        uncorr = True
        
        # check over the whole period from this point
        for j in range(period):

            # check if the mean is in bounds
            if np.abs(ac[i+j]) > cutoff: 
                uncorr = False
                break
                # check if the CI bounds contain zero
                if acConf[i+j,0] * acConf[i+j,1] > 0:

                    # no go, get out
                    uncorr = False
                    break
        if uncorr:
            sampFreq = lag[i]
            break

    return sampFreq


