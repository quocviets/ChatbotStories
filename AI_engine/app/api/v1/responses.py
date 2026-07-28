def api_response(code: int, message: str, **payload) -> dict:
    return {"code": code, "message": message, **payload}
