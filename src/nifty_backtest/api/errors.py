"""One error type for the whole API, turned into one JSON shape (ErrorBody).

Status codes (owner-approved for M5):
  404 run_not_found, trade_not_found, not_found   the thing asked for does not exist
  404 study_not_found                             (M7) no such study folder
  409 metrics_not_computed                        the run exists but has no metrics yet
  409 run_in_progress, run_exists                 a launch conflicts with another one
  422 invalid_request                             bad id format or bad parameters
  500 artifact_invalid                            a saved file is missing, unreadable or
                                                  not shaped as expected (names the file)
  500 run_failed                                  a launched backtest raised an error
  503 data_unavailable                            no local market data to launch a run with
"""


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        error: str,
        detail: str,
        run_id: str | None = None,
        artifact: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.error = error
        self.detail = detail
        self.run_id = run_id
        self.artifact = artifact
