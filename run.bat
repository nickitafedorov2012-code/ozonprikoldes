@echo off
echo Starting... > start.log
echo Installing dependencies... >> start.log
pip install -r requirements.txt >> start.log 2>&1
echo Starting Streamlit app... >> start.log
streamlit run app.py >> start.log 2>&1
pause
