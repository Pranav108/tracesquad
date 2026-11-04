class ApiError(Exception):
    """An error the API returns as {"detail": ...} with the given status code."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
