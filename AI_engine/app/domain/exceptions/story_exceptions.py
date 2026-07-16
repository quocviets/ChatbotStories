class StoryEngineException(Exception):
    """Base exception for AI Story Engine"""
    pass

class StoryNotFoundException(StoryEngineException):
    """Raised when story does not exist"""
    pass

class JobNotFoundException(StoryEngineException):
    """Raised when job does not exist"""
    pass

class CapabilityMismatchException(StoryEngineException):
    """Raised when model does not support required context length or features"""
    pass

class RateLimitException(StoryEngineException):
    """Raised when provider rate limit is hit"""
    pass

class ProviderException(StoryEngineException):
    """Raised when the LLM provider returns an error"""
    pass
