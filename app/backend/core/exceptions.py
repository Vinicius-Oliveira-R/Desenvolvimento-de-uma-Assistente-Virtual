from fastapi import status


class DomainError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT


class BusinessRuleError(DomainError):
    status_code = status.HTTP_400_BAD_REQUEST


class UnauthorizedError(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN


class HorarioIndisponivelError(ConflictError):
    MENSAGEM_RESERVADO = "Este horário acabou de ser reservado por outro paciente."

    def __init__(self, detail: str = MENSAGEM_RESERVADO):
        super().__init__(detail)
