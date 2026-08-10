"""
Unit tests for statistical functions (genStats.py)

These tests validate robust vs normal statistical methods,
covariance calculations, and outlier handling.
"""
import pytest
import numpy as np
import sys
import os

# Import the module under test
from functions import genStats as gs

class TestExpectedValue:
    """Test expected value calculations"""
    
    def test_expected_normal_method(self):
        """Test expected value using normal method (mean)"""
        data = np.array([1, 2, 3, 4, 5])
        
        result = gs.expected(data, 'Normal')
        expected = np.mean(data)
        
        assert abs(result - expected) < 1e-10
        assert abs(result - 3.0) < 1e-10
    
    def test_expected_robust_method(self):
        """Test expected value using robust method (median)"""
        data = np.array([1, 2, 3, 4, 5])
        
        result = gs.expected(data, 'Robust')
        expected = np.median(data)
        
        assert abs(result - expected) < 1e-10
        assert abs(result - 3.0) < 1e-10
    
    def test_expected_with_outliers(self):
        """Test that robust method handles outliers better than normal"""
        data = np.array([1, 2, 3, 4, 5, 100])  # 100 is clear outlier
        
        normal_mean = gs.expected(data, 'Normal')
        robust_median = gs.expected(data, 'Robust')
        
        # Median should be less affected by outlier
        assert robust_median == 3.5  # Median of [1,2,3,4,5,100]
        assert normal_mean > robust_median  # Mean pulled up by outlier
        assert normal_mean > 10  # Mean should be significantly higher
    
    def test_expected_with_nans(self):
        """Test that NaN values are handled correctly"""
        data = np.array([1, 2, np.nan, 4, 5])
        
        # Should work without NaN affecting result
        normal_result = gs.expected(data, 'Normal')
        robust_result = gs.expected(data, 'Robust')
        
        assert not np.isnan(normal_result)
        assert not np.isnan(robust_result)
        
        # Should equal results from clean data
        clean_data = np.array([1, 2, 4, 5])
        assert abs(normal_result - np.mean(clean_data)) < 1e-10
        assert abs(robust_result - np.median(clean_data)) < 1e-10
    
    def test_expected_invalid_method(self):
        """Test that invalid method raises exception"""
        data = np.array([1, 2, 3, 4, 5])
        
        with pytest.raises(Exception, match="Method not known"):
            gs.expected(data, 'InvalidMethod')

class TestDispersion:
    """Test dispersion (spread) calculations"""
    
    def test_disper_normal_method(self):
        """Test dispersion using normal method (standard deviation)"""
        data = np.array([1, 2, 3, 4, 5])
        
        result = gs.disper(data, 'Normal')
        expected = np.std(data)
        
        assert abs(result - expected) < 1e-10
    
    def test_disper_mad_method(self):
        """Test dispersion using MAD method"""
        data = np.array([1, 2, 3, 4, 5])
        
        result = gs.disper(data, 'MAD')
        
        # MAD should be positive and reasonable
        assert result > 0
        assert result < 10  # Sanity check for reasonable scale
    
    def test_disper_with_outliers(self):
        """Test that robust dispersion handles outliers better"""
        data = np.array([1, 2, 3, 4, 5, 100])  # 100 is outlier
        
        normal_std = gs.disper(data, 'Normal')
        robust_mad = gs.disper(data, 'MAD')
        
        # Standard deviation should be much larger due to outlier
        assert normal_std > robust_mad
        assert normal_std > 30  # Should be significantly affected
        assert robust_mad < 5   # Should be less affected
    
    def test_disper_with_nans(self):
        """Test that NaN values are handled in dispersion calculation"""
        data = np.array([1, 2, np.nan, 4, 5])
        
        result = gs.disper(data, 'Normal')
        
        assert not np.isnan(result)
        assert result > 0
    
    def test_disper_constant_data(self):
        """Test dispersion with constant data (should be zero or near zero)"""
        data = np.array([5, 5, 5, 5, 5])
        
        normal_result = gs.disper(data, 'Normal')
        mad_result = gs.disper(data, 'MAD')
        
        assert abs(normal_result) < 1e-10  # Should be exactly zero
        assert abs(mad_result) < 1e-10     # Should be exactly zero
    
    def test_disper_invalid_method(self):
        """Test that invalid method raises exception"""
        data = np.array([1, 2, 3, 4, 5])
        
        with pytest.raises(Exception, match="Method name not known"):
            gs.disper(data, 'InvalidMethod')

class TestCoMAD:
    """Test Co-variate Median Absolute Deviation"""
    
    def test_comad_identical_series(self):
        """Test CoMAD with identical series (should equal MAD squared)"""
        x = np.array([1, 2, 3, 4, 5])
        
        comad_result = gs.comad(x, x)
        mad_squared = gs.disper(x, 'MAD') ** 2
        
        # Should be approximately equal (within numerical precision)
        assert abs(comad_result - mad_squared) < 1e-6
    
    def test_comad_perfectly_correlated(self):
        """Test CoMAD with perfectly correlated series"""
        x = np.array([1, 2, 3, 4, 5])
        y = 2 * x + 3  # Perfect linear relationship
        
        comad_result = gs.comad(x, y)
        
        # Should be positive for positively correlated data
        assert comad_result > 0
    
    def test_comad_uncorrelated(self):
        """Test CoMAD with uncorrelated series"""
        np.random.seed(42)
        x = np.random.normal(0, 1, 100)
        y = np.random.normal(0, 1, 100)  # Independent random series
        
        comad_result = gs.comad(x, y)
        
        # Should be close to zero for uncorrelated data
        assert abs(comad_result) < 0.5  # Allow some random variation
    
    def test_comad_anticorrelated(self):
        """Test CoMAD with anti-correlated series"""
        x = np.array([1, 2, 3, 4, 5])
        y = -x  # Perfect negative correlation
        
        comad_result = gs.comad(x, y)
        
        # Should be negative for negatively correlated data
        assert comad_result < 0

class TestCovarianceMatrix:
    """Test covariance/co-dispersion matrix calculations"""
    
    def test_codisper_sq_normal_method(self):
        """Test covariance matrix using normal method"""
        # Create simple 2-variable dataset
        data = np.array([
            [1, 2],
            [2, 4], 
            [3, 6],
            [4, 8]
        ])
        
        result = gs.codisper_sq(data, 'Normal')
        
        # Should be 2x2 symmetric matrix
        assert result.shape == (2, 2)
        assert abs(result[0, 1] - result[1, 0]) < 1e-10  # Symmetric
        
        # Diagonal should be variances
        assert result[0, 0] > 0
        assert result[1, 1] > 0
        
        # Compare with numpy covariance (should be similar)
        np_cov = np.cov(data.T, bias=True)  # Use population covariance
        np.testing.assert_array_almost_equal(result, np_cov, decimal=8)
    
    def test_codisper_sq_comad_method(self):
        """Test co-dispersion matrix using CoMAD method"""
        data = np.array([
            [1, 2],
            [2, 4],
            [3, 6], 
            [4, 8]
        ])
        
        result = gs.codisper_sq(data, 'CoMAD')
        
        # Should be 2x2 symmetric matrix
        assert result.shape == (2, 2)
        assert abs(result[0, 1] - result[1, 0]) < 1e-10  # Symmetric
        
        # Diagonal should be positive
        assert result[0, 0] > 0
        assert result[1, 1] > 0
    
    def test_codisper_sq_three_variables(self):
        """Test covariance matrix with three variables"""
        np.random.seed(42)
        data = np.random.normal(0, 1, (50, 3))
        
        result = gs.codisper_sq(data, 'Normal')
        
        # Should be 3x3 symmetric matrix
        assert result.shape == (3, 3)
        
        # Check symmetry
        for i in range(3):
            for j in range(3):
                assert abs(result[i, j] - result[j, i]) < 1e-10
        
        # Diagonal should be positive (variances)
        for i in range(3):
            assert result[i, i] > 0
    
    def test_codisper_sq_with_nans(self):
        """Test covariance matrix handles NaN values pairwise"""
        data = np.array([
            [1, 2, np.nan],
            [2, np.nan, 6],
            [3, 6, 9],
            [4, 8, 12]
        ])
        
        result = gs.codisper_sq(data, 'Normal')
        
        # Should still produce valid 3x3 matrix
        assert result.shape == (3, 3)
        assert not np.any(np.isnan(result))
        
        # Should be symmetric
        for i in range(3):
            for j in range(3):
                assert abs(result[i, j] - result[j, i]) < 1e-10
    
    def test_codisper_sq_perfect_correlation(self):
        """Test covariance matrix with perfectly correlated variables"""
        x = np.array([1, 2, 3, 4, 5])
        y = 2 * x  # Perfect correlation
        data = np.column_stack([x, y])
        
        result = gs.codisper_sq(data, 'Normal')
        
        # Correlation coefficient should be 1
        corr = result[0, 1] / np.sqrt(result[0, 0] * result[1, 1])
        assert abs(corr - 1.0) < 1e-10
    
    def test_codisper_sq_invalid_method(self):
        """Test that invalid method raises exception"""
        data = np.array([[1, 2], [3, 4]])
        
        with pytest.raises(Exception, match="Method name not known"):
            gs.codisper_sq(data, 'InvalidMethod')

class TestModelFitting:
    """Test statistical model fitting functions"""
    
    def test_fit_model_basic(self):
        """Test basic OLS model fitting"""
        # Create simple linear relationship: y = 2x + 1 + noise
        np.random.seed(42)
        x = np.linspace(0, 10, 50)
        y = 2 * x + 1 + np.random.normal(0, 0.1, 50)
        
        # Create design matrix (with constant term)
        from statsmodels.tools import add_constant
        X = add_constant(x.reshape(-1, 1))
        
        ic, rsq, yHat, model = gs.fit_model(X, y)
        
        # Should have reasonable fit
        assert rsq > 0.9  # High R-squared for linear relationship
        assert len(yHat) == len(y)
        
        # Coefficients should be close to true values [1, 2]
        params = model.params
        assert abs(params[0] - 1.0) < 0.2  # Intercept
        assert abs(params[1] - 2.0) < 0.2  # Slope
    
    def test_x2X_polynomial(self):
        """Test design matrix creation for polynomial models"""
        x = np.array([1, 2, 3, 4, 5])
        
        # Test quadratic polynomial
        X = gs.x2X(x, 'Polynomial Order 2')
        
        # Should have 3 columns: constant, x, x^2
        assert X.shape == (5, 3)
        
        # Check first column is constants (1s)
        np.testing.assert_array_equal(X[:, 0], np.ones(5))
        
        # Check second column is x
        np.testing.assert_array_equal(X[:, 1], x)
        
        # Check third column is x^2
        np.testing.assert_array_equal(X[:, 2], x**2)
    
    def test_x2X_exponential(self):
        """Test design matrix creation for exponential model"""
        x = np.array([1, 2, 3, 4, 5])
        
        X = gs.x2X(x, 'Exp')
        
        # Should have 2 columns: constant, x
        assert X.shape == (5, 2)
        np.testing.assert_array_equal(X[:, 0], np.ones(5))
        np.testing.assert_array_equal(X[:, 1], x)
    
    def test_x2X_logarithmic(self):
        """Test design matrix creation for logarithmic model"""
        x = np.array([1, 2, 3, 4, 5])
        
        X = gs.x2X(x, 'Log')
        
        # Should have 2 columns: constant, log(x+1)
        assert X.shape == (5, 2)
        np.testing.assert_array_equal(X[:, 0], np.ones(5))
        np.testing.assert_array_equal(X[:, 1], np.log(x + 1))
    
    def test_x2X_invalid_model(self):
        """Test that invalid model name raises exception"""
        x = np.array([1, 2, 3, 4, 5])
        
        with pytest.raises(Exception, match="Model name not known"):
            gs.x2X(x, 'InvalidModel')

class TestAutocorrelation:
    """Test autocorrelation function"""
    
    def test_acf_white_noise(self):
        """Test ACF with white noise (should show no correlation)"""
        np.random.seed(42)
        x = np.random.normal(0, 1, 100)
        
        acf_vals, lags, acf_conf = gs.acf(x, fracLag=0.2, ci=95)
        
        # First lag should be 1.0 (perfect self-correlation)
        assert abs(acf_vals[0] - 1.0) < 1e-10
        
        # Other lags should be small for white noise
        assert np.max(np.abs(acf_vals[1:])) < 0.3  # Allow some random variation
        
        # Should return appropriate number of lags
        expected_lags = int(0.2 * 100) + 1
        assert len(acf_vals) == expected_lags
        assert len(lags) == expected_lags
    
    def test_acf_trending_data(self):
        """Test ACF with trending data (should show strong correlation)"""
        x = np.cumsum(np.random.normal(0, 1, 100))  # Random walk (trending)
        
        acf_vals, lags, acf_conf = gs.acf(x, fracLag=0.1, ci=95)
        
        # Should show strong positive correlation at small lags
        assert acf_vals[0] == 1.0  # Perfect self-correlation
        assert acf_vals[1] > 0.8   # Strong correlation at lag 1
        
        # Confidence intervals should be provided
        assert acf_conf.shape[0] == len(acf_vals)
        assert acf_conf.shape[1] == 2  # Upper and lower bounds

class TestEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_empty_array(self):
        """Test functions with empty arrays"""
        empty_data = np.array([])
        
        # Most functions should handle empty arrays gracefully or raise informative errors
        with pytest.raises((ValueError, IndexError)):
            gs.expected(empty_data, 'Normal')
    
    def test_single_value(self):
        """Test functions with single-value arrays"""
        single_data = np.array([5.0])
        
        # Expected value should work
        result = gs.expected(single_data, 'Normal')
        assert abs(result - 5.0) < 1e-10
        
        # Dispersion should be zero
        disp_result = gs.disper(single_data, 'Normal')
        assert abs(disp_result) < 1e-10
    
    def test_all_nans(self):
        """Test functions with all NaN values"""
        nan_data = np.array([np.nan, np.nan, np.nan])
        
        # Should handle gracefully (may return NaN or raise error)
        try:
            result = gs.expected(nan_data, 'Normal')
            # If it returns a value, it should be NaN
            assert np.isnan(result)
        except (ValueError, IndexError):
            # Or it may raise an error, which is also acceptable
            pass
    
    def test_infinite_values(self):
        """Test functions with infinite values"""
        inf_data = np.array([1, 2, np.inf, 4, 5])
        
        # Functions should handle or reject infinite values appropriately
        try:
            result = gs.expected(inf_data, 'Robust')
            assert not np.isinf(result)  # Result should not be infinite
        except (ValueError, RuntimeWarning):
            # May raise error or warning, which is acceptable
            pass