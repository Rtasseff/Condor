"""
Unit tests for portfolio optimization functions (portOpt.py)

These tests validate optimization algorithms including Sharpe ratio maximization,
minimum variance optimization, and efficient frontier calculations.
"""
import pytest
import numpy as np
import sys
import os

# Import the modules under test
from functions import portOpt as po
from functions import genFin as gf

class TestMaxSharpeRatio:
    """Test Sharpe ratio maximization optimization"""
    
    def test_max_sharpe_basic(self, three_asset_portfolio):
        """Test basic Sharpe ratio maximization"""
        expected_returns = three_asset_portfolio['expected_returns']
        cov_matrix = three_asset_portfolio['cov_matrix']
        
        result = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.03)
        
        # Optimization should succeed
        assert result.success
        
        # Weights should sum to 1
        assert abs(np.sum(result.x) - 1.0) < 1e-6
        
        # No short selling (all weights >= 0)
        assert all(result.x >= -1e-6)  # Allow small numerical errors
        
        # Should prefer higher return assets
        # Asset 2 (index 2) has highest return (0.15), should have highest weight
        max_weight_index = np.argmax(result.x)
        max_return_index = np.argmax(expected_returns)
        assert max_weight_index == max_return_index
    
    def test_max_sharpe_zero_risk_free(self, simple_portfolio_data):
        """Test Sharpe ratio maximization with zero risk-free rate"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        result = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.0)
        
        assert result.success
        assert abs(np.sum(result.x) - 1.0) < 1e-6
        
        # Calculate achieved Sharpe ratio
        weights = result.x
        port_return, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        sharpe_ratio = port_return / port_risk
        
        # Should be positive and reasonable
        assert sharpe_ratio > 0
        assert sharpe_ratio < 10  # Sanity check
    
    def test_max_sharpe_high_risk_free(self, simple_portfolio_data):
        """Test Sharpe ratio maximization with high risk-free rate"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Set risk-free rate higher than expected returns
        high_rf_rate = 0.15
        
        result = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=high_rf_rate)
        
        # Should still find a solution (may have negative Sharpe ratio)
        assert result.success
        assert abs(np.sum(result.x) - 1.0) < 1e-6
    
    def test_max_sharpe_custom_constraints(self, simple_portfolio_data):
        """Test Sharpe ratio maximization with custom weight constraints"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Limit weights to 0.3-0.7 range
        custom_constraints = (0.3, 0.7)
        
        result = po.max_sharpe_ratio(expected_returns, cov_matrix, 
                                     constraintSet=custom_constraints, riskFreeRate=0.03)
        
        assert result.success
        assert abs(np.sum(result.x) - 1.0) < 1e-6
        
        # All weights should be within specified bounds
        for weight in result.x:
            assert weight >= 0.3 - 1e-6
            assert weight <= 0.7 + 1e-6
    
    def test_max_sharpe_annualized(self, simple_portfolio_data):
        """Test Sharpe ratio maximization with annualization"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Test monthly annualization
        result_monthly = po.max_sharpe_ratio(expected_returns, cov_matrix, 
                                             riskFreeRate=0.03, annualizeBy='M')
        
        # Test daily annualization  
        result_daily = po.max_sharpe_ratio(expected_returns, cov_matrix,
                                           riskFreeRate=0.03, annualizeBy='D')
        
        # Both should succeed and give similar weight allocations
        assert result_monthly.success
        assert result_daily.success
        
        # Weights might be slightly different due to annualization, but should be similar
        weight_diff = np.max(np.abs(result_monthly.x - result_daily.x))
        assert weight_diff < 0.1  # Allow some difference due to optimization

class TestMinimumVariance:
    """Test minimum variance optimization"""
    
    def test_min_dispersion_basic(self, three_asset_portfolio):
        """Test basic minimum variance optimization"""
        expected_returns = three_asset_portfolio['expected_returns']
        cov_matrix = three_asset_portfolio['cov_matrix']
        
        result = po.min_dispersion(expected_returns, cov_matrix)
        
        # Optimization should succeed
        assert result.success
        
        # Weights should sum to 1
        assert abs(np.sum(result.x) - 1.0) < 1e-6
        
        # No short selling
        assert all(result.x >= -1e-6)
        
        # Should prefer lower risk assets
        # Asset 0 has lowest variance (0.04), should have significant weight
        variances = np.diag(cov_matrix)
        min_var_index = np.argmin(variances)
        
        # The asset with minimum variance should have non-trivial weight
        assert result.x[min_var_index] > 0.1
    
    def test_min_dispersion_with_target_return(self, simple_portfolio_data):
        """Test minimum variance with target return constraint"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Set target return between min and max individual returns
        target_return = 0.10  # Between 0.08 and 0.12
        
        result = po.min_dispersion(expected_returns, cov_matrix, 
                                   returnTarget=target_return)
        
        assert result.success
        assert abs(np.sum(result.x) - 1.0) < 1e-6
        
        # Check that target return is achieved (approximately)
        achieved_return, _ = gf.asset_set_perform(result.x, expected_returns, cov_matrix)
        assert abs(achieved_return - target_return) < 1e-4
    
    def test_min_dispersion_impossible_target(self, simple_portfolio_data):
        """Test minimum variance with impossible target return"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Set target return higher than maximum possible
        impossible_target = 0.20  # Higher than max return of 0.12
        
        result = po.min_dispersion(expected_returns, cov_matrix,
                                   returnTarget=impossible_target)
        
        # Optimization should fail or find boundary solution
        # Either not successful, or solution is at boundary (100% in highest return asset)
        if result.success:
            # If successful, should be 100% in highest return asset
            max_return_index = np.argmax(expected_returns)
            assert result.x[max_return_index] > 0.99
    
    def test_min_dispersion_low_target(self, simple_portfolio_data):
        """Test minimum variance with very low target return"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Set target return lower than minimum individual return
        low_target = 0.05  # Lower than min return of 0.08
        
        result = po.min_dispersion(expected_returns, cov_matrix,
                                   returnTarget=low_target)
        
        # Should fail or find boundary solution (100% in lowest return asset)
        if result.success:
            min_return_index = np.argmin(expected_returns)
            assert result.x[min_return_index] > 0.99
    
    def test_min_dispersion_annualized(self, simple_portfolio_data):
        """Test minimum variance with annualization"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        result_none = po.min_dispersion(expected_returns, cov_matrix, annualizeBy='None')
        result_monthly = po.min_dispersion(expected_returns, cov_matrix, annualizeBy='M')
        
        # Both should succeed
        assert result_none.success
        assert result_monthly.success
        
        # Weights should be identical (annualization doesn't change optimal weights)
        np.testing.assert_array_almost_equal(result_none.x, result_monthly.x, decimal=6)

class TestEfficientFrontier:
    """Test efficient frontier calculation"""
    
    def test_calc_efficient_frontier_basic(self, simple_portfolio_data):
        """Test basic efficient frontier calculation"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Create range of target returns
        min_return = np.min(expected_returns)
        max_return = np.max(expected_returns)
        target_returns = np.linspace(min_return, max_return, 5)
        
        weights = po.calc_efficient_frontier(expected_returns, cov_matrix, target_returns)
        
        # Should return correct shape
        assert weights.shape == (5, 2)  # 5 targets, 2 assets
        
        # Each portfolio should have weights summing to 1
        for i in range(5):
            assert abs(np.sum(weights[i]) - 1.0) < 1e-4
            
        # No short selling
        assert np.all(weights >= -1e-6)
        
        # First portfolio should be 100% in low-return asset
        assert weights[0, 0] > 0.99  # First asset has lower return
        
        # Last portfolio should be 100% in high-return asset  
        assert weights[-1, 1] > 0.99  # Second asset has higher return
    
    def test_calc_efficient_frontier_three_assets(self, three_asset_portfolio):
        """Test efficient frontier with three assets"""
        expected_returns = three_asset_portfolio['expected_returns']
        cov_matrix = three_asset_portfolio['cov_matrix']
        
        # Get minimum variance return for starting point
        min_var_result = po.min_dispersion(expected_returns, cov_matrix)
        min_var_return, _ = gf.asset_set_perform(min_var_result.x, expected_returns, cov_matrix)
        
        max_return = np.max(expected_returns)
        target_returns = np.linspace(min_var_return, max_return, 10)
        
        weights = po.calc_efficient_frontier(expected_returns, cov_matrix, target_returns)
        
        # Should return correct shape
        assert weights.shape == (10, 3)  # 10 targets, 3 assets
        
        # Each portfolio should have valid weights
        for i in range(10):
            assert abs(np.sum(weights[i]) - 1.0) < 1e-4
            assert np.all(weights[i] >= -1e-6)
    
    def test_calc_efficient_frontier_risk_progression(self, simple_portfolio_data):
        """Test that efficient frontier shows increasing risk with return"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        min_return = np.min(expected_returns)
        max_return = np.max(expected_returns)
        target_returns = np.linspace(min_return, max_return, 5)
        
        weights = po.calc_efficient_frontier(expected_returns, cov_matrix, target_returns)
        
        # Calculate risk for each portfolio
        risks = []
        for i in range(5):
            _, risk = gf.asset_set_perform(weights[i], expected_returns, cov_matrix)
            risks.append(risk)
        
        risks = np.array(risks)
        
        # Risk should generally increase along the frontier
        # (allowing for small numerical variations)
        for i in range(1, len(risks)):
            assert risks[i] >= risks[i-1] - 1e-6
    
    def test_calc_efficient_frontier_with_annualization(self, simple_portfolio_data):
        """Test efficient frontier with annualization"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        target_returns = np.linspace(0.08, 0.12, 3)
        
        weights_none = po.calc_efficient_frontier(expected_returns, cov_matrix, 
                                                  target_returns, annualizeBy='None')
        weights_monthly = po.calc_efficient_frontier(expected_returns, cov_matrix,
                                                     target_returns * 12, annualizeBy='M')
        
        # Weights should be similar (accounting for annualization in targets)
        np.testing.assert_array_almost_equal(weights_none, weights_monthly, decimal=4)

class TestHelperFunctions:
    """Test helper functions used in optimization"""
    
    def test_asset_set_disp(self, simple_portfolio_data):
        """Test _asset_set_disp helper function"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Should return only the dispersion (risk)
        result = po._asset_set_disp(weights, expected_returns, cov_matrix)
        
        # Compare with full calculation
        _, expected_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        
        assert abs(result - expected_risk) < 1e-10
        assert isinstance(result, float)
    
    def test_asset_set_exp(self, simple_portfolio_data):
        """Test _asset_set_exp helper function"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Should return only the expected return
        result = po._asset_set_exp(weights, expected_returns, cov_matrix)
        
        # Compare with full calculation
        expected_return, _ = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        
        assert abs(result - expected_return) < 1e-10
        assert isinstance(result, float)
    
    def test_helper_functions_with_annualization(self, simple_portfolio_data):
        """Test helper functions with annualization"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Test with monthly annualization
        risk_monthly = po._asset_set_disp(weights, expected_returns, cov_matrix, 'M')
        return_monthly = po._asset_set_exp(weights, expected_returns, cov_matrix, 'M')
        
        # Test without annualization
        risk_none = po._asset_set_disp(weights, expected_returns, cov_matrix, 'None')
        return_none = po._asset_set_exp(weights, expected_returns, cov_matrix, 'None')
        
        # Check annualization factors
        assert abs(return_monthly - return_none * 12) < 1e-10
        assert abs(risk_monthly - risk_none * np.sqrt(12)) < 1e-10

class TestOptimizationEdgeCases:
    """Test optimization with edge cases and extreme scenarios"""
    
    def test_single_asset_optimization(self):
        """Test optimization with single asset"""
        expected_returns = np.array([0.10])
        cov_matrix = np.array([[0.04]])
        
        # Sharpe ratio optimization
        result_sharpe = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.03)
        assert result_sharpe.success
        assert abs(result_sharpe.x[0] - 1.0) < 1e-6
        
        # Minimum variance optimization
        result_minvar = po.min_dispersion(expected_returns, cov_matrix)
        assert result_minvar.success
        assert abs(result_minvar.x[0] - 1.0) < 1e-6
    
    def test_identical_assets(self):
        """Test optimization with identical assets"""
        # Two identical assets
        expected_returns = np.array([0.10, 0.10])
        cov_matrix = np.array([[0.04, 0.04], [0.04, 0.04]])
        
        result = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.03)
        
        # Should find a valid solution
        assert result.success
        assert abs(np.sum(result.x) - 1.0) < 1e-6
        
        # Any combination of weights should be equally optimal
        # (solver may pick any valid combination)
    
    def test_zero_correlation_assets(self):
        """Test optimization with uncorrelated assets"""
        expected_returns = np.array([0.08, 0.12])
        # Zero correlation: off-diagonal elements are zero
        cov_matrix = np.array([[0.04, 0.00], [0.00, 0.09]])
        
        result = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.03)
        
        assert result.success
        assert abs(np.sum(result.x) - 1.0) < 1e-6
        
        # Should prefer higher return asset, but diversify due to different risks
        assert result.x[1] > result.x[0]  # Higher return asset gets more weight
        assert result.x[0] > 0.1  # But lower return asset still gets some weight
    
    def test_extreme_risk_aversion(self):
        """Test optimization with extremely low-risk vs high-risk assets"""
        expected_returns = np.array([0.02, 0.15])  # Very conservative vs aggressive
        cov_matrix = np.array([[0.0001, 0.001], [0.001, 0.25]])  # Very low vs high risk
        
        # Minimum variance should heavily favor low-risk asset
        result_minvar = po.min_dispersion(expected_returns, cov_matrix)
        assert result_minvar.success
        assert result_minvar.x[0] > 0.9  # Should be mostly in low-risk asset
        
        # Sharpe ratio optimization depends on risk-free rate
        result_sharpe = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.01)
        assert result_sharpe.success
    
    def test_negative_expected_returns(self, extreme_market_data):
        """Test optimization with negative expected returns"""
        crash_returns = extreme_market_data['crash_returns']
        crash_cov = extreme_market_data['crash_cov']
        
        # Even with negative returns, optimization should find valid solution
        result = po.min_dispersion(crash_returns, crash_cov)
        
        assert result.success
        assert abs(np.sum(result.x) - 1.0) < 1e-6
        assert np.all(result.x >= -1e-6)
        
        # Should minimize losses by choosing least negative returns and correlations
    
    def test_optimization_convergence_tolerance(self, simple_portfolio_data):
        """Test that optimization results are consistent across multiple runs"""
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Run optimization multiple times
        results = []
        for _ in range(5):
            result = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.03)
            assert result.success
            results.append(result.x)
        
        # All results should be very similar
        for i in range(1, len(results)):
            weight_diff = np.max(np.abs(results[i] - results[0]))
            assert weight_diff < 1e-6  # Very tight tolerance for deterministic problem