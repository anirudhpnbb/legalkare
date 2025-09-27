# exceptions.py

class LegalKareError(Exception):
    """
    Base exception for LegalKare-specific errors.
    """
    def __init__(self, message="An error occurred", error_code="LKE00000", status_code=400, payload=None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.payload = payload or {}

    def to_dict(self):
        response = dict(self.payload)
        response["error_code"] = self.error_code
        response["message"] = self.message
        return response


class InputValidationError(LegalKareError):
    def __init__(self, message="Invalid input provided", payload=None):
        super().__init__(message, error_code="LKE00001", status_code=400, payload=payload)


class UserNotFoundError(LegalKareError):
    def __init__(self, message="User not found", payload=None):
        super().__init__(message, error_code="LKE00002", status_code=404, payload=payload)


class DocumentNotFoundError(LegalKareError):
    def __init__(self, message="Document not found", payload=None):
        super().__init__(message, error_code="LKE00003", status_code=404, payload=payload)


class DatabaseError(LegalKareError):
    def __init__(self, message="A database error occurred", payload=None):
        super().__init__(message, error_code="LKE00004", status_code=500, payload=payload)


class FileUploadError(LegalKareError):
    def __init__(self, message="File upload failed", payload=None):
        super().__init__(message, error_code="LKE00005", status_code=500, payload=payload)


class S3UploadError(LegalKareError):
    def __init__(self, message="S3 upload failed", payload=None):
        super().__init__(message, error_code="LKE00006", status_code=500, payload=payload)


class EmailSendingError(LegalKareError):
    def __init__(self, message="Failed to send email", payload=None):
        super().__init__(message, error_code="LKE00007", status_code=500, payload=payload)


class AuthenticationError(LegalKareError):
    def __init__(self, message="Authentication failed", payload=None):
        super().__init__(message, error_code="LKE00008", status_code=401, payload=payload)


class AuthorizationError(LegalKareError):
    def __init__(self, message="Authorization failed", payload=None):
        super().__init__(message, error_code="LKE00009", status_code=403, payload=payload)


class ExternalServiceError(LegalKareError):
    def __init__(self, message="External service error", payload=None):
        super().__init__(message, error_code="LKE00010", status_code=502, payload=payload)


class NotificationError(LegalKareError):
    def __init__(self, message="Notification error", payload=None):
        super().__init__(message, error_code="LKE00011", status_code=500, payload=payload)


class AppointmentError(LegalKareError):
    def __init__(self, message="Appointment error", payload=None):
        super().__init__(message, error_code="LKE00012", status_code=400, payload=payload)


class ConsultationError(LegalKareError):
    def __init__(self, message="Consultation error", payload=None):
        super().__init__(message, error_code="LKE00013", status_code=400, payload=payload)


class EmbeddingError(LegalKareError):
    def __init__(self, message="Embedding generation error", payload=None):
        super().__init__(message, error_code="LKE00014", status_code=500, payload=payload)


class SummarizationError(LegalKareError):
    def __init__(self, message="Summarization error", payload=None):
        super().__init__(message, error_code="LKE00015", status_code=500, payload=payload)


class TwilioError(LegalKareError):
    def __init__(self, message="Twilio service error", payload=None):
        super().__init__(message, error_code="LKE00016", status_code=500, payload=payload)


class FileProcessingError(LegalKareError):
    def __init__(self, message="File processing error", payload=None):
        super().__init__(message, error_code="LKE00017", status_code=500, payload=payload)
