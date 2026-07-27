@echo off
echo Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Failed to install dependencies.
    pause
    exit /b %errorlevel%
)
echo Starting Streamlit app...
streamlit run app.py
pause
