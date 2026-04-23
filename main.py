import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.core.app_state:app",
        host="0.0.0.0",
        port=8000,
        reload=True,        # set False in production
        log_level="info",
    )
