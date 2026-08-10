# Unit Tests for Condor Financial Modeling

This directory contains comprehensive unit tests for the core financial modeling functionality of the Condor portfolio optimization system.

## Quick Start

```bash
# Install test dependencies
pip install -r tests/requirements.txt

# Run all tests
pytest tests/

# Run with coverage report
pytest --cov=analytics tests/

# Run specific test file
pytest tests/test_genFin.py -v
```

## Test Structure

- `test_genFin.py` - Core financial calculations (returns, Sharpe ratios, portfolio math)
- `test_genStats.py` - Statistical functions (robust vs normal methods, covariance)
- `test_portOpt.py` - Portfolio optimization (Sharpe maximization, minimum variance)
- `test_integration.py` - End-to-end workflow tests
- `conftest.py` - Pytest fixtures and configuration
- `requirements.txt` - Test dependencies

## Key Test Categories

### Priority 1: Mathematical Accuracy
- Return calculations with known values
- Portfolio performance mathematics
- Sharpe ratio calculations
- Weight constraint validation

### Priority 2: Optimization
- Sharpe ratio maximization convergence
- Minimum variance optimization
- Efficient frontier calculations
- Edge cases and extreme scenarios

### Priority 3: Data Quality
- NaN value handling
- Outlier robustness (robust vs normal statistics)
- Missing data scenarios
- Extreme market conditions

### Priority 4: Integration
- Complete optimization workflows
- Class-based vs function-based consistency
- Different timeframe calculations
- Annualization accuracy

## Running Specific Tests

```bash
# Test core return calculations
pytest tests/test_genFin.py::TestReturnCalculations -v

# Test portfolio optimization
pytest tests/test_portOpt.py::TestMaxSharpeRatio -v

# Test statistical robustness
pytest tests/test_genStats.py::TestExpectedValue::test_expected_with_outliers -v

# Test complete workflow
pytest tests/test_integration.py::TestFullOptimizationWorkflow -v
```

## Test Data

Tests use deterministic fixtures for reproducibility:
- `sample_price_data` - Correlated 3-asset price series
- `simple_portfolio_data` - 2-asset portfolio for basic tests  
- `three_asset_portfolio` - 3-asset portfolio for optimization
- `extreme_market_data` - Market crash scenarios
- `mock_price_loader` - Mock data loader for testing without external dependencies

## Coverage Expectations

Target coverage levels:
- `genFin.py`: >95% (critical mathematical functions)
- `genStats.py`: >90% (statistical calculations)
- `portOpt.py`: >90% (optimization algorithms)
- `CondorCoreObs.py`: >85% (class functionality)

## Debugging Failed Tests

1. **Mathematical precision errors**: Check decimal precision in assertions
2. **Optimization convergence**: May need looser tolerances for numerical methods
3. **Random data issues**: Ensure deterministic seeds are set
4. **Missing dependencies**: Install test requirements

## Adding New Tests

When adding functionality:
1. Add corresponding unit tests
2. Include edge cases and error conditions
3. Test both normal and robust statistical methods
4. Verify mathematical properties hold
5. Add integration tests for new workflows

## Continuous Integration

These tests should be run:
- Before any commit to main branch
- In automated CI/CD pipeline
- Before major refactoring
- When dependencies are updated

The test suite is designed to catch regressions in core financial modeling while supporting rapid application development.