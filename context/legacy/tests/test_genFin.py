"""
Unit tests for core financial calculations (genFin.py)

These tests validate the mathematical accuracy of return calculations,
portfolio performance metrics, and Sharpe ratio calculations.
"""
import pytest
import numpy as np
import sys
import os

# Import the module under test
from functions import genFin as gf

class TestReturnCalculations:
    """Test core return calculation functions"""
    
    def test_calc_return_all_metrics(self):
        """Test all return calculation methods with known values"""
        x0, xi = 100, 110  # 10% price increase
        
        # Test each metric type
        assert abs(gf.calc_return(x0, xi, 'Relative') - 0.1) < 1e-10
        assert abs(gf.calc_return(x0, xi, 'Simple') - 1.1) < 1e-10
        assert abs(gf.calc_return(x0, xi, 'Log') - np.log(1.1)) < 1e-10
        assert abs(gf.calc_return(x0, xi, 'Delta') - 10) < 1e-10
    
    def test_calc_return_negative_change(self):
        """Test return calculations with price decreases"""
        x0, xi = 100, 90  # 10% price decrease
        
        assert abs(gf.calc_return(x0, xi, 'Relative') - (-0.1)) < 1e-10
        assert abs(gf.calc_return(x0, xi, 'Simple') - 0.9) < 1e-10
        assert abs(gf.calc_return(x0, xi, 'Log') - np.log(0.9)) < 1e-10
        assert abs(gf.calc_return(x0, xi, 'Delta') - (-10)) < 1e-10
    
    def test_calc_return_invalid_metric(self):
        """Test that invalid metric raises exception"""
        with pytest.raises(Exception, match="Metric not known"):
            gf.calc_return(100, 110, 'InvalidMetric')
    
    def test_returns_array_processing(self):
        """Test return calculations on price arrays"""
        prices = np.array([100.0, 105.0, 110.0, 108.0])
        
        # Test with period=1 (daily returns)
        returns_result = gf.returns(prices, period=1, metric='Relative')
        expected = np.array([0.05, 0.047619047619, -0.018181818182])
        
        np.testing.assert_array_almost_equal(returns_result, expected, decimal=10)
        
        # Test array length is correct
        assert len(returns_result) == len(prices) - 1
    
    def test_returns_matrix_processing(self):
        """Test return calculations on price matrices (multiple assets)"""
        prices = np.array([
            [100.0, 200.0],
            [105.0, 210.0], 
            [110.0, 205.0]
        ])
        
        returns_result = gf.returns(prices, period=1, metric='Relative')
        
        # Should return 2x2 matrix (2 time periods, 2 assets)
        assert returns_result.shape == (2, 2)
        
        # Check first asset returns
        expected_asset1 = np.array([0.05, 0.047619047619])
        np.testing.assert_array_almost_equal(returns_result[:, 0], expected_asset1, decimal=10)
    
    def test_returns_different_periods(self):
        """Test return calculations with different time periods"""
        prices = np.array([100.0, 105.0, 110.25, 115.7625, 121.55])
        
        # Monthly returns (period=1)
        monthly = gf.returns(prices, period=1, metric='Relative')
        
        # Quarterly returns (period=3) 
        quarterly = gf.returns(prices, period=3, metric='Relative')
        
        assert len(monthly) == 4  # 5 prices - 1 period
        assert len(quarterly) == 2  # 5 prices - 3 period
        
        # First quarterly return should be approximately (110.25-100)/100 = 0.1025
        assert abs(quarterly[0] - 0.1025) < 1e-10

class TestStatisticalProperties:
    """Test expected return and dispersion calculations"""
    
    def test_returnExp_normal_method(self):
        """Test expected return calculation using normal method (mean)"""
        returns = np.array([0.05, 0.10, 0.15, 0.08, 0.12])
        
        result = gf.returnExp(returns, method='Normal')
        expected = np.mean(returns)
        
        assert abs(result - expected) < 1e-10
    
    def test_returnExp_robust_method(self):
        """Test expected return calculation using robust method (median)"""
        returns = np.array([0.05, 0.10, 0.15, 0.08, 0.12])
        
        result = gf.returnExp(returns, method='Robust')
        expected = np.median(returns)
        
        assert abs(result - expected) < 1e-10
    
    def test_returnExp_matrix(self):
        """Test expected return calculation on return matrix"""
        returns = np.array([
            [0.05, 0.08],
            [0.10, 0.12],
            [0.15, 0.06]
        ])
        
        result = gf.returnExp(returns, method='Normal')
        
        # Should return array of expected returns for each asset
        assert len(result) == 2
        assert abs(result[0] - np.mean([0.05, 0.10, 0.15])) < 1e-10
        assert abs(result[1] - np.mean([0.08, 0.12, 0.06])) < 1e-10
    
    def test_returnDisp_normal_method(self):
        """Test return dispersion calculation using normal method (std dev)"""
        returns = np.array([0.05, 0.10, 0.15, 0.08, 0.12])
        
        result = gf.returnDisp(returns, method='Normal')
        expected = np.std(returns, ddof=0)  # Population std dev
        
        assert abs(result - expected) < 1e-10
    
    def test_calc_return_prop(self):
        """Test combined return properties calculation"""
        returns = np.array([0.05, 0.10, 0.15, 0.08, 0.12])
        
        exp_return, dispersion = gf.calc_return_prop(returns, method='Normal')
        
        assert abs(exp_return - np.mean(returns)) < 1e-10
        assert abs(dispersion - np.std(returns, ddof=0)) < 1e-10

class TestPortfolioPerformance:
    """Test portfolio performance calculations"""
    
    def test_asset_set_perform_basic(self, simple_portfolio_data):
        """Test basic portfolio performance calculation"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        port_return, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        
        # Portfolio return should be weighted average
        expected_port_return = np.sum(weights * expected_returns)
        assert abs(port_return - expected_port_return) < 1e-10
        
        # Portfolio risk should be positive
        assert port_risk > 0
        
        # Portfolio risk calculation: sqrt(w' * Cov * w)
        expected_port_risk = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        assert abs(port_risk - expected_port_risk) < 1e-10
    
    def test_asset_set_perform_weight_validation(self, simple_portfolio_data):
        """Test that invalid weights raise exception"""
        bad_weights = np.array([0.6, 0.3])  # Sum = 0.9, not 1.0
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        with pytest.raises(Exception, match="Weights in w do not add to one"):
            gf.asset_set_perform(bad_weights, expected_returns, cov_matrix)
    
    def test_asset_set_perform_dimension_mismatch(self, simple_portfolio_data):
        """Test that dimension mismatches are caught"""
        weights = np.array([0.5, 0.5, 0.0])  # 3 weights
        expected_returns = simple_portfolio_data['expected_returns']  # 2 returns
        cov_matrix = simple_portfolio_data['cov_matrix']  # 2x2 matrix
        
        with pytest.raises(Exception):
            gf.asset_set_perform(weights, expected_returns, cov_matrix)
    
    def test_annualization_monthly(self, simple_portfolio_data):
        """Test monthly annualization factors"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Monthly returns
        monthly_return, monthly_risk = gf.asset_set_perform(
            weights, expected_returns, cov_matrix, annualizeBy='None'
        )
        
        # Annualized returns  
        annual_return, annual_risk = gf.asset_set_perform(
            weights, expected_returns, cov_matrix, annualizeBy='M'
        )
        
        # Check annualization factors
        assert abs(annual_return - monthly_return * 12) < 1e-10
        assert abs(annual_risk - monthly_risk * np.sqrt(12)) < 1e-10
    
    def test_annualization_daily(self, simple_portfolio_data):
        """Test daily annualization factors"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Daily returns
        daily_return, daily_risk = gf.asset_set_perform(
            weights, expected_returns, cov_matrix, annualizeBy='None'
        )
        
        # Annualized returns
        annual_return, annual_risk = gf.asset_set_perform(
            weights, expected_returns, cov_matrix, annualizeBy='D'
        )
        
        # Check annualization factors (252 trading days)
        assert abs(annual_return - daily_return * 252) < 1e-10
        assert abs(annual_risk - daily_risk * np.sqrt(252)) < 1e-10
    
    def test_annualization_invalid(self, simple_portfolio_data):
        """Test that invalid annualization raises exception"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        with pytest.raises(Exception, match="Unknown way to annualize"):
            gf.asset_set_perform(weights, expected_returns, cov_matrix, annualizeBy='Invalid')

class TestSharpeRatio:
    """Test Sharpe ratio calculations"""
    
    def test_asset_set_sharpe_ratio_basic(self, simple_portfolio_data):
        """Test basic Sharpe ratio calculation"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        risk_free_rate = 0.03
        
        sr = gf.asset_set_sharpe_ratio(weights, expected_returns, cov_matrix, 
                                       riskFreeRate=risk_free_rate)
        
        # Calculate manually for verification
        port_return, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        expected_sr = (port_return - risk_free_rate) / port_risk
        
        assert abs(sr - expected_sr) < 1e-10
        
        # Should be positive for profitable portfolio above risk-free rate
        assert sr > 0
    
    def test_asset_set_sharpe_ratio_zero_risk_free(self, simple_portfolio_data):
        """Test Sharpe ratio with zero risk-free rate"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        sr = gf.asset_set_sharpe_ratio(weights, expected_returns, cov_matrix, 
                                       riskFreeRate=0.0)
        
        # Should equal return/risk when risk-free rate is zero
        port_return, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        expected_sr = port_return / port_risk
        
        assert abs(sr - expected_sr) < 1e-10
    
    def test_asset_set_neg_sharpe_ratio(self, simple_portfolio_data):
        """Test negative Sharpe ratio (for optimization)"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        risk_free_rate = 0.03
        
        pos_sr = gf.asset_set_sharpe_ratio(weights, expected_returns, cov_matrix, 
                                           riskFreeRate=risk_free_rate)
        neg_sr = gf.asset_set_neg_sharpe_ratio(weights, expected_returns, cov_matrix, 
                                               riskFreeRate=risk_free_rate)
        
        assert abs(neg_sr + pos_sr) < 1e-10  # Should be exact negatives

class TestAnnualizationFunction:
    """Test standalone annualization function"""
    
    def test_annualize_monthly(self):
        """Test monthly to annual conversion"""
        monthly_return = 0.02
        monthly_risk = 0.05
        
        annual_return, annual_risk = gf.annualize(monthly_return, monthly_risk, 'M')
        
        assert abs(annual_return - monthly_return * 12) < 1e-10
        assert abs(annual_risk - monthly_risk * np.sqrt(12)) < 1e-10
    
    def test_annualize_daily(self):
        """Test daily to annual conversion"""
        daily_return = 0.001
        daily_risk = 0.02
        
        annual_return, annual_risk = gf.annualize(daily_return, daily_risk, 'D')
        
        assert abs(annual_return - daily_return * 252) < 1e-10
        assert abs(annual_risk - daily_risk * np.sqrt(252)) < 1e-10
    
    def test_annualize_none(self):
        """Test no annualization"""
        return_val = 0.08
        risk_val = 0.15
        
        annual_return, annual_risk = gf.annualize(return_val, risk_val, 'None')
        
        assert abs(annual_return - return_val) < 1e-10
        assert abs(annual_risk - risk_val) < 1e-10
    
    def test_annualize_arrays(self):
        """Test annualization with arrays"""
        returns = np.array([0.02, 0.03, 0.025])
        risks = np.array([0.05, 0.08, 0.06])
        
        annual_returns, annual_risks = gf.annualize(returns, risks, 'M')
        
        np.testing.assert_array_almost_equal(annual_returns, returns * 12, decimal=10)
        np.testing.assert_array_almost_equal(annual_risks, risks * np.sqrt(12), decimal=10)
    
    def test_annualize_invalid(self):
        """Test invalid annualization parameter"""
        with pytest.raises(Exception, match="Unknown way to annualize"):
            gf.annualize(0.02, 0.05, 'Invalid')

class TestEdgeCases:
    """Test edge cases and extreme scenarios"""
    
    def test_zero_returns(self):
        """Test portfolio with zero expected returns"""
        weights = np.array([0.5, 0.5])
        expected_returns = np.array([0.0, 0.0])
        cov_matrix = np.array([[0.04, 0.01], [0.01, 0.09]])
        
        port_return, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        
        assert abs(port_return) < 1e-10  # Should be zero
        assert port_risk > 0  # Risk should still be positive
    
    def test_negative_returns(self, extreme_market_data):
        """Test portfolio with negative expected returns (market crash)"""
        weights = np.array([1/3, 1/3, 1/3])
        crash_returns = extreme_market_data['crash_returns']
        crash_cov = extreme_market_data['crash_cov']
        
        port_return, port_risk = gf.asset_set_perform(weights, crash_returns, crash_cov)
        
        assert port_return < 0  # Should be negative
        assert port_risk > 0    # Risk should still be positive
        
        # Sharpe ratio should be negative with positive risk-free rate
        sr = gf.asset_set_sharpe_ratio(weights, crash_returns, crash_cov, riskFreeRate=0.03)
        assert sr < 0
    
    def test_single_asset_portfolio(self):
        """Test portfolio with single asset"""
        weights = np.array([1.0])
        expected_returns = np.array([0.10])
        cov_matrix = np.array([[0.04]])
        
        port_return, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        
        assert abs(port_return - 0.10) < 1e-10
        assert abs(port_risk - np.sqrt(0.04)) < 1e-10
    
    def test_perfect_correlation(self):
        """Test portfolio with perfectly correlated assets"""
        weights = np.array([0.6, 0.4])
        expected_returns = np.array([0.08, 0.12])
        # Perfect correlation: cov = sigma1 * sigma2 * rho = 0.2 * 0.3 * 1.0 = 0.06
        cov_matrix = np.array([[0.04, 0.06], [0.06, 0.09]])
        
        port_return, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        
        # With perfect correlation, portfolio risk should equal weighted average of individual risks
        individual_risks = np.sqrt(np.diag(cov_matrix))
        expected_risk = np.sum(weights * individual_risks)
        
        assert abs(port_risk - expected_risk) < 1e-10
    
    def test_very_small_weights(self):
        """Test portfolio with very small but valid weights"""
        weights = np.array([0.999999, 0.000001])
        expected_returns = np.array([0.08, 0.12])
        cov_matrix = np.array([[0.04, 0.01], [0.01, 0.09]])
        
        port_return, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        
        # Should be very close to first asset's properties
        assert abs(port_return - 0.08) < 1e-5
        assert abs(port_risk - np.sqrt(0.04)) < 1e-5