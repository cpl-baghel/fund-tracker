# Mutual Fund Holdings Tracker

This application helps you track mutual fund holdings and their changes over time. It allows you to:
- Add and manage multiple mutual funds
- Record top 10-20 holdings for each fund
- Track sector-wise and company-wise exposure
- Visualize holdings distribution through charts
- Maintain historical records of holdings changes

## Setup

1. Install Python 3.7 or higher
2. Install the required packages:
```bash
pip install -r requirements.txt
```

## Running the Application

Run the following command in your terminal:
```bash
streamlit run app.py
```

The application will open in your default web browser.

## Usage

1. **Adding a New Fund**
   - Enter the fund name in the sidebar
   - Click "Add Fund"

2. **Recording Holdings**
   - Select a fund from the dropdown in the sidebar
   - Enter the number of holdings you want to record
   - Fill in the company name, sector, and percentage for each holding
   - Click "Save Holdings"

3. **Viewing Holdings**
   - Select a fund from the sidebar
   - View the current holdings in the table
   - Analyze sector-wise distribution through the pie chart
   - View company-wise distribution through the bar chart

4. **Updating Holdings**
   - Select the fund
   - Enter the new holdings data
   - Save to record the changes

## Features

- Simple and intuitive interface
- Visual representation of holdings distribution
- Historical tracking of holdings changes
- Sector-wise and company-wise analysis
- Support for multiple funds 