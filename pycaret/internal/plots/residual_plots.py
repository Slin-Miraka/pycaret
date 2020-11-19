from typing import Any, Dict, Optional, Union, Sequence

import re
from scipy import stats
import plotly.graph_objects as go
import plotly.express as px
from plotly.basewidget import BaseFigureWidget
import statsmodels.api as sm
import pandas as pd
import numpy as np
import statsmodels.regression.linear_model as linear_model
from ipywidgets import widgets, Layout
from ipywidgets.embed import embed_snippet
from IPython.display import display

import pycaret.internal.plots.helper as helper
from pycaret.internal.validation import is_fitted
from pycaret.internal.Display import Display
from pycaret.internal.logging import get_logger


class CoefficientPlotWidget(BaseFigureWidget):
    def __init__(
            self,
            coefficients: Union[list, np.ndarray],
            columnnames: Union[list, np.ndarray] = None,
            **kwargs
    ):
        coefficients = np.array(coefficients)
        if columnnames is None:
            self._labels = [f'Feature {i}' for i in range(coefficients.shape[0])]
        else:
            self._labels = self._rename_labels(names=columnnames)
        print(self._labels)
        super(CoefficientPlotWidget, self).__init__(
            data=go.Scatter(
                x=coefficients,
                y=self._labels,
                mode='markers',
                marker_color='blue'
            ),
            layout=go.Layout(
                yaxis=dict(
                    tickmode='array',
                    tickvals=self._labels,
                    ticktext=self._labels
                ),
                xaxis_title="Coefficient values",
                yaxis_title="Coefficients",
                font=dict(
                    family="Courier New, monospace",
                    size=18,
                    color="#7f7f7f"
                )
            ),
            **kwargs
        )

    def _rename_labels(self, names: Union[list, np.ndarray]):
        word = re.compile("^([A-Za-z0-9_ ]+)( .*){0,1}$")
        labels = []
        for col in names:
            grp = word.match(col)
            if grp:
                labels.append(grp[1])
            else:
                # ToDo: check if is useful
                labels.append(col[:5])
        return labels

    def update_values(self, coefficients: Union[list, np.ndarray]):
        self.update({"data": go.Scatter(
            x=coefficients,
            y=self._labels,
            mode='markers',
            marker_color='blue'
        )}, overwrite=True)


class QQPlotWidget(BaseFigureWidget):

    def __init__(self, predicted: np.ndarray, expected: np.ndarray = None, featuresize: int = None,
                 split_origin: np.array = None, **kwargs):
        if expected is not None:
            std_res = helper.calculate_standardized_residual(
                predicted,
                expected=expected,
                featuresize=featuresize
            )
        else:
            std_res = predicted
        plot = self.qq_plot(std_res, split_origin)
        super(QQPlotWidget, self).__init__(plot, **kwargs)

    def _get_qq(self, standardized_residuals: np.ndarray) -> np.ndarray:
        qq = stats.probplot(standardized_residuals, dist='norm', sparams=(1))
        return np.array([qq[0][0][0], qq[0][0][-1]]), qq

    def qq_plot(self, standardized_residuals: np.ndarray, split_origin: np.array = None) -> go.Figure:

        sorted_split_origin = np.array(
            [x[1] for x in sorted(enumerate(split_origin), key=lambda x: standardized_residuals[x[0]])])
        colors = sorted_split_origin.copy()
        colors[sorted_split_origin == "train"] = "blue"
        colors[sorted_split_origin == "test"] = "green"

        x, qq = self._get_qq(standardized_residuals=standardized_residuals)
        fig = go.Figure()
        fig.add_scatter(x=qq[0][0], y=qq[0][1], mode='markers',
                        marker=dict(color=colors), customdata=sorted_split_origin, hovertemplate="%{x},%{y} (%{customdata})",
                        opacity=0.7)
        fig.add_scatter(x=x, y=qq[1][1] + qq[1][0] * x, mode='lines')
        fig.layout.update(
            autosize=True,
            showlegend=False,
            title='Normal QQ-Plot',
            xaxis_title='Theoretical Quantiles',
            yaxis_title='Standardized Residuals'
        )
        return fig

    def update_values(self, predicted: np.ndarray, expected: np.ndarray = None, featuresize: int = None):
        plot = self.qq_plot(
            standardized_residuals=helper.calculate_standardized_residual(predicted, expected, featuresize)
        )
        self.update({"data": plot.data}, overwrite=True)
        self.update_layout()


class ScaleLocationWidget(BaseFigureWidget):
    def __init__(self, fitted: np.ndarray, sqrt_abs_standardized_residuals: np.ndarray, split_origin: np.ndarray = None, **kwargs):
        plot = self._scale_location_plot(fitted, sqrt_abs_standardized_residuals, split_origin)
        super(ScaleLocationWidget, self).__init__(plot, **kwargs)

    def _scale_location_plot(self, fitted, sqrt_abs_standardized_residuals, split_origin):
        sqrt_abs_standardized_residuals = pd.Series(sqrt_abs_standardized_residuals)

        if split_origin is not None:
            dataframe = pd.DataFrame(
                {'Fitted Values': fitted, 'Split': split_origin,
                 '$\sqrt{|Standardized Residuals|}$': sqrt_abs_standardized_residuals})
            fig = px.scatter(dataframe, x="Fitted Values", y="$\sqrt{|Standardized Residuals|}$", trendline="lowess",
                             color="Split", color_discrete_sequence=['blue', 'green'],
                             title="Scale-Location Plot", opacity=0.3)

            fig.update_layout(showlegend=False)
        else:
            dataframe = pd.DataFrame(
                {'Fitted Values': fitted, '$\sqrt{|Standardized Residuals|}$': sqrt_abs_standardized_residuals})
            fig = px.scatter(dataframe, x="Fitted Values", y="$\sqrt{|Standardized Residuals|}$", trendline="lowess",
                             title="Scale-Location Plot", opacity=0.3)

        abs_sq_norm_resid = sqrt_abs_standardized_residuals.sort_values(ascending=False)
        abs_sq_norm_resid_top_3 = abs_sq_norm_resid[:3]
        for i in abs_sq_norm_resid_top_3.index:
            fig.add_annotation(
                x=fitted[i],
                y=sqrt_abs_standardized_residuals[i],
                text=str(i + 1))
        fig.update_annotations(dict(
            xref="x",
            yref="y",
            showarrow=True,
            arrowhead=7,
            ax=0,
            ay=-40
        ))
        return fig

    def update_values(self, fitted: np.ndarray, sqrt_abs_standardized_residuals: np.ndarray):
        plot = self._scale_location_plot(fitted, sqrt_abs_standardized_residuals)
        self.update({"data": plot.data}, overwrite=True)
        self.update_layout()


class CooksDistanceWidget(BaseFigureWidget):
    def __init__(
            self,
            model_leverage: np.ndarray,
            cooks_distances: np.ndarray,
            standardized_residuals: np.ndarray,
            n_model_params: int,
            **kwargs
    ):
        plot = self._cooks_distance_plot(model_leverage, cooks_distances, standardized_residuals, n_model_params)
        super(CooksDistanceWidget, self).__init__(plot, **kwargs)

    def _cooks_distance_plot(self, model_leverage, cooks_distances, standardized_residuals, n_model_params):
        cooks_distances = pd.Series(cooks_distances)
        dataframe = pd.DataFrame(
            {'Leverage': model_leverage, 'Standardized Residuals': standardized_residuals})
        fig = px.scatter(dataframe, x="Leverage", y="Standardized Residuals", trendline="lowess",
                         title="Residuals vs Leverage", opacity=0.3)
        maxmo = max(model_leverage) + 0.003
        fig.update_xaxes(range=[0, maxmo])
        fig.update_yaxes(range=[-3, 5])
        leverage_top_3 = cooks_distances.sort_values(ascending=False)[:3]
        for i in leverage_top_3.index:
            fig.add_annotation(
                x=model_leverage[i],
                y=standardized_residuals[i],
                text=str(i + 1))
        fig.update_annotations(dict(
            xref="x",
            yref="y",
            showarrow=True,
            arrowhead=7,
            ax=0,
            ay=-40
        ))

        def graph(formula, x_range, label=None):
            x = x_range
            y = formula(x)
            fig.add_trace(
                go.Scatter(x=x, y=y, name=label,
                           line=dict(color='firebrick', width=4, dash='dash'),
                           showlegend=True
                           )
            )

        p = n_model_params
        graph(lambda x: np.sqrt(np.abs((0.5 * p * (1 - x)) / x)),
              np.linspace(0.001, max(model_leverage), 50), 'Cook\'s distance')
        return fig

    def update_values(
            self,
            model_leverage: np.ndarray,
            cooks_distances: np.ndarray,
            standardized_residuals: np.ndarray,
            n_model_params: int
    ):
        plot = self._cooks_distance_plot(model_leverage, cooks_distances, standardized_residuals, n_model_params)
        self.update({"data": plot.data}, overwrite=True)
        self.update_layout()


class TukeyAnscombeWidget(BaseFigureWidget):
    def __init__(self, predictions: np.ndarray, residuals: np.ndarray,
                 split_origin: np.ndarray = None, **kwargs):
        plot = self._tukey_anscombe_plot(predictions, residuals, split_origin)
        super(TukeyAnscombeWidget, self).__init__(plot, **kwargs)

    def _tukey_anscombe_plot(self, predictions, residuals, split_origin):
        if split_origin is not None:
            dataframe = pd.DataFrame({
                'Prediction': predictions,
                'Residual': residuals,
                'Split': split_origin})

            fig = px.scatter(dataframe, x="Prediction", y="Residual", trendline="lowess",
                             color="Split",
                             color_discrete_sequence=['blue', 'green'],
                             title="Tukey-Anscombe Plot",
                             opacity=0.3)

            fig.update_layout(showlegend=False)
        else:
            dataframe = pd.DataFrame({'Fitted Values': predictions, 'Fitted Residuals': residuals})

            fig = px.scatter(dataframe, x="Fitted Values", y="Fitted Residuals", trendline="lowess",
                             title="Tukey-Anscombe Plot",
                             opacity=0.3)

        model_abs_resid = pd.Series(np.abs(residuals))
        abs_resid = model_abs_resid.sort_values(ascending=False)
        abs_resid_top_3 = abs_resid[:3]
        for i in abs_resid_top_3.index:
            fig.add_annotation(
                x=predictions[i],
                y=residuals[i],
                text=str(i + 1))
        fig.update_annotations(dict(
            xref="x",
            yref="y",
            showarrow=True,
            arrowhead=7,
            ax=0,
            ay=-40
        ))
        return fig

    def update_values(self, fitted: np.ndarray, residuals: np.ndarray,
                      predictions: np.ndarray = None, prediction_residuals: np.ndarray = None):
        plot = self._tukey_anscombe_plot(fitted, residuals, predictions, prediction_residuals)
        self.update({"data": plot.data}, overwrite=True)
        self.update_layout()


class InteractiveResidualsPlot:
    def __init__(self, display: Display, model, x: np.ndarray, y: np.ndarray, x_test: np.ndarray = None,
                 y_test: np.ndarray = None):
        self.figures: [BaseFigureWidget] = []
        self.display: Display = display
        self.plot = self.__create_resplots(model, x, y, x_test, y_test)

    def show(self):
        self.display.display(self.plot)

    def write_html(self, plot_filename):
        style = 'style="width: 50%; height: 50%; float:left;"'
        html = f'<div {style}>{self.figures[0].to_html()}</div><div {style}>{self.figures[1].to_html()}</div>' \
               f'<div {style}>{self.figures[2].to_html()}</div><div {style}>{self.figures[3].to_html()}</div>'

        with open(plot_filename, "w") as f:
            f.write(html)

    def __create_resplots(self, model, x: np.ndarray, y: np.ndarray,
                          x_test: np.ndarray = None, y_test: np.ndarray = None) -> widgets.VBox:
        logger = get_logger()

        if not is_fitted(model):
            model.fit(x, y)

        fitted = model.predict(x)
        fitted_residuals = fitted - y

        if x_test is not None and y_test is not None:
            pred = model.predict(x_test)
            prediction_residuals = pred - y_test

            predictions = np.concatenate((fitted, pred))
            residuals = np.concatenate((fitted_residuals, prediction_residuals))
            split_origin = np.concatenate(
                (np.repeat("train", fitted.shape[0]),
                 np.repeat("test", pred.shape[0])))

            x = np.concatenate((x, x_test))
            y = np.concatenate((y, y_test))

        else:
            predictions = fitted
            residuals = fitted_residuals
            split_origin = None

        logger.info("Calculated model residuals")
        self.display.move_progress()

        tukey_anscombe_widget = TukeyAnscombeWidget(predictions, residuals, split_origin=split_origin)
        logger.info("Calculated Tunkey-Anscombe Plot")
        self.figures.append(tukey_anscombe_widget)
        self.display.move_progress()

        qq_plot_widget = QQPlotWidget(predictions, y, split_origin=split_origin)
        logger.info("Calculated Normal QQ Plot")
        self.figures.append(qq_plot_widget)
        self.display.move_progress()

        standardized_residuals = \
            helper.calculate_standardized_residual(predictions, y, None)
        model_norm_residuals_abs_sqrt = np.sqrt(np.abs(standardized_residuals))
        scale_location_widget = ScaleLocationWidget(predictions, model_norm_residuals_abs_sqrt, split_origin)
        logger.info("Calculated Scale-Location Plot")
        self.figures.append(scale_location_widget)
        self.display.move_progress()

        leverage = helper.leverage_statistic(np.array(x))
        distance = helper.cooks_distance(standardized_residuals, leverage)
        n_model_params = len(model.get_params())
        cooks_distance_widget = CooksDistanceWidget(leverage, distance, standardized_residuals,
                                                    n_model_params)
        logger.info("Calculated Residual vs Leverage Plot inc. Cook's distance")
        self.figures.append(cooks_distance_widget)
        self.display.move_progress()

        items_layout = Layout(width='1000px')
        h0 = widgets.HBox(self.figures[:2], layout=items_layout)
        h1 = widgets.HBox(self.figures[2:], layout=items_layout)
        return widgets.VBox([h0, h1])
