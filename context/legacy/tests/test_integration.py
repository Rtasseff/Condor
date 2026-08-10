"""
Integration tests for the complete portfolio optimization workflow

These tests validate that all components work together correctly
from data loading through portfolio optimization and analysis.
"""
import pytest
import numpy as np
import pandas as pd
import sys
import os

# Import all modules for integration testing
from functions import genFin as gf
from functions import genStats as gs
from functions import portOpt as po
from classes import CondorCoreObs as condor

class TestFullOptimizationWorkflow:
    """Test complete end-to-end optimization workflows"""
    
    def test_complete_workflow_basic(self, sample_price_data, mock_price_loader):
        """Test complete optimization workflow from prices to optimized portfolio"""
        symbols = sample_price_data['symbols']
        initial_weights = np.array([1/3, 1/3, 1/3])
        
        # Create portfolio
        portfolio = condor.Portfolio(symbols, initial_weights, priceLoader=mock_price_loader)
        
        # Update with returns calculation
        portfolio.update_properties(timeFrame='M', metric='Relative', method='Normal', annualize=True)
        
        # Verify portfolio has necessary data
        assert portfolio.expectedReturnArray is not None
        assert portfolio.returnCoDispersionSqMatrix is not None
        assert len(portfolio.expectedReturnArray) == 3
        assert portfolio.returnCoDispersionSqMatrix.shape == (3, 3)
        
        # Optimize for maximum Sharpe ratio
        expected_return, risk = portfolio.optimize('Sharpe Ratio', riskFreeRate=0.03, annualize=True)
        
        # Verify results are reasonable
        assert expected_return > 0.03  # Should beat risk-free rate
        assert risk > 0  # Should have some risk
        assert abs(np.sum(portfolio.weights) - 1.0) < 1e-6  # Weights sum to 1
        assert np.all(portfolio.weights >= -1e-6)  # No short selling
        
        # Calculate Sharpe ratio and verify it's reasonable
        sharpe_ratio = (expected_return - 0.03) / risk
        assert sharpe_ratio > 0  # Should be positive
        assert sharpe_ratio < 5   # Sanity check - not unreasonably high
    
    def test_workflow_minimum_variance(self, sample_price_data, mock_price_loader):
        """Test workflow optimizing for minimum variance"""
        symbols = sample_price_data['symbols']
        initial_weights = np.array([1/3, 1/3, 1/3])
        
        portfolio = condor.Portfolio(symbols, initial_weights, priceLoader=mock_price_loader)
        portfolio.update_properties(timeFrame='M', metric='Relative', method='Normal', annualize=True)
        
        # Store initial equal-weight portfolio performance
        initial_return, initial_risk = portfolio.calc_properties(annualize=True, update=False)
        
        # Optimize for minimum variance
        optimized_return, optimized_risk = portfolio.optimize('Dispersion', annualize=True)
        
        # Optimized portfolio should have lower or equal risk
        assert optimized_risk <= initial_risk + 1e-6
        
        # Verify optimization worked
        assert abs(np.sum(portfolio.weights) - 1.0) < 1e-6
        assert np.all(portfolio.weights >= -1e-6)
    
    def test_workflow_different_timeframes(self, sample_price_data, mock_price_loader):
        """Test workflow with different return calculation timeframes"""
        symbols = sample_price_data['symbols']
        weights = np.array([1/3, 1/3, 1/3])
        
        # Test monthly returns
        portfolio_monthly = condor.Portfolio(symbols, weights, priceLoader=mock_price_loader)
        portfolio_monthly.update_properties(timeFrame='M', metric='Relative', method='Normal')
        
        # Test daily returns
        portfolio_daily = condor.Portfolio(symbols, weights, priceLoader=mock_price_loader)
        portfolio_daily.update_properties(timeFrame='D', metric='Relative', method='Normal')
        
        # Both should work without errors
        assert portfolio_monthly.expectedReturnArray is not None
        assert portfolio_daily.expectedReturnArray is not None
        
        # Daily returns should generally be smaller than monthly
        monthly_avg_return = np.mean(portfolio_monthly.expectedReturnArray)
        daily_avg_return = np.mean(portfolio_daily.expectedReturnArray)
        assert daily_avg_return < monthly_avg_return
    
    def test_workflow_robust_vs_normal_statistics(self, sample_price_data, mock_price_loader):
        """Test workflow comparing robust vs normal statistical methods"""
        symbols = sample_price_data['symbols']
        weights = np.array([1/3, 1/3, 1/3])
        
        # Normal statistics
        portfolio_normal = condor.Portfolio(symbols, weights, priceLoader=mock_price_loader)
        portfolio_normal.update_properties(timeFrame='M', metric='Relative', method='Normal')
        
        # Robust statistics
        portfolio_robust = condor.Portfolio(symbols, weights, priceLoader=mock_price_loader)
        portfolio_robust.update_properties(timeFrame='M', metric='Relative', method='Robust')
        
        # Both should produce valid results
        assert portfolio_normal.expectedReturnArray is not None
        assert portfolio_robust.expectedReturnArray is not None
        
        # Results should be different but both reasonable
        normal_returns = portfolio_normal.expectedReturnArray
        robust_returns = portfolio_robust.expectedReturnArray
        
        # Should not be identical (unless data is perfectly normal)
        assert not np.allclose(normal_returns, robust_returns, rtol=1e-10)
        
        # Both should be reasonable in magnitude
        assert np.all(np.abs(normal_returns) < 1.0)  # Monthly returns should be < 100%
        assert np.all(np.abs(robust_returns) < 1.0)

class TestDataValidationWorkflow:
    """Test workflows with data quality issues"""
    
    def test_missing_data_handling(self, mock_price_loader):
        """Test workflow handles missing data gracefully"""
        # Create price data with some NaN values
        dates = pd.date_range('2020-01-01', periods=100, freq='D')
        prices = np.random.normal(1.001, 0.02, (100, 2)).cumprod(axis=0) * 100
        
        # Introduce some NaN values
        prices[10:15, 0] = np.nan  # Missing data for first asset
        prices[20:25, 1] = np.nan  # Missing data for second asset
        
        # Create custom mock loader with NaN data
        class NaNMockLoader:
            def get_assets_df(self, syms=None):
                return pd.DataFrame(prices, index=dates, columns=['ASSET_A', 'ASSET_B'])
            
            def get_assets_np(self, syms=None):
                df = self.get_assets_df(syms)
                return df.values, df.index.values, df.columns.values
            
            def set_target_asset_symbols(self, syms):
                pass
        
        nan_loader = NaNMockLoader()
        symbols = ['ASSET_A', 'ASSET_B']
        weights = np.array([0.5, 0.5])
        
        # Should handle NaN data without crashing
        portfolio = condor.Portfolio(symbols, weights, priceLoader=nan_loader)
        portfolio.update_properties(timeFrame='M', metric='Relative', method='Normal')
        
        # Should produce valid results (NaNs removed pairwise)
        assert portfolio.expectedReturnArray is not None
        assert not np.any(np.isnan(portfolio.expectedReturnArray))
        assert not np.any(np.isnan(portfolio.returnCoDispersionSqMatrix))
    
    def test_extreme_market_conditions(self, extreme_market_data):
        """Test workflow with extreme market conditions (crash scenario)"""
        crash_returns = extreme_market_data['crash_returns']
        crash_cov = extreme_market_data['crash_cov']
        weights = np.array([1/3, 1/3, 1/3])
        
        # Test that optimization still works in crash scenario
        result_sharpe = po.max_sharpe_ratio(crash_returns, crash_cov, riskFreeRate=0.03)
        result_minvar = po.min_dispersion(crash_returns, crash_cov)
        
        # Both optimizations should succeed
        assert result_sharpe.success
        assert result_minvar.success
        
        # Results should be valid portfolios
        assert abs(np.sum(result_sharpe.x) - 1.0) < 1e-6
        assert abs(np.sum(result_minvar.x) - 1.0) < 1e-6
        
        # Portfolio performance should reflect crash conditions
        crash_return, crash_risk = gf.asset_set_perform(weights, crash_returns, crash_cov)
        assert crash_return < 0  # Negative returns in crash
        assert crash_risk > 0    # But still positive risk
    
    def test_single_asset_workflow(self, sample_price_data):
        """Test workflow with single asset (edge case)"""
        # Extract single asset data
        single_prices = sample_price_data['prices'][:, 0:1]  # Keep as 2D array
        dates = sample_price_data['dates']
        
        class SingleAssetLoader:
            def get_assets_df(self, syms=None):
                return pd.DataFrame(single_prices, index=dates, columns=['SINGLE_ASSET'])
            
            def get_assets_np(self, syms=None):
                df = self.get_assets_df(syms)
                return df.values, df.index.values, df.columns.values
            
            def set_target_asset_symbols(self, syms):
                pass
        
        single_loader = SingleAssetLoader()
        symbols = ['SINGLE_ASSET']
        weights = np.array([1.0])
        
        # Should work with single asset
        portfolio = condor.Portfolio(symbols, weights, priceLoader=single_loader)
        portfolio.update_properties(timeFrame='M', metric='Relative', method='Normal')
        
        # Should produce scalar results
        assert len(portfolio.expectedReturnArray) == 1
        assert portfolio.returnCoDispersionSqMatrix.shape == (1, 1)
        
        # Optimization should still work (trivial case)
        expected_return, risk = portfolio.optimize('Sharpe Ratio', riskFreeRate=0.03)
        assert abs(portfolio.weights[0] - 1.0) < 1e-6  # Should be 100% in single asset

class TestWorkflowConsistency:
    """Test consistency across different calculation methods"""
    
    def test_manual_vs_class_calculations(self, sample_price_data, mock_price_loader):
        """Test that manual calculations match class-based calculations"""
        symbols = sample_price_data['symbols']
        weights = np.array([0.4, 0.4, 0.2])
        
        # Get raw price data
        prices, dates, syms = mock_price_loader.get_assets_np(symbols)
        
        # Manual calculation
        returns_manual = gf.returns(prices, period=21, metric='Relative')
        expected_returns_manual = gf.returnExp(returns_manual, method='Normal')
        cov_matrix_manual = gf.returnCoDispSq(returns_manual, method='Normal')
        
        # Class-based calculation
        portfolio = condor.Portfolio(symbols, weights, priceLoader=mock_price_loader)
        portfolio.update_properties(timeFrame='M', metric='Relative', method='Normal')
        
        # Results should be very similar
        np.testing.assert_array_almost_equal(
            expected_returns_manual, portfolio.expectedReturnArray, decimal=8
        )
        np.testing.assert_array_almost_equal(
            cov_matrix_manual, portfolio.returnCoDispersionSqMatrix, decimal=8
        )
    
    def test_optimization_consistency(self, three_asset_portfolio):
        """Test that different optimization approaches give consistent results"""
        expected_returns = three_asset_portfolio['expected_returns']
        cov_matrix = three_asset_portfolio['cov_matrix']
        
        # Direct optimization function call
        result_direct = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.03)
        
        # Portfolio class optimization
        symbols = three_asset_portfolio['symbols']
        weights = three_asset_portfolio['equal_weights']
        
        # Create mock portfolio with known data
        class KnownDataPortfolio(condor.Portfolio):
            def __init__(self, symbols, weights):
                self.assets = symbols  # Simplified for testing
                self.weights = weights
                self.expectedReturnArray = expected_returns
                self.returnCoDispersionSqMatrix = cov_matrix
                self.timeFrame = 'M'
                self.annualize = True
                
                # Initialize other attributes
                self.expectedReturn = None
                self.returnDispersion = None
        
        portfolio = KnownDataPortfolio(symbols, weights)
        optimal_weights = portfolio.optimal('Sharpe Ratio', riskFreeRate=0.03, annualize=False)
        
        # Results should be very similar
        np.testing.assert_array_almost_equal(result_direct.x, optimal_weights, decimal=6)
    
    def test_annualization_consistency(self, simple_portfolio_data):
        """Test that annualization is consistent across different calculation paths"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Method 1: Calculate then annualize
        monthly_return, monthly_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        annual_return_1, annual_risk_1 = gf.annualize(monthly_return, monthly_risk, 'M')
        
        # Method 2: Annualize during calculation
        annual_return_2, annual_risk_2 = gf.asset_set_perform(
            weights, expected_returns, cov_matrix, annualizeBy='M'
        )
        
        # Should be identical
        assert abs(annual_return_1 - annual_return_2) < 1e-10
        assert abs(annual_risk_1 - annual_risk_2) < 1e-10

class TestRegressionPrevention:
    """Test cases to prevent regressions in known working functionality"""
    
    def test_known_portfolio_results(self):
        """Test specific portfolio with known expected results"""
        # Portfolio from the original notebook analysis
        weights = np.array([0.6, 0.4])
        expected_returns = np.array([0.08, 0.12])  # 8% and 12% expected returns
        cov_matrix = np.array([[0.04, 0.01], [0.01, 0.09]])  # Known covariance
        
        # Portfolio return should be weighted average
        port_return, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        expected_port_return = 0.6 * 0.08 + 0.4 * 0.12  # = 0.096
        
        assert abs(port_return - expected_port_return) < 1e-10
        
        # Sharpe ratio calculation
        risk_free_rate = 0.03
        sharpe_ratio = gf.asset_set_sharpe_ratio(weights, expected_returns, cov_matrix, 
                                                 riskFreeRate=risk_free_rate)
        expected_sharpe = (port_return - risk_free_rate) / port_risk
        
        assert abs(sharpe_ratio - expected_sharpe) < 1e-10
    
    def test_optimization_known_solution(self):
        """Test optimization with problem that has known optimal solution"""
        # Simple case: one asset clearly dominates
        expected_returns = np.array([0.05, 0.15])  # Second asset much better
        cov_matrix = np.array([[0.04, 0.01], [0.01, 0.04]])  # Similar risk
        
        result = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.03)
        
        # Should heavily favor second asset
        assert result.success
        assert result.x[1] > 0.8  # Should put most weight in better asset
        assert result.x[0] < 0.2  # Minimal weight in worse asset
    
    def test_mathematical_properties(self, simple_portfolio_data):
        """Test that mathematical properties hold"""
        weights = simple_portfolio_data['weights']
        expected_returns = simple_portfolio_data['expected_returns']
        cov_matrix = simple_portfolio_data['cov_matrix']
        
        # Portfolio return linearity
        port_return, _ = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        manual_return = np.sum(weights * expected_returns)
        assert abs(port_return - manual_return) < 1e-10
        
        # Covariance matrix symmetry
        assert np.allclose(cov_matrix, cov_matrix.T)
        
        # Positive semi-definite (eigenvalues >= 0)
        eigenvals = np.linalg.eigvals(cov_matrix)
        assert np.all(eigenvals >= -1e-10)  # Allow small numerical errors
        
        # Risk calculation
        _, port_risk = gf.asset_set_perform(weights, expected_returns, cov_matrix)
        manual_risk = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        assert abs(port_risk - manual_risk) < 1e-10

class TestPerformanceAndScalability:
    """Test performance with larger portfolios"""
    
    def test_large_portfolio_optimization(self):
        """Test optimization with larger number of assets"""
        n_assets = 10
        np.random.seed(42)  # For reproducibility
        
        # Generate random but reasonable portfolio data
        expected_returns = np.random.uniform(0.05, 0.15, n_assets)
        
        # Generate positive semi-definite covariance matrix
        A = np.random.randn(n_assets, n_assets)
        cov_matrix = np.dot(A, A.T) * 0.01  # Scale to reasonable variance levels
        
        # Optimization should still work
        result = po.max_sharpe_ratio(expected_returns, cov_matrix, riskFreeRate=0.03)
        
        assert result.success
        assert abs(np.sum(result.x) - 1.0) < 1e-6
        assert len(result.x) == n_assets
        assert np.all(result.x >= -1e-6)
    
    def test_efficient_frontier_scaling(self):
        """Test efficient frontier calculation with many points"""
        expected_returns = np.array([0.08, 0.12, 0.15])
        cov_matrix = np.array([
            [0.04, 0.01, 0.02],
            [0.01, 0.09, 0.03], 
            [0.02, 0.03, 0.16]
        ])
        
        # Test with many frontier points
        target_returns = np.linspace(0.08, 0.15, 50)
        
        weights = po.calc_efficient_frontier(expected_returns, cov_matrix, target_returns)
        
        # Should handle many points without issues
        assert weights.shape == (50, 3)
        
        # All portfolios should be valid
        for i in range(50):
            assert abs(np.sum(weights[i]) - 1.0) < 1e-4
            assert np.all(weights[i] >= -1e-6)