class ApplicationError(Exception):
    def __init__(self, code: str, field: str, message: str) -> None:
        self.code = code.encode("utf-8", errors="backslashreplace").decode("utf-8")
        self.field = field.encode("utf-8", errors="backslashreplace").decode("utf-8")
        self.message = message.encode("utf-8", errors="backslashreplace").decode("utf-8")
        super().__init__(f"{self.code}: {self.field}: {self.message}")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "message": self.message}


class SubmissionError(ApplicationError):
    pass


class AnalysisFailure(ApplicationError):
    def __init__(self, message: str, *, field: str = "analysis") -> None:
        super().__init__("analysis_error", field, message)


class ConfigurationError(ApplicationError):
    def __init__(self, message: str, *, field: str = "config") -> None:
        super().__init__("configuration_error", field, message)
