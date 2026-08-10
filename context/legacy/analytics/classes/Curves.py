# This module contains the objects for important curves in analysis 
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

from classes import CondorCoreObs as Condor

from data_mining import load

import numpy as np
import datetime
import plotly.graph_objects as go

# a small number that could be considered zero compared to 1.0
eps = 1e-7

# originally we planned to allow for curves to be created for any set of assets
# however, we decided to force the use of a portfolio set only for now
# there are many precalculated things in a portfolio so this way we dont have to redo 
# them and we can speed up development 
# in the future we should reconcile this so that we can allow for a more generic asset 
# set (not a portfolio) but also not double write code 
# I suggest a new AssetSet object which is a stream lined portfolio that 
# takes on the basic functinality on any asset set and then we can 
# rewrite portfolio to inherit this and only added portfolio (weight) specfic 
# features in the Portfolio object.

class EF:
    def __init__(self,portfolio,riskFreeRate=0,annualize=None, returnRange=None):
    # we are forcing a portfolio object, with calculated returns, be passed
    # we wanted to make it more general but forcing a portfolio lets us 
    # use the portfolio methods already writen and forcing returns to exist
    # lets us off load the parameter setting to the existing portfolio code
    # see note above for plans to make more general

        if portfolio.get_returns_lastUpdated() is None:
            raise Exception('Portfolio returns are required to calculate the efficent frontier, please update returns.')

        # set parameters
        if annualize is None:
            # use default or preset (if not this, then use what was passed, no action needed)
            if portfolio.annualize is None:
                # use default
                annualize = Condor.defaultParams['annualize']
            else:
                # we had a preset use that
                annualize = portfolio.annualize

        # to get this far a time frame would have been set
        if annualize:
            annualizeBy = portfolio.timeFrame
        else:
            annualizeBy = 'None'

        if returnRange is None:
            # get the minimum as min risk and max as single asset max
            # get the min dispersion weights
            wOpt = portfolio.optimal(target='Dispersion', riskFreeRate=riskFreeRate, 
                    annualize=annualize)
            expectedReturn_minDisp, returnDispersion_minDisp = portfolio.calc_properties(weights=wOpt, 
                    annualize=annualize, update=False)

            returns = portfolio.expectedReturnArray
            dispersions = np.sqrt(np.diag(portfolio.returnCoDispersionSqMatrix))
        if annualize:
            returns, dispersions = gf.annualize(returns,dispersions,portfolio.timeFrame)

            returnRange = (expectedReturn_minDisp, max(returns))

        returnTargets = np.linspace(returnRange[0], returnRange[1], 101)

        self.annualize=annualize
        self.riskFreeRate=riskFreeRate
        

        # calculate the frontier weights 
        wEF = po.calc_efficient_frontier(portfolio.expectedReturnArray, 
                portfolio.returnCoDispersionSqMatrix, returnTargets, 
                riskFreeRate=riskFreeRate, annualizeBy=annualizeBy)

        # calculate the properties for each wighting 
        # optimization is not exact so while the target return was set as a goal
# it may not have been achived, need to recalculate 
        n = len(wEF)
        returnExps_EF = np.zeros(n) * np.nan
        returnDisps_EF = np.zeros(n) * np.nan

        for i in range(n):
            returnExps_EF[i], returnDisps_EF[i] = gf.asset_set_perform(wEF[i], 
                    portfolio.expectedReturnArray, portfolio.returnCoDispersionSqMatrix, 
                    annualizeBy=annualizeBy)

        self.expectedReturns = returnExps_EF
        self.returnDispersions = returnDisps_EF
        self.weights = wEF



def calc_CAL(x,sr, riskFreeRate):
    # Given a maximum sharpe ratio 
    # return the return value of the capital allocation line for x

    cal = x * sr + riskFreeRate

    return cal

class CAL:
    def __init__(self,portfolio,riskFreeRate=0,annualize=None):
        # Capital Allocation line for portfolio 
        # Stores paired expected returns and return dispersions
        # Stores weights as risk free and stock portfolio pairs
        # 

        if portfolio.get_returns_lastUpdated() is None:
            raise Exception('Portfolio returns are required to calculate the efficent frontier, please update returns.')

        # set parameters
        if annualize is None:
            # use default or preset (if not this, then use what was passed, no action needed)
            if portfolio.annualize is None:
                # use default
                annualize = Condor.defaultParams['annualize']
            else:
                # we had a preset use that
                annualize = portfolio.annualize

        # to get this far a time frame would have been set
        if annualize:
            annualizeBy = portfolio.timeFrame
        else:
            annualizeBy = 'None'

        wOpt = portfolio.optimal(target='Sharpe Ratio', riskFreeRate=riskFreeRate, 
                annualize=annualize)

        sr = portfolio.calc_sharpe_ratio(weights=wOpt, riskFreeRate=riskFreeRate, 
                annualize=annualize)

        _, maxDisp = portfolio.calc_properties(weights=wOpt, annualize=annualize, update=False)

        returnDispersions = np.linspace(0, maxDisp, 101)

        expectedReturns = np.zeros(len(returnDispersions)) * np.nan
        weights = np.zeros((len(returnDispersions),2)) * np.nan

        for i in range(len(returnDispersions)):
            disp = returnDispersions[i]
            expectedReturns[i] = calc_CAL(disp,sr,riskFreeRate)
            wStock = disp / maxDisp
            weights[i,0] = 1 - wStock
            weights[i,1] = wStock

        self.returnDispersions = returnDispersions
        self.expectedReturns = expectedReturns
        self.weights = weights



class Plotter:
    def __init__(self,portfolio,riskFreeRate=0,annualize=None):

        if portfolio.metric != 'Relative':
            raise Warning('For creating plot text we are assuming relative returns, but the current return metric is not set to Relative, interpretation may be off.')
       
        # set parameters
        if annualize is None:
            # use default or preset (if not this, then use what was passed, no action needed)
            if portfolio.annualize is None:
                # use default
                annualize = Condor.defaultParams['annualize']
            else:
                # we had a preset use that
                annualize = portfolio.annualize


        self.annualize = annualize
        self.riskFreeRate = riskFreeRate
        self.portfolio = portfolio

        returns = portfolio.expectedReturnArray
        dispersions = np.sqrt(np.diag(portfolio.returnCoDispersionSqMatrix))

        if self.annualize:
            returns, dispersions = gf.annualize(returns,dispersions,portfolio.timeFrame)

        self.returns_assets = returns
        self.dispersions_assets = dispersions


    def get_curves(self):
        self.ef = EF(self.portfolio,riskFreeRate=self.riskFreeRate,annualize=self.annualize)
        self.cal = CAL(self.portfolio,riskFreeRate=self.riskFreeRate,annualize=self.annualize)

    def plot(self, width=675, height=545): 


        # Assets
        portfolio = self.portfolio
        syms = portfolio.get_syms()
        returns = self.returns_assets
        dispersions = self.dispersions_assets


        # format: change to percentage points and round
        returns = np.round(returns * 100,2)
        dispersions = np.round(dispersions * 100, 2)


        text = [
                f"{sym}: Return: {r}% +/- points {d} ({np.round(d/r * 100,2)}%)" for 
                sym, r, d in zip(syms, returns, dispersions)
                ]
        assetPoints = go.Scatter(
                name = 'Assets',
                mode = 'markers',
                x = dispersions,
                y = returns,
                marker = dict(
                    color='gray',
                    size=10,
                    line = dict (
                        width = 2,
                        color = 'black'
                        )
                    ),
                text = text,
                hoverinfo = 'text'
                )

        # EF

        returns_EF = np.round(self.ef.expectedReturns * 100,2)
        dispersions_EF = np.round(self.ef.returnDispersions * 100, 2)
        weights_EF = np.round(self.ef.weights * 100, 2)


        
        text = [
                f"Return: {r}% +/- {d} points ({np.round(d/r * 100,2)}%)<br>" +
                "<br>".join([f"{sym}: {w}%" for sym, w in zip(syms, ws)]) for
                r, d, ws in zip(returns_EF, dispersions_EF, weights_EF)
                ]
        efPoints = go.Scatter(
                name = 'Efficient Frontier',
                mode = 'lines',
                x = dispersions_EF,
                y = returns_EF,
                line = dict (
                    width = 3,
                    color = 'black',
                    dash = 'dashdot'
                    ),
                text = text,
                hoverinfo = 'text'
                )



        # CAL

        returns_CAL = np.round(self.cal.expectedReturns * 100,2)
        dispersions_CAL = np.round(self.cal.returnDispersions * 100, 2)
        weights_CAL = np.round(self.cal.weights * 100, 2)
        syms_CAL = ['RFA']
        for sym in syms: syms_CAL.append(sym)


        # we need to expand the weights of CAL to cover the indivdual stocks
        # recall, these are a portion of the sharpe ratio portfolio

        wSR = portfolio.optimal(target='Sharpe Ratio', riskFreeRate=self.riskFreeRate, 
                annualize=self.annualize)

        weights_CAL_exp = np.zeros((len(weights_CAL),len(wSR)+1)) * np.nan

                
        for i in range(len(weights_CAL)):
            weights_CAL_exp[i,0] = weights_CAL[i,0] # risk free asset weight
            tmp = weights_CAL[i,1] # stock portfolio weight
            for j in range(len(wSR)):
                weights_CAL_exp[i,j+1] = wSR[j] * tmp

        weights_CAL_exp = np.round(weights_CAL_exp, 2)

        text = [
                f"Return: {r}% +/- {d} points ({np.round(d/r * 100,2)}%)<br>" +
                "<br>".join([f"{sym}: {w}%" for sym, w in zip(syms_CAL, ws)]) for
                r, d, ws in zip(returns_CAL, dispersions_CAL, weights_CAL_exp)
                ]
        calPoints = go.Scatter(
                name = 'Capital Allocation Line',
                mode = 'lines',
                x = dispersions_CAL,
                y = returns_CAL,
                line = dict (
                    width = 3,
                    color = 'blue',
                    dash = 'dashdot'
                    ),
                text = text,
                hoverinfo = 'text'
                )


        # RF

        return_RF = round(self.riskFreeRate * 100, 2)

        rfPoint = go.Scatter(
                name = 'Risk-Free Asset',
                mode = 'markers',
                x = [0],
                y = [return_RF],
                marker = dict(
                    color='blue',
                    size=10,
                    line = dict (
                        width = 3,
                        color = 'black'
                        )
                    ),
                text = f"Risk-Free Asset (RFA) Rate of Return: {return_RF}%",
                hoverinfo = 'text'
                )



        # Max Sharpe
        return_SR, dispersion_SR = portfolio.calc_properties(weights=wSR, 
                annualize=self.annualize, update=False)

        return_SR = np.round(return_SR * 100, 2)
        dispersion_SR = np.round(dispersion_SR * 100,2)

        msrPoint = go.Scatter(
                name = 'Optimal Risky Asset Portfolio',
                mode = 'markers',
                x = [dispersion_SR],
                y = [return_SR],
                marker = dict(
                    color='red',
                    size=10,
                    line = dict (
                        width = 3,
                        color = 'black'
                        )
                    ),
                text = f"Optimal Risky Asset Portfolio<br>Return: {return_SR}% +/- {dispersion_SR} points<br>" + "<br>".join([f"{sym}: {w}%" for sym, w in zip(syms, np.round(wSR * 100, 2))]),
                hoverinfo = 'text'
                )


        # Min Dispersion
        wDisp = portfolio.optimal(target='Dispersion', riskFreeRate=self.riskFreeRate, 
                annualize=self.annualize)

        return_Disp, dispersion_Disp = portfolio.calc_properties(weights=wDisp, 
                annualize=self.annualize, update=False)

        return_Disp = np.round(return_Disp * 100, 2)
        dispersion_Disp = np.round(dispersion_Disp * 100,2)

        mdispPoint = go.Scatter(
                name = 'Min Volatility Risky Portfolio',
                mode = 'markers',
                x = [dispersion_Disp],
                y = [return_Disp],
                marker = dict(
                    color='pink',
                    size=10,
                    line = dict (
                        width = 3,
                        color = 'black'
                        )
                    ),
                text = f"Minimum Volitility Risky Portfolio<br>Return: {return_Disp}% +/- {dispersion_Disp} points<br>" + "<br>".join([f"{sym}: {w}%" for sym, w in zip(syms, np.round(wDisp * 100, 2))]),
                hoverinfo = 'text'
                )
        # plot

        data = [assetPoints, efPoints, calPoints, rfPoint, msrPoint, mdispPoint]

        annualizeText = ''
        if self.annualize: 
            annualizeText = 'Annualized '
        else:
            if portfolio.timeFrame == 'M':
                annualizeText = 'Monthly '
            elif portfolio.timeFrame == 'D':
                annualizeText = 'Daily '



        layout = go.Layout(
            title=self.portfolio.method + ' Portfolio Allocations',
            yaxis=dict(title=annualizeText + 'Return (%)'),
            xaxis=dict(title=annualizeText + 'Volatility (Points of Return)'),
            showlegend=True,
            legend=dict(
                x=0,
                y=1,
                traceorder='normal',
                bgcolor="#E2E2E2",
                bordercolor='black',
                borderwidth=2
                ),
            width=width,
            height=height
            )

        fig = go.Figure(data=data, layout=layout)
        fig.show()






