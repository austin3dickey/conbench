import abc
import copy
import json
import logging
from typing import List, Optional, Tuple

import bokeh
import flask as f
from werkzeug.exceptions import HTTPException

from ..api.compare import CompareRunsAPI
from ..app import rule
from ..app._endpoint import AppEndpoint, authorize_or_terminate
from ..app._plots import TimeSeriesPlotMixin, simple_bar_plot
from ..app._util import error_page
from ..app.results import BenchmarkResultMixin, RunMixin
from ..app.types import HighlightInHistPlot
from ..config import Config
from ..entities.benchmark_result import BenchmarkResult

log = logging.getLogger(__name__)


def all_keys(dict1, dict2, attr):
    if dict1 is None:
        dict1 = {}
    if dict2 is None:
        dict2 = {}
    return sorted(
        set(list(dict1.get(attr, {}).keys()) + list(dict2.get(attr, {}).keys()))
    )


class Compare(AppEndpoint, BenchmarkResultMixin, RunMixin, TimeSeriesPlotMixin):
    type: str
    html: str
    title: str

    @abc.abstractmethod
    def get_comparisons(
        self, baseline_id: str, contender_id: str
    ) -> Tuple[List[dict], Optional[str]]:
        """Get comparisons between two entities. If the second tuple element is returned
        it's an error message.
        """

    def page(self, comparisons, baseline_id, contender_id):
        unknown = "unknown...unknown"
        compare_runs_url = f.url_for("app.compare-runs", compare_ids=unknown)
        baseline, contender, plot, plot_history = None, None, None, None
        baseline_run, contender_run = None, None
        biggest_changes_names, outlier_urls = None, None
        benchmark_result_history_plot_info = None
        contender_hardware_checksum = "n/a"
        baseline_hardware_checksum = "n/a"

        if comparisons and self.type == "run":
            baseline_run_id, contender_run_id = baseline_id, contender_id

        elif comparisons and self.type == "benchmark-result":
            baseline = self.get_display_benchmark(baseline_id)
            # TODO: fetch directly from db, no indirection through API.
            contender = self.get_display_benchmark(contender_id)
            # I think this is a bar chart showing two bars. One for each
            # benchmark result's mean value. Don't need a plot for that.
            # plot = self._get_plot(baseline, contender)
            baseline_run_id = baseline["run_id"]
            contender_run_id = contender["run_id"]
            compare = f"{baseline_run_id}...{contender_run_id}"
            compare_runs_url = f.url_for("app.compare-runs", compare_ids=compare)

        if comparisons:
            baseline_run = self.get_display_run(baseline_run_id)
            contender_run = self.get_display_run(contender_run_id)

        if comparisons and self.type == "benchmark-result":
            # `contender` is a dictionary representing the benchmark result.
            # Also inject the 'proper' benchmark result object  into
            # get_history_plot(). This is a mad way to deal with madness.
            # We (really!) need to remove this API layer indirection:
            # https://github.com/conbench/conbench/issues/968
            contender_benchmark_result = BenchmarkResult.one(id=contender["id"])
            baseline_benchmark_result = BenchmarkResult.one(id=baseline["id"])
            contender_hardware_checksum = contender_benchmark_result.hardware.hash
            baseline_hardware_checksum = baseline_benchmark_result.hardware.hash

            benchmark_result_history_plot_info = self.get_history_plot(
                contender_benchmark_result,
                contender_run,
                highlight_other_result=HighlightInHistPlot(
                    bmrid=baseline_id, highlight_name="baseline"
                ),
            )
            # log.info("compare view: generated history plot", plot_history)

        # It is wild that we use this call for rendering either of two rather
        # different templates.
        return self.render_template(
            self.html,
            application=Config.APPLICATION_NAME,
            title=self.title,
            type=self.type,
            # This is probably a plot! But what kind of plot?
            plot=plot,
            plot_history=plot_history,
            benchmark_result_history_plot_info=benchmark_result_history_plot_info,
            resources=bokeh.resources.CDN.render(),
            comparisons=comparisons,
            baseline_id=baseline_id,
            contender_id=contender_id,
            baseline=baseline,
            contender=contender,
            baseline_run=baseline_run,
            contender_run=contender_run,
            compare_runs_url=compare_runs_url,
            outlier_names=biggest_changes_names,
            outlier_urls=outlier_urls,
            search_value=f.request.args.get("search"),
            tags_fields=all_keys(baseline, contender, "tags"),
            context_fields=all_keys(baseline, contender, "context"),
            info_fields=all_keys(baseline, contender, "info"),
            hardware_fields=all_keys(baseline_run, contender_run, "hardware"),
            contender_hardware_checksum=contender_hardware_checksum,
            baseline_hardware_checksum=baseline_hardware_checksum,
        )

    def _get_plot(self, baseline, contender):
        baseline_copy = copy.deepcopy(baseline)
        contender_copy = copy.deepcopy(contender)
        baseline_copy["tags"] = {
            "compare": "baseline",
            "name": baseline["display_case_perm"],
        }
        contender_copy["tags"] = {
            "compare": "contender",
            "name": contender["display_case_perm"],
        }
        plot = json.dumps(
            bokeh.embed.json_item(
                simple_bar_plot(
                    [baseline_copy, contender_copy], height=200, vbar_width=0.3
                ),
                "plot",
            ),
        )
        return plot

    @authorize_or_terminate
    def get(self, compare_ids: str) -> str:
        """
        The argument `compare_ids` is an user-given unvalidated string which is
        supposed to be of the following shape:

                    <baseline_id>...<contender_id>

        Parse the shape here to provide some friendly UI feedback for common
        mistakes.

        However, for now rely on the API layer to check if these IDs are
        'known'.

        The API layer will parse the string `compare_ids` again, but that's OK
        for now.

        Note that the two IDs that are encoded `compare_ids` can be either two
        run IDs or two benchmark result IDs.
        """

        if "..." not in compare_ids:
            return error_page(
                "Got unexpected URL path pattern. Expected: <id>...<id>",
                subtitle=self.title,
            )

        baseline_id, contender_id = compare_ids.split("...", 1)

        if not baseline_id:
            return error_page(
                "No baseline ID was provided. Expected format: <baseline_id>...<contender_id>",
                subtitle=self.title,
            )

        if not contender_id:
            return error_page(
                "No contender ID was provided. Expected format: <baseline-id>...<contender-id>",
                subtitle=self.title,
            )

        comparison_results, error_string = self._compare(
            baseline_id=baseline_id, contender_id=contender_id
        )

        if error_string is not None:
            return error_page(
                f"cannot perform comparison: {error_string}",
                alert_level="info",
                subtitle=self.title,
            )

        if len(comparison_results) == 0:
            return error_page(
                "comparison yielded 0 benchmark results",
                alert_level="info",
                subtitle=self.title,
            )

        return self.page(
            comparisons=comparison_results,
            baseline_id=baseline_id,
            contender_id=contender_id,
        )

    def _compare(
        self, baseline_id: str, contender_id: str
    ) -> Tuple[List, Optional[str]]:
        """
        Return a 2-tuple.

        If the last item is a string then it is an error message for why
        the comparison failed. Do not process the first item then.
        """
        comparisons, errmsg = self.get_comparisons(baseline_id, contender_id)
        if errmsg:
            return [], errmsg

        # below is legacy code, review for bugs and clarity
        # Mutate comparison objs (dictionaries) on the fly
        for c in comparisons:
            view = "app.compare-benchmark-results"
            if c["baseline"] and c["contender"]:
                compare = f'{c["baseline"]["benchmark_result_id"]}...{c["contender"]["benchmark_result_id"]}'
                c["compare_benchmarks_url"] = f.url_for(view, compare_ids=compare)
            else:
                c["compare_benchmarks_url"] = None

        return comparisons, None


class CompareBenchmarkResults(Compare):
    type = "benchmark-result"
    html = "compare-entity.html"
    title = "Compare Benchmark Results"

    def get_comparisons(
        self, baseline_id: str, contender_id: str
    ) -> Tuple[List[dict], Optional[str]]:
        # Re-assemble the stringified input argument for the virtual API
        # endpoint, carrying both baseline and contender ID
        params = {"compare_ids": f"{baseline_id}...{contender_id}"}
        response = self.api_get("api.compare-benchmark-results", **params)

        if response.status_code == 200:
            return [response.json], None

        log.error(
            "processing req to %s -- unexpected response for virtual request: %s, %s",
            f.request.url,
            response.status_code,
            response.text,
        )
        # poor-mans error propagation, until we remove the API
        # layer indirection.
        errmsg = response.text
        try:
            errmsg = response.json["description"]
        except Exception:
            pass
        return [], errmsg


class CompareRuns(Compare):
    type = "run"
    # non-intuitive name for a template supposed to render the "compare two
    # runs" view.
    html = "compare-list.html"
    title = "Compare Runs"

    def get_comparisons(
        self, baseline_id: str, contender_id: str
    ) -> Tuple[List[dict], str | None]:
        # Instead of hitting the API we'll hit the DB directly using the same code.
        try:
            api = CompareRunsAPI()
            response = api._get_response_as_dict(
                compare_ids=f"{baseline_id}...{contender_id}",
                cursor=None,
                page_size=None,
                threshold=None,
                threshold_z=None,
            )
            return response["data"], None
        except HTTPException as e:
            return [], e.description


rule(
    "/compare/benchmark-results/<compare_ids>/",
    view_func=CompareBenchmarkResults.as_view("compare-benchmark-results"),
    methods=["GET"],
)
# legacy route
rule(
    "/compare/benchmarks/<compare_ids>/",
    endpoint="compare-benchmarks",
    redirect_to="/compare/benchmark-results/<compare_ids>/",
    methods=["GET"],
)
rule(
    "/compare/runs/<compare_ids>/",
    view_func=CompareRuns.as_view("compare-runs"),
    methods=["GET"],
)
