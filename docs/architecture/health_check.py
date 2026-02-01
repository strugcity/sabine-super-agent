from fastapi import FastAPI, status

app = FastAPI()

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    Health check endpoint for the Sabine backend.
    
    Returns:
        dict: A dictionary with the current status.
    """
    return {"status": "ok"}