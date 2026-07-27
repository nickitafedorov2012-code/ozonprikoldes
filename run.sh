#!/bin/bash
echo "Installing dependencies..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install dependencies."
    exit 1
fi
echo "Starting Streamlit app..."
streamlit run app.py
