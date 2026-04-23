import pandas as pd
from statsmodels.tsa.arima.model import ARIMA

def train_arima_model(time_series):

    # Use month-start frequency to match series built from period->timestamp month starts.
    time_series = time_series.asfreq('MS').fillna(0)

    model = ARIMA(time_series, order=(1,1,1))
    model_fit = model.fit()

    forecast = model_fit.forecast(steps=3)

    return model_fit, forecast

