# Unit Test Plan for Core Financial Modeling

## Overview

This document outlines the comprehensive unit test plan designed to protect the core financial modeling functionality of the Condor portfolio optimization system. These tests must be implemented before any major refactoring or application development to ensure mathematical accuracy and prevent regressions.

## Test Organization

### Directory Structure
```
tests/
├── test_genFin.py           # Core financial calculations
├── test_genStats.py         # Statistical functions
├── test_portOpt.py          # Portfolio optimization
├── test_CondorCoreObs.py    # Core classes (Asset, Portfolio, etc.)
├── test_integration.py      # End-to-end workflow tests
├── conftest.py              # Pytest fixtures and configuration
└── fixtures/
    ├── sample_data.py       # Test data generators
    └── mock_loaders.py      # Mock data loaders
```

### Running Tests
```bash
# Install test dependencies
pip install pytest numpy pandas scipy

# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_genFin.py

# Run with coverage
pytest --cov=analytics tests/

# Run specific test function
pytest tests/test_genFin.py::test_calc_return_all_metrics -v
```

## Test Categories

### 1. Core Mathematical Functions (`test_genFin.py`)

**File Location**: `tests/test_genFin.py`  
**Target Module**: `analytics/functions/genFin.py`

#### High Priority Tests

**`test_calc_return_all_metrics()`**
- **Purpose**: Validates all return calculation methods (Relative, Simple, Log, Delta)
- **Reasoning**: Return calculations are fundamental to all portfolio analysis. Errors here propagate through entire system
- **Test Data**: Known price pairs (100 → 110) with expected mathematical results
- **Call**: `pytest tests/test_genFin.py::test_calc_return_all_metrics -v`

**`test_returns_array_processing()`**
- **Purpose**: Tests return calculations on price arrays with different periods
- **Reasoning**: Ensures vectorized operations work correctly for time series data
- **Test Data**: Simple price array [100, 105, 110, 108] with known expected returns
- **Call**: `pytest tests/test_genFin.py::test_returns_array_processing -v`

**`test_asset_set_perform()`**
- **Purpose**: Validates portfolio performance calculations (return and risk)
- **Reasoning**: Core portfolio mathematics - any error affects all optimization results
- **Test Data**: 2-asset portfolio with known weights, returns, and covariance matrix
- **Expected**: Weighted return = 0.6×0.08 + 0.4×0.12 = 0.096
- **Call**: `pytest tests/test_genFin.py::test_asset_set_perform -v`

**`test_sharpe_ratio_calculation()`**
- **Purpose**: Verifies Sharpe ratio calculations for portfolio optimization
- **Reasoning**: Sharpe ratio is primary optimization target - must be mathematically correct
- **Test Data**: Balanced portfolio with risk-free rate
- **Call**: `pytest tests/test_genFin.py::test_sharpe_ratio_calculation -v`

#### Edge Case Tests

**`test_weight_validation()`**
- **Purpose**: Ensures weight constraints are enforced (must sum to 1.0)
- **Reasoning**: Prevents invalid portfolios that would produce meaningless results
- **Test Data**: Weights summing to 0.9 (should raise exception)
- **Call**: `pytest tests/test_genFin.py::test_weight_validation -v`

**`test_annualization()`**
- **Purpose**: Validates annualization factors for different time periods
- **Reasoning**: Critical for comparing returns across different timeframes
- **Test Data**: Monthly returns converted to annual (×12 for returns, ×√12 for risk)
- **Call**: `pytest tests/test_genFin.py::test_annualization -v`

### 2. Statistical Functions (`test_genStats.py`)

**File Location**: `tests/test_genStats.py`  
**Target Module**: `analytics/functions/genStats.py`

**`test_statistical_methods()`**
- **Purpose**: Compares robust vs normal statistical methods
- **Reasoning**: Ensures robust methods handle outliers correctly vs normal methods
- **Test Data**: Dataset [1,2,3,4,5,100] with clear outlier
- **Expected**: Median (3.5) < Mean (influenced by outlier)
- **Call**: `pytest tests/test_genStats.py::test_statistical_methods -v`

**`test_covariance_matrix()`**
- **Purpose**: Validates covariance matrix calculations (normal and robust)
- **Reasoning**: Covariance matrices are essential for portfolio risk calculations
- **Test Data**: Perfectly correlated data series
- **Expected**: Symmetric matrix with correct correlations
- **Call**: `pytest tests/test_genStats.py::test_covariance_matrix -v`

### 3. Portfolio Optimization (`test_portOpt.py`)

**File Location**: `tests/test_portOpt.py`  
**Target Module**: `analytics/functions/portOpt.py`

**`test_max_sharpe_optimization()`**
- **Purpose**: Tests Sharpe ratio maximization optimization
- **Reasoning**: Primary optimization method - must converge to valid solutions
- **Test Data**: 3-asset universe with different risk/return profiles
- **Expected**: Successful convergence, weights sum to 1, no short positions
- **Call**: `pytest tests/test_portOpt.py::test_max_sharpe_optimization -v`

**`test_min_variance_optimization()`**
- **Purpose**: Tests minimum variance portfolio optimization
- **Reasoning**: Alternative optimization target - validates solver robustness
- **Test Data**: 2-asset portfolio for simple verification
- **Expected**: Successful convergence with valid weight constraints
- **Call**: `pytest tests/test_portOpt.py::test_min_variance_optimization -v`

**`test_efficient_frontier()`**
- **Purpose**: Tests efficient frontier calculation across return targets
- **Reasoning**: Ensures optimization works across range of target returns
- **Test Data**: Linear range of target returns from min to max
- **Expected**: Valid weights for each target return
- **Call**: `pytest tests/test_portOpt.py::test_efficient_frontier -v`

### 4. Core Classes (`test_CondorCoreObs.py`)

**File Location**: `tests/test_CondorCoreObs.py`  
**Target Module**: `analytics/classes/CondorCoreObs.py`

**`test_portfolio_creation()`**
- **Purpose**: Tests Portfolio class initialization and validation
- **Reasoning**: Ensures portfolio objects are created correctly with proper constraints
- **Test Data**: Valid and invalid weight arrays
- **Expected**: Successful creation with valid weights, exceptions with invalid weights
- **Call**: `pytest tests/test_CondorCoreObs.py::test_portfolio_creation -v`

**`test_returns_calculation()`**
- **Purpose**: Tests Returns class calculations and time period handling
- **Reasoning**: Validates return calculations maintain correct time alignment
- **Test Data**: Generated price time series with known characteristics
- **Expected**: Correct return series length and properties
- **Call**: `pytest tests/test_CondorCoreObs.py::test_returns_calculation -v`

### 5. Integration Tests (`test_integration.py`)

**File Location**: `tests/test_integration.py`  
**Target Modules**: Multiple modules working together

**`test_full_optimization_workflow()`**
- **Purpose**: Tests complete end-to-end optimization workflow
- **Reasoning**: Ensures all components work together correctly
- **Test Data**: Complete price dataset through full optimization
- **Expected**: Reasonable optimized portfolio with valid properties
- **Call**: `pytest tests/test_integration.py::test_full_optimization_workflow -v`

### 6. Data Validation Tests

**`test_missing_data_handling()`**
- **Purpose**: Tests NaN and missing data handling
- **Reasoning**: Real financial data often has gaps - system must handle gracefully
- **Test Data**: Arrays with NaN values
- **Expected**: Valid results excluding NaN values
- **Call**: `pytest tests/test_integration.py::test_missing_data_handling -v`

**`test_extreme_values()`**
- **Purpose**: Tests behavior with extreme market conditions
- **Reasoning**: System must handle market crashes and extreme scenarios
- **Test Data**: Large negative returns simulating market crash
- **Expected**: Mathematically correct results even with extreme inputs
- **Call**: `pytest tests/test_integration.py::test_extreme_values -v`

## Test Data Fixtures

### `sample_price_data` Fixture
**Location**: `tests/conftest.py`
**Purpose**: Provides reproducible test price data for multiple tests
**Usage**: 
```python
def test_example(sample_price_data):
    dates = sample_price_data['dates']
    prices = sample_price_data['prices']
    symbols = sample_price_data['symbols']
```

## Critical Test Priorities

### Priority 1: Mathematical Accuracy
- Return calculations (`test_calc_return_all_metrics`)
- Portfolio mathematics (`test_asset_set_perform`)
- Sharpe ratio calculations (`test_sharpe_ratio_calculation`)

**Reasoning**: Errors in core mathematics invalidate all analysis

### Priority 2: Constraint Validation
- Weight validation (`test_weight_validation`)
- Portfolio creation (`test_portfolio_creation`)

**Reasoning**: Invalid portfolios produce meaningless results

### Priority 3: Optimization Convergence
- Sharpe optimization (`test_max_sharpe_optimization`)
- Minimum variance (`test_min_variance_optimization`)
- Efficient frontier (`test_efficient_frontier`)

**Reasoning**: Optimization failures break primary application functionality

### Priority 4: Data Integrity
- Statistical methods (`test_statistical_methods`)
- Missing data handling (`test_missing_data_handling`)
- Extreme values (`test_extreme_values`)

**Reasoning**: Real-world data has quality issues that must be handled

### Priority 5: Integration
- Full workflow (`test_full_optimization_workflow`)

**Reasoning**: Ensures components work together correctly

## Implementation Notes

### Test Data Strategy
- Use deterministic random seeds for reproducible tests
- Create simple, mathematically verifiable test cases
- Include edge cases that stress the system

### Tolerance Levels
- Use `np.testing.assert_array_almost_equal` with appropriate decimal places
- Financial calculations: typically 6 decimal places
- Optimization results: may need looser tolerance (1e-4) due to numerical methods

### Mock Objects
- Create mock price loaders for testing without external data dependencies
- Mock data should have known statistical properties for verification

### Continuous Integration
These tests should be run:
- Before any commit to main branch
- As part of automated CI/CD pipeline
- Before any major refactoring

## Expected Outcomes

After implementing these tests:
1. **Confidence**: Mathematical accuracy is verified
2. **Safety**: Refactoring won't break core functionality  
3. **Documentation**: Tests serve as specification for expected behavior
4. **Regression Prevention**: Changes that break functionality are caught immediately
5. **Code Quality**: Forces consideration of edge cases and error handling

## Next Steps

1. Implement test directory structure
2. Create `conftest.py` with shared fixtures
3. Implement Priority 1 tests first
4. Add tests to CI/CD pipeline
5. Achieve >90% code coverage on core modules
6. Document any mathematical assumptions discovered during testing

## Maintenance

- Review and update tests when mathematical methods change
- Add new tests for any new financial calculations
- Regularly run tests against new market data to verify continued accuracy
- Update test data fixtures annually to include recent market conditions