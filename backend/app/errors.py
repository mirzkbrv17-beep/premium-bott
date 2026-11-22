class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class InsufficientFunds(DomainError):
    def __init__(self, currency: str = ""):
        super().__init__("insufficient_funds", f"{currency.replace('_', ' ')} balansi yetarli emas".strip(), 402)


def not_found(what="Topilmadi"):
    return DomainError("not_found", what, 404)


def forbidden(msg="Ruxsat yo'q"):
    return DomainError("forbidden", msg, 403)
