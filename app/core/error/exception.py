class BusinessException(Exception):
    def __init__(self, error_code):
        self.error_code = error_code
        self.message = error_code.message
        self.status_code = error_code.status_code
        super().__init__(error_code.message)