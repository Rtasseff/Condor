"""
Pytest configuration and fixtures for Condor financial modeling tests
"""
import pytest
import numpy as np
import pandas as pd
import sys
import os

# Add analytics to path for testing
analytics_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'analytics')
sys.path.insert(0, analytics_dir)

@pytest.fixture
def sample_price_data():
    """Generate deterministic test price data for reproducible tests"""
    np.random.seed(42)  # For reproducible tests
    dates = pd.date_range('2020-01-01', periods=252, freq='D')
    
    # Create correlated price series
    returns_a = np.random.normal(0.001, 0.02, 252)
    returns_b = 0.7 * returns_a + 0.3 * np.random.normal(0.0008, 0.015, 252)
    returns_c = -0.3 * returns_a + 0.8 * np.random.normal(0.0012, 0.025, 252)
    
    prices_a = 100 * (1 + returns_a).cumprod()
    prices_b = 100 * (1 + returns_b).cumprod()
    prices_c = 100 * (1 + returns_c).cumprod()
    
    return {
        'dates': dates,
        'prices': np.column_stack([prices_a, prices_b, prices_c]),
        'symbols': ['TEST_A', 'TEST_B', 'TEST_C'],
        'returns_a': returns_a,
        'returns_b': returns_b,
        'returns_c': returns_c
    }

@pytest.fixture
def simple_portfolio_data():
    """Simple 2-asset portfolio data for basic tests"""
    return {
        'weights': np.array([0.6, 0.4]),
        'expected_returns': np.array([0.08, 0.12]),
        'cov_matrix': np.array([[0.04, 0.01], [0.01, 0.09]]),
        'symbols': ['ASSET_A', 'ASSET_B']
    }

@pytest.fixture
def three_asset_portfolio():
    """3-asset portfolio for optimization tests"""
    return {
        'expected_returns': np.array([0.08, 0.12, 0.15]),
        'cov_matrix': np.array([
            [0.04, 0.01, 0.02], 
            [0.01, 0.09, 0.03], 
            [0.02, 0.03, 0.16]
        ]),
        'symbols': ['CONSERVATIVE', 'MODERATE', 'AGGRESSIVE'],
        'equal_weights': np.array([1/3, 1/3, 1/3])
    }

@pytest.fixture 
def extreme_market_data():
    """Data representing extreme market conditions (crash scenario)"""
    return {
        'crash_returns': np.array([-0.5, -0.3, -0.4]),
        'crash_cov': np.array([
            [0.25, 0.15, 0.10],
            [0.15, 0.20, 0.12], 
            [0.10, 0.12, 0.30]
        ]),
        'symbols': ['STOCK_A', 'STOCK_B', 'STOCK_C']
    }

class MockPriceLoader:
    """Mock price loader for testing without external dependencies"""
    
    def __init__(self, sample_data):
        self.data = sample_data
        self.symbols = sample_data['symbols']
    
    def get_assets_df(self, syms=None):
        if syms is None:
            syms = self.symbols
        
        df = pd.DataFrame(
            self.data['prices'][:, [self.symbols.index(s) for s in syms]], 
            index=self.data['dates'],
            columns=syms
        )
        return df
    
    def get_assets_np(self, syms=None):
        df = self.get_assets_df(syms)
        return df.values, df.index.values, df.columns.values
    
    def set_target_asset_symbols(self, syms):
        self.symbols = syms

@pytest.fixture
def mock_price_loader(sample_price_data):
    """Mock price loader fixture"""
    return MockPriceLoader(sample_price_data)