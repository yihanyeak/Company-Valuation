# Imports
import re
from ast import Name
import warnings
import yfinance as yf
from edgar import *
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from fredapi import Fred
from datetime import datetime
import operator

fred = Fred(api_key='9722564d0a57789efd01a7a397cfad6b')

# Helper Functions
def clean_financial_value(val):
    # 1. If input is a DataFrame, apply recursively to the whole frame
    if isinstance(val, pd.DataFrame):
        return val.map(
            clean_financial_value
        )  # Use .applymap(clean_financial_value) if pandas < 2.1.0

    # 2. If input is a Series, apply to each element
    elif isinstance(val, pd.Series):
        return val.map(clean_financial_value)

    # 3. Handle missing values safely
    if pd.isna(val) or val in (0, "0", "0.0", "0.0%", "nan%"):
        return "N/A"

    # 4. Try converting to float; if it's text (like "Good" or ">0.08"), leave it alone
    try:
        val = float(val)
    except (ValueError, TypeError):
        return val

    # 5. Core formatting logic
    abs_val = abs(val)
    if abs_val >= 1e9:
        return f"{val / 1e9:.3f}B"
    elif abs_val >= 1e6:
        return f"{val / 1e6:.3f}M"
    else:
        return f"{val:.3f}"

def clean_statement_value(df):
    # 1. Drop Columns safely
    cols_to_drop = ['depth', 'is_abstract', 'is_total', 'section', 'confidence']
    existing_cols_to_drop = [c for c in cols_to_drop if c in df.columns]
    if existing_cols_to_drop:
        df = df.drop(columns=existing_cols_to_drop)

    # 2. Rename Column name
    if 'label' in df.columns:
        df = df.rename(columns={'label': 'name'})

    df.columns = [
        col.replace('FY ', '').strip() if 'FY' in str(col) else col
        for col in df.columns
    ]
    
    # 3. Clean data cells (strip text, drop commas, coerce to numeric)
    for col in df.columns:
        if col == 'name' or col == 'concept':
            continue
        cleaned_series = (
            df[col].astype(str)
            .str.strip()
            .str.replace(',', '', regex=False)
        )
        df[col] = pd.to_numeric(cleaned_series, errors='coerce')

    # 4. Rename Concept 
    concept_map = {
        'RevenueFromContractWithCustomerExcludingAssessedTax': 'Revenues',
        'GrossProfit_Calculated': 'GrossProfit',
        'CostOfGoodsAndServicesSold': 'CostOfRevenue',
        # 'OtherCostAndExpenseOperating': 'CostOfRevenue'
        # 'InterestIncomeExpenseNet': 'InterestExpense',
        # 'PaymentsToAcquireBusinessesNetOfCashAcquired' : 'PaymentsToAcquirePropertyPlantAndEquipment'
    }

    if 'concept' in df.columns:
        df['concept'] = df['concept'].replace(concept_map)
        df = df.set_index('concept')

    elif df.index.name == 'concept':
        df.index = df.index.to_series().replace(concept_map)

    # 5. Create new concepts 
    concept_calc = {
        'GrossProfit': {'name': 'Gross Profit', 'components': ['Revenues', 'CostOfRevenue'], 'operator': operator.sub},
        'OperatingIncomeLoss': {'name': 'Operating Income Loss', 'components': ['Revenues', 'OperatingExpenses'], 'operator': operator.sub}
    }

    for target, rules in concept_calc.items():
        components = rules['components']
        operation = rules['operator']

        if target not in df.index and all(x in df.index for x in components):

            values = [
                pd.to_numeric(df.loc[x], errors='coerce')
                for x in components
            ]

            result = values[0]

            for value in values[1:]:
                result = operation(result, value)

            df.loc[target] = result
            df.loc[target, 'name'] = rules['name']

    # 6. Safer row filtering (Only drop if all numeric value columns are completely NaN/0)
    numeric_cols = [col for col in df.columns if str(col).isdigit() or col in ['TTM', 'latest']]
    if numeric_cols:
        df = df.loc[df[numeric_cols].fillna(0).ne(0).any(axis=1)]
    
    return df

# Fetch Raw Date
def fetch_estimates(ticker):
    stock = yf.Ticker(ticker)

    forecast = {
        "revenue_estimate": stock.get_revenue_estimate(), # revenue
        "earnings_estimate": stock.get_earnings_estimate(), # eps
        # "growth_estimate": stock.get_growth_estimates(),
        # "eps_revisions": stock.get_eps_revisions(),
        # "eps_trend": stock.get_eps_trend()
    }

    return forecast

def fetch_financial_statement(ticker, stock_price):
    # 1. Fetch raw data (Edgar API)
    set_identity("YeakYiHan yihanyeak8@gmail.com")
    company = Company(ticker)

    methods = {
        'income_statement': company.income_statement,
        'balance_sheet': company.balance_sheet,
        'cash_flow': company.cash_flow_statement
    }

    # A. Yearly Statemetns
    yearly_statement = {
        'income_statement': company.income_statement(periods=99).to_dataframe(),
        'balance_sheet': company.balance_sheet(periods=99).to_dataframe(),
        'cash_flow': company.cash_flow_statement(periods=99).to_dataframe()
    }

    # B. Quarterly Statemetns
    quarterly_statement = {
        'income_statement': company.income_statement(periods=8, annual=False).to_dataframe(),
        'balance_sheet': company.balance_sheet(periods=8, annual=False).to_dataframe(),
        'cash_flow': company.cash_flow_statement(periods=8, annual=False).to_dataframe()
    }

    yearly_statement = {k: clean_statement_value(m(periods=99).to_dataframe()) for k, m in methods.items()}
    quarterly_statement = {k: clean_statement_value(m(periods=8, annual=False).to_dataframe()) for k, m in methods.items()}

    # 2. Format Data
    share_concepts = ['WeightedAverageNumberOfSharesOutstandingBasic', 'WeightedAverageNumberOfDilutedSharesOutstanding']

    # A. Custom Columns (TTMs or latest)
    financial_statement = {}
    for statement, df in yearly_statement.items():
        df = df.copy()
        df_quarter = quarterly_statement[statement].copy()

        q_col = [col for col in df_quarter.columns if str(col).startswith('Q')][::-1]
        df_quarter = df_quarter[['name'] + q_col]

        def sum_or_last(cols):
            # Share concepts take the last quarter; everything else is summed
            return np.where(df_quarter.index.isin(share_concepts), df_quarter[cols].iloc[:, -1], df_quarter[cols].sum(axis=1))

        # For Balance Sheet:
        if statement == 'balance_sheet':
            cus_col = ['latest']
            df_quarter['latest'] = df_quarter[q_col[-1]]
        # For Income Statement & Cash Flow:
        else:
            cus_col = ['TTM_prior', 'TTM_current']
            df_quarter['TTM_prior'] = sum_or_last(q_col[:4])
            df_quarter['TTM_current'] = sum_or_last(q_col[-4:])

        df = df.join(df_quarter.drop(columns=q_col + ['name']), how='left').fillna(0)

        # Fallback Logic (for missing values in custom column after the left join)
        fy_col = [col for col in df.columns if str(col).isdigit()]
        target_col, newest_fy_col = cus_col[0], fy_col[0]
        if target_col in df.columns and newest_fy_col in df.columns:
            df.loc[df[target_col] == 0, target_col] = df.loc[df[target_col] == 0, newest_fy_col]

        financial_statement[statement] = df[['name'] + fy_col[::-1] + cus_col]

    # B. Custom Rows (StockPrice & StockSplit)
    stock_price = stock_price.set_index(pd.to_datetime(stock_price['date']))
    yearly_stock_price = stock_price['close'].resample('YE').last()
    
    latest_fy = max([int(c) for c in financial_statement['income_statement'].columns if str(c).isdigit()])
    latest_stock_year = yearly_stock_price.index.max().year
    fy_adjusted = latest_fy - latest_stock_year # stock price yearly adjusted to company finanacial year (range: -1 to +1)

    yearly_stock_price.index = yearly_stock_price.index.year + fy_adjusted

    split_event = stock_price.loc[stock_price['stock splits'] != 0, 'stock splits']
    split_event.index = split_event.index.year
    split_event = split_event.groupby(level=0).prod() # For financial years with multiple stock splits

    add_df_T = (
        pd.concat([yearly_stock_price, split_event], axis=1)
        .assign(**{
            'stock splits': lambda x: (
                x['stock splits']
                .fillna(1)
                .sort_index(ascending=False)
                .cumprod()
                .sort_index(ascending=True)
            )
        })
        .rename(columns={'close': 'StockPrice', 'stock splits': 'StockSplit'})
        .T
        .rename_axis('concept')  # Set index directly to 'concept' so it matches income_df!
    )

    add_df_T.columns = add_df_T.columns.map(str)
    add_df_T['name'] = add_df_T.index.map({'StockPrice': 'Stock Price', 'StockSplit': 'Stock Split'})

    # 1. Add Stock Price and Stock Split rows
    valid_close = stock_price["close"].dropna().sort_index()
    latest_date = valid_close.index[-1]
    prior_year_date = latest_date - pd.DateOffset(years=1)
    ttm_price = {'TTM_current': valid_close.iloc[-1], 'TTM_prior': valid_close.asof(prior_year_date)}
    
    for ttm_col, price in ttm_price.items():
        add_df_T.loc['StockPrice', ttm_col] = price
        add_df_T.loc['StockSplit', ttm_col] = 1.0

    # Align columns to match the already-processed income_statement
    income_df = financial_statement['income_statement']
    add_df_T = add_df_T.reindex(columns=income_df.columns).fillna(0)
    add_df_T = clean_statement_value(add_df_T.reset_index())

    combined_df = pd.concat([income_df, add_df_T], axis=0)

    # Fix for share count scaling inconsistency
    target_cols = [col for col in combined_df.columns if str(col).isdigit() or str(col).startswith('TTM')]
    for concept in share_concepts:
        if concept in combined_df.index:
            combined_df.loc[concept, target_cols] = (
                combined_df.loc[concept, target_cols]
                .mask(
                    combined_df.loc[concept, target_cols].between(1, 1_000_000),
                    combined_df.loc[concept, target_cols] * 1000
                )
            )

    financial_statement['income_statement'] = combined_df
    return financial_statement

# 1. Search Bar
def search_stocks(query: str):
    if not query or len(query) < 1:
        return []

    results = yf.Search(query, max_results=10)

    return [
        f"{stock['symbol']} - {stock.get('shortname', stock.get('longname', ''))}"
        for stock in results.quotes
        if stock.get("quoteType") == "EQUITY"
    ]

# 2. Price Chart
def fetch_price_action(ticker):
    stock = yf.Ticker(ticker)

    stock_price = stock.history(period="max", interval="1d").reset_index()
    stock_price.columns = stock_price.columns.str.lower()

    return stock_price

def plot_price_chart(df, timeframe="1Y"):
    # 1. Prepare data
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'], utc=True).dt.tz_convert(None)
    df = df.sort_values('date').dropna(subset=['open', 'high', 'low', 'close'])

    max_date = df['date'].max()
    min_date = df['date'].min()

    # 2. Date cutoffs
    dates = {
        "MAX": min_date,
        "5Y":  max_date - pd.DateOffset(years=5),
        "2Y":  max_date - pd.DateOffset(years=2),
        "1Y":  max_date - pd.DateOffset(years=1),
        "6M":  max_date - pd.DateOffset(months=6),
        "3M":  max_date - pd.DateOffset(months=3)
        }

    if timeframe not in dates:
        timeframe = "1Y"

    # 3. Resample
    data = df[df['date'] >= dates[timeframe]].copy()

    # 4. Create chart
    fig = go.Figure(
        go.Candlestick(
            x=data['date'],
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            increasing_line_width=1.5,
            decreasing_line_width=1.5,
        )
    )

    # 5. Layout
    low, high = data['low'].min(), data['high'].max()
    padding = max((high - low) * 0.05, abs(high) * 0.001)

    fig.update_layout(
        dragmode='pan',
        hovermode='x unified',
        xaxis=dict(
            range=[dates[timeframe], max_date],
            rangeslider=dict(visible=False),
            fixedrange=False,
        ),
        yaxis=dict(
            range=[low - padding, high + padding],
            fixedrange=True,
            autorange=False,
        ),
        margin=dict(l=10, r=10, t=30, b=10),
    )

    return fig

# 3. Company Fundamentals
def fetch_macro_data(n_years):
    def process_data(series_id, scale=1.0):
        series = fred.get_series(series_id)
        return series.resample('YE').mean().values[-n_years:][::-1] / scale

    # Now adding new indicators takes just one clean line each
    macro_data = {
        'risk_free_yearly': process_data('DFF',  scale=100.0),
        'consumer_price_index': process_data('CPIAUCSL', scale=1.0)
    }

    return macro_data

def extract_guideline_component(guideline, metric_dict):
    operator = guideline[0] if guideline[0] in '<>' else ''
    body = guideline[len(operator):].strip()

    match = re.match(r'(\d+(?:\.\d+)?)\s*(%|x)?\s*(.*)', body)

    if not match:
        raise ValueError(f"Invalid guideline: {guideline}")

    number, symbol, metric = match.groups()
    value = float(number)

    if symbol == '%':
        value /= 100

    if metric.strip():
        value *= metric_dict[metric.strip()]

    return operator, value, symbol

def fundamental_rating(name, metric, metric_dict, forecast, guideline, relevance, type, rating_sensitivity):
    # Clean Data
    original_series = metric.replace([np.inf, -np.inf], np.nan)
    annual = original_series.drop(index=['TTM_prior', 'TTM_current'], errors='ignore')

    # Handle Guidline Components (Eg: <8% => operator = '<', display_value = '8', value = '0.08', symbol = '%')
    operator, value, symbol = extract_guideline_component(guideline, metric_dict)

    # 1. Current Value
    current_value = original_series.iloc[-1]

    # Annual Growth
    if type == 'ratio':
        growth_series = annual.diff().replace([np.inf, -np.inf], np.nan)
        growth_series_percentage = annual.pct_change()
    else:
        growth_series = annual.pct_change().replace([np.inf, -np.inf], np.nan)
        growth_series_percentage = growth_series.copy()

    # 2. YoY Growth
    yoy_growth = growth_series.iloc[-1]

    # 3. Blended Value & 4. Growth
    series_loop = [original_series, growth_series]

    # Weightage
    result = []
    for s in series_loop:
        weight = np.arange(1, len(s) + 1) ** (relevance / 10)
        temp_df = pd.DataFrame({'val': s, 'wt': weight}).dropna(subset=['val'])

        if not temp_df.empty:
            weighted_avg = np.average(temp_df['val'], weights=temp_df['wt'])
        else:
            weighted_avg = np.nan

        result.append(weighted_avg)

    blended_value, blended_growth = result
    # print(original_series)
    # print(blended_value)

    # 5. Rating
    # Set Upper and Lower Bounds
    if abs(value) == 0:
        magnitude_factor = 0.01
    else:
        # Automatically scales down sensitivity for small numbers (ratios/multiples) 
        magnitude_factor = min(1.0, abs(value) / 10.0)

    margin = abs(value) * rating_sensitivity * magnitude_factor
    upper_bound = value + margin
    lower_bound = value - margin

    # Set Value to Check
    if type == 'growth':
        val_to_check = blended_growth
    elif type in ['ratio', 'nominal']:
        val_to_check = blended_value

    # Rate
    if operator == ">":
        # print(val_to_check, '>', upper_bound, value, lower_bound)
        if val_to_check > upper_bound:
            rating = "Good"
        elif val_to_check < lower_bound:
            rating = "Concern"
        else:
            rating = "Watch"

    elif operator == "<":
        # print(val_to_check, '<', lower_bound, value, upper_bound)
        if val_to_check < lower_bound:
            rating = "Good"
        elif val_to_check > upper_bound:
            rating = "Concern"
        else:
            rating = "Watch"

    row = {
        'Name': name,
        'Current Year': f"{current_value * 100:.1f}%" if (type == 'ratio' and symbol == '%') else current_value,
        'YoY Growth': f"{yoy_growth * 100:.1f}%" if symbol in ['%', 'x'] else yoy_growth,
        'Blended Growth': None if symbol == None else (f"{blended_growth * 100:.1f}%" if symbol in ['%', 'x'] else blended_growth),
        'Blended Value': None if symbol is None or (type == 'ratio' and symbol == '%') else f"{blended_value * 100:.1f}%" if (type == 'ratio' and symbol == 'x') else blended_value,
        'Type': type,
        'Symbol': symbol,
        'Operator': f"{operator}",
        'Guideline': f"{value * 100:.1f}%" if type in ['growth', 'ratio'] and symbol == '%' else value,
        'Rating': rating
    }

    # 5. Forcast Blended Growth
    if forecast is not False and forecast is not None:
        if type == 'growth' and symbol == '%':
            combined_metric = pd.concat([metric.iloc[:-1], pd.Series(forecast)])
            combined_series = combined_metric.pct_change().dropna()
        else:
            combined_metric = pd.concat([growth_series_percentage.iloc[:-1], pd.Series(forecast)])
            combined_series = combined_metric.diff().dropna()

        # Forecast Weigtage
        forecast_weight = np.arange(1, len(combined_series) + 1) ** (5 / relevance)
        forecast_blended_growth = np.average(combined_series, weights=forecast_weight)
        forecast_evaluation = eval(f"{forecast_blended_growth} {operator} {value}")

        row['Forecast Blended Growth'] = f"{forecast_blended_growth * 100:.1f}%"

    return row

def cal_fundamentals(ticker, rating_sensitivity, user_input_value, user_input_relevance):
    stock_price = fetch_price_action(ticker)
    financial_statement = fetch_financial_statement(ticker, stock_price)
    forecast = fetch_estimates(ticker)

    # print(financial_statement['balance_sheet'])

    inc, bs, cf = [
        clean_statement_value(financial_statement[k].drop(columns=['name']))
        for k in ['income_statement', 'balance_sheet', 'cash_flow']
    ]

    # Special case for ROIC (exclude the extra TTM_prior column)
    inc_roic = inc.drop(columns=['name', 'TTM_prior'], errors='ignore')

    latest_col_inc, latest_col_bs, latest_col_cf = inc.columns[-1], bs.columns[-1], cf.columns[-1]

    metric_dict = {
        'Total Debt': (bs[latest_col_bs].get('DebtCurrent', 0) or 0) + (bs[latest_col_bs].get('LongTermDebtNoncurrent', 0) or 0),
        'FCF': cf.loc['NetCashProvidedByUsedInOperatingActivities', latest_col_cf],
        'Net Income': inc.loc['NetIncomeLoss', latest_col_inc],
        'Revenue': inc.loc['Revenues', latest_col_inc]
    }

    # Shared Calculation Metrics
    total_debt = (bs.reindex(['DebtCurrent']).iloc[0].fillna(0) + bs.reindex(['LongTermDebtNoncurrent']).iloc[0].fillna(0))

    # (name, metric, forecast, type) -- user_input_value / user_input_relevance are matched by position
    metrics_to_evaluate = [
        ('Revenue', inc.loc['Revenues'], None, 'growth'),
        ('Gross Margin', inc.loc['GrossProfit'] / inc.loc['Revenues'], None, 'ratio'),
        ('Interest Coverage', inc.loc['OperatingIncomeLoss'] / inc.loc['InterestExpense'], None, 'ratio'),
        ('Net Income', inc.loc['NetIncomeLoss'], None, 'growth'),
        ('Shares Outstanding', inc.loc['WeightedAverageNumberOfDilutedSharesOutstanding'].astype(float) * inc.loc['StockSplit'].astype(float), None, 'growth'),
        ('Cash & Short Term Investments', bs.loc['CashAndCashEquivalentsAtCarryingValue'], None, 'nominal'),
        ('Total Debt', total_debt, None, 'nominal'),
        ('Retained Earnings', bs.loc['RetainedEarningsAccumulatedDeficit'], None, 'nominal'),
        ('Stock Based Compensation', cf.loc['ShareBasedCompensation'], None, 'nominal'),
        ('Free Cash Flow', cf.loc['NetCashProvidedByUsedInOperatingActivities'] - cf.loc['PaymentsToAcquirePropertyPlantAndEquipment'], None, 'growth'),
        ('Return on Invested Capital', (inc_roic.loc['OperatingIncomeLoss'] * (1 - (inc_roic.loc['IncomeTaxExpenseBenefit'] / (inc_roic.loc['NetIncomeLoss'] + inc_roic.loc['IncomeTaxExpenseBenefit']))).values / (total_debt + bs.loc['StockholdersEquity'] - bs.loc['CashAndCashEquivalentsAtCarryingValue']).values), None, 'ratio'),
        ('PE ratio', (inc.loc['StockPrice'].values * inc.loc['StockSplit'].values) / inc.loc['EarningsPerShareDiluted'], None, 'ratio')
    ]

    final_df = pd.DataFrame([
        fundamental_rating(name, metric, metric_dict, forecast, user_input_value[i], user_input_relevance[i], type, rating_sensitivity)
        for i, (name, metric, forecast, type) in enumerate(metrics_to_evaluate)
    ])

    return clean_financial_value(final_df)
