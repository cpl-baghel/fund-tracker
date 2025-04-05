from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import sqlite3
from datetime import datetime
import pandas as pd
import random  # For generating mock price updates
import io  # For in-memory file handling
import csv  # For CSV export
import openpyxl
from werkzeug.utils import secure_filename
from io import TextIOWrapper
import json
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

# Add template filter for current date/time
@app.template_filter('now')
def template_now():
    """Return the current datetime for use in templates"""
    return datetime.now()

# Add template filter for JSON conversion
@app.template_filter('tojson')
def tojson_filter(obj):
    """Custom tojson filter for templates"""
    return json.dumps(obj)

@app.context_processor
def inject_datetime():
    """Make datetime available in all templates"""
    return {'datetime': datetime}

def get_db():
    """Get database connection"""
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    """Check if file has an allowed extension"""
    allowed_extensions = {'csv', 'xls', 'xlsx'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def init_db():
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS funds
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  fund_name TEXT NOT NULL,
                  fund_category TEXT,
                  fund_house TEXT,
                  fund_manager TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                  
    # Create holdings table
    c.execute('''CREATE TABLE IF NOT EXISTS holdings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  fund_id INTEGER,
                  month_year TEXT NOT NULL,
                  company_name TEXT NOT NULL,
                  sector TEXT,
                  percentage REAL NOT NULL,
                  added_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (fund_id) REFERENCES funds (id))''')
    
    # Create sectors table for reference
    c.execute('''CREATE TABLE IF NOT EXISTS sectors
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  sector_name TEXT UNIQUE NOT NULL)''')
                  
    # Add some default sectors if they don't exist
    sectors = [
        "Financials", "Information Technology", "Healthcare", "Consumer Goods", 
        "Energy", "Consumer Discretionary", "Industrials", "Telecom", 
        "Materials", "Real Estate", "Utilities", "Media & Entertainment",
        "Transportation & Logistics", "Chemicals", "Infrastructure",
        "Hospitality & Tourism", "Defense & Aerospace", "Agriculture",
        "Education", "Retail & E-commerce", "Luxury & Lifestyle", "Others"
    ]
    
    for sector in sectors:
        c.execute("INSERT OR IGNORE INTO sectors (sector_name) VALUES (?)", (sector,))
    
    # Check if demat_accounts table exists, if not create it
    c.execute('''CREATE TABLE IF NOT EXISTS demat_accounts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  account_name TEXT NOT NULL,
                  broker TEXT,
                  account_number TEXT,
                  initial_investment REAL DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                  
    # Check if demat_holdings table exists, if not create it
    c.execute('''CREATE TABLE IF NOT EXISTS demat_holdings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  account_id INTEGER,
                  company_name TEXT NOT NULL,
                  symbol TEXT,
                  quantity INTEGER NOT NULL,
                  purchase_price REAL,
                  current_price REAL,
                  sector TEXT,
                  added_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (account_id) REFERENCES demat_accounts (id))''')
    
    conn.commit()
    conn.close()

def upgrade_db():
    """Update database schema if needed"""
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Check if initial_investment column exists in demat_accounts table
    try:
        c.execute("SELECT initial_investment FROM demat_accounts LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        print("Upgrading database: Adding initial_investment column to demat_accounts table")
        c.execute("ALTER TABLE demat_accounts ADD COLUMN initial_investment REAL DEFAULT 0")
        conn.commit()
    
    conn.close()

@app.route('/')
def index():
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM funds')
    funds = c.fetchall()
    
    # Get the latest activity
    c.execute('''SELECT f.fund_name, h.month_year, COUNT(h.id) as holdings_count, MAX(h.added_on) as added_on 
                FROM holdings h 
                JOIN funds f ON h.fund_id = f.id 
                GROUP BY h.fund_id, h.month_year 
                ORDER BY h.added_on DESC LIMIT 5''')
    activities = c.fetchall()
    
    conn.close()
    return render_template('index.html', funds=funds, recent_activities=activities)

@app.route('/add_fund', methods=['POST'])
def add_fund():
    fund_name = request.form.get('fund_name')
    category = request.form.get('category')
    house = request.form.get('fund_house')
    manager = request.form.get('fund_manager')
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    c.execute('''INSERT INTO funds 
                (fund_name, fund_category, fund_house, fund_manager, last_updated) 
                VALUES (?, ?, ?, ?, ?)''',
              (fund_name, category, house, manager, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    flash('Fund added successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/fund/<int:fund_id>')
def view_fund(fund_id):
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    fund = c.fetchone()
    
    if not fund:
        flash('Fund not found!', 'error')
        return redirect(url_for('index'))
    
    # Get available months for this fund
    c.execute('''SELECT DISTINCT month_year FROM holdings 
                WHERE fund_id = ? ORDER BY month_year DESC''', (fund_id,))
    months = c.fetchall()
    
    # Get the selected month or default to the latest
    selected_month = request.args.get('month')
    if not selected_month and months:
        selected_month = months[0]['month_year']
    
    # Get holdings for selected month
    if selected_month:
        c.execute('''SELECT * FROM holdings 
                    WHERE fund_id = ? AND month_year = ? 
                    ORDER BY percentage DESC''', (fund_id, selected_month))
        holdings = c.fetchall()
        
        # Calculate sector totals
        c.execute('''SELECT sector, SUM(percentage) as total 
                    FROM holdings 
                    WHERE fund_id = ? AND month_year = ? 
                    GROUP BY sector 
                    ORDER BY total DESC''', (fund_id, selected_month))
        sectors = c.fetchall()
    else:
        holdings = []
        sectors = []
    
    conn.close()
    return render_template('view_fund.html', fund=fund, holdings=holdings, 
                           sectors=sectors, months=months, selected_month=selected_month)

@app.route('/fund/<int:fund_id>/edit', methods=['GET', 'POST'])
def edit_fund(fund_id):
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    fund = c.fetchone()
    
    if not fund:
        flash('Fund not found!', 'error')
        return redirect(url_for('index'))
    
    # Get all sectors for the dropdown
    c.execute('SELECT sector_name FROM sectors ORDER BY sector_name')
    sectors = [row['sector_name'] for row in c.fetchall()]
    
    if request.method == 'POST':
        fund_name = request.form.get('fund_name')
        category = request.form.get('category')
        house = request.form.get('fund_house')
        manager = request.form.get('fund_manager')
        
        c.execute('''UPDATE funds 
                    SET fund_name = ?, fund_category = ?, fund_house = ?, fund_manager = ?, last_updated = ?
                    WHERE id = ?''', 
                  (fund_name, category, house, manager, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), fund_id))
        conn.commit()
        flash('Fund updated successfully!', 'success')
        return redirect(url_for('view_fund', fund_id=fund_id))
    
    # Get available months for this fund
    c.execute('''SELECT DISTINCT month_year FROM holdings 
                WHERE fund_id = ? ORDER BY month_year DESC''', (fund_id,))
    months = c.fetchall()
    
    # Get the selected month or default to the latest
    selected_month = request.args.get('month')
    if not selected_month and months:
        selected_month = months[0]['month_year']
    
    # Get holdings for the selected month
    if selected_month:
        c.execute('''SELECT * FROM holdings 
                    WHERE fund_id = ? AND month_year = ? 
                    ORDER BY percentage DESC''', (fund_id, selected_month))
        holdings = c.fetchall()
    else:
        holdings = []
        
    conn.close()
    
    categories = ["Large Cap", "Mid Cap", "Small Cap", "Multi Cap", "Debt", "Hybrid", "Index", "Sectoral"]
    
    return render_template('edit_fund.html', fund=fund, categories=categories, 
                          holdings=holdings, sectors=sectors, months=months, selected_month=selected_month)

@app.route('/fund/<int:fund_id>/update', methods=['POST'])
def update_fund(fund_id):
    fund_name = request.form.get('fund_name')
    category = request.form.get('category')
    house = request.form.get('fund_house')
    manager = request.form.get('fund_manager')
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    c.execute('''UPDATE funds 
                SET fund_name = ?, fund_category = ?, fund_house = ?, fund_manager = ?, last_updated = ?
                WHERE id = ?''', 
              (fund_name, category, house, manager, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), fund_id))
    conn.commit()
    conn.close()
    
    flash('Fund updated successfully!', 'success')
    return redirect(url_for('view_fund', fund_id=fund_id))

@app.route('/fund/<int:fund_id>/add_holding', methods=['POST'])
def add_holding(fund_id):
    month_year = request.form.get('month_year')
    company_name = request.form.get('company_name')
    sector = request.form.get('sector')
    percentage = float(request.form.get('percentage', 0))
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Check if fund exists
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    if not c.fetchone():
        conn.close()
        flash('Fund not found!', 'error')
        return redirect(url_for('index'))
    
    # Insert the holding
    c.execute('''INSERT INTO holdings 
                (fund_id, month_year, company_name, sector, percentage)
                VALUES (?, ?, ?, ?, ?)''',
              (fund_id, month_year, company_name, sector, percentage))
    
    conn.commit()
    conn.close()
    
    flash(f'Holding "{company_name}" added successfully!', 'success')
    return redirect(url_for('view_fund', fund_id=fund_id, month=month_year))

@app.route('/holding/<int:holding_id>/delete')
def delete_holding(holding_id):
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Get fund_id and month_year before deleting
    c.execute('SELECT fund_id, month_year FROM holdings WHERE id = ?', (holding_id,))
    result = c.fetchone()
    
    if not result:
        conn.close()
        flash('Holding not found!', 'error')
        return redirect(url_for('index'))
    
    fund_id, month_year = result
    
    # Delete the holding
    c.execute('DELETE FROM holdings WHERE id = ?', (holding_id,))
    conn.commit()
    conn.close()
    
    flash('Holding deleted successfully!', 'success')
    return redirect(url_for('view_fund', fund_id=fund_id, month=month_year))

@app.route('/fund/<int:fund_id>/import_holdings', methods=['POST'])
def import_holdings(fund_id):
    if 'holdings_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('edit_fund', fund_id=fund_id))
    
    file = request.files['holdings_file']
    month_year = request.form.get('month_year')
    
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('edit_fund', fund_id=fund_id))
    
    if file and month_year:
        try:
            # Determine file type and read
            if file.filename.endswith('.csv'):
                # Try to read the file without skipping rows first
                df = pd.read_csv(file)
            elif file.filename.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(file)
            else:
                flash('Unsupported file format. Please use CSV or Excel.', 'error')
                return redirect(url_for('edit_fund', fund_id=fund_id))
            
            # Check if this is the standard format with month_year column
            if 'month_year' in df.columns:
                # Filter only the requested month if it's a multi-month file
                df = df[df['month_year'] == month_year]
                if len(df) == 0:
                    # If no entries for the month, check if we need to warn the user
                    available_months = df['month_year'].unique()
                    if len(available_months) > 0:
                        flash(f'No entries found for {month_year}. Available months in file: {", ".join(available_months)}', 'warning')
                        return redirect(url_for('view_fund', fund_id=fund_id))
            
            # Rename columns if they match the export format 
            if df.columns.tolist() == ['Company Name', 'Sector', 'Percentage']:
                df.columns = ['company_name', 'sector', 'percentage']
            
            # Check required columns
            required_columns = ['company_name', 'percentage']
            for col in required_columns:
                if col not in df.columns:
                    flash(f'Required column "{col}" not found in file. File must contain "company_name" and "percentage" columns', 'error')
                    return redirect(url_for('view_fund', fund_id=fund_id))
            
            # Ensure sector column exists
            if 'sector' not in df.columns:
                df['sector'] = 'Others'  # Default sector
            
            # Clean and convert data
            df['percentage'] = pd.to_numeric(df['percentage'], errors='coerce').fillna(0)
            
            # Check if there's any data to import
            if len(df) == 0:
                flash('No valid data found in the file to import', 'error')
                return redirect(url_for('view_fund', fund_id=fund_id))
            
            # Prepare data for database
            conn = sqlite3.connect('funds.db')
            c = conn.cursor()
            
            # Insert each holding
            for _, row in df.iterrows():
                c.execute('''INSERT INTO holdings 
                            (fund_id, month_year, company_name, sector, percentage)
                            VALUES (?, ?, ?, ?, ?)''',
                          (fund_id, month_year, 
                           str(row['company_name']), 
                           str(row.get('sector', 'Others')), 
                           float(row['percentage'])))
            
            conn.commit()
            conn.close()
            
            flash(f'Successfully imported {len(df)} holdings!', 'success')
            return redirect(url_for('view_fund', fund_id=fund_id, month=month_year))
        except Exception as e:
            flash(f'Error importing file: {str(e)}', 'error')
            import traceback
            print(traceback.format_exc())
    
    return redirect(url_for('view_fund', fund_id=fund_id, month=month_year))

@app.route('/fund/<int:fund_id>/analysis')
def fund_analysis(fund_id):
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get fund details
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    fund = c.fetchone()
    
    if not fund:
        flash('Fund not found!', 'error')
        return redirect(url_for('index'))
    
    # Get all months with holdings
    c.execute('''SELECT DISTINCT month_year FROM holdings 
                WHERE fund_id = ? ORDER BY month_year''', (fund_id,))
    months = [row['month_year'] for row in c.fetchall()]
    
    # Get sector-wise allocation for each month
    sector_data = {}
    for month in months:
        c.execute('''SELECT sector, SUM(percentage) as total 
                   FROM holdings 
                   WHERE fund_id = ? AND month_year = ? 
                   GROUP BY sector''', (fund_id, month))
        sector_data[month] = {row['sector']: row['total'] for row in c.fetchall()}
    
    # Get top holdings changes between months
    top_holdings_changes = []
    if len(months) > 1:
        latest_month = months[-1]
        previous_month = months[-2]
        
        # Get latest month holdings
        c.execute('''SELECT company_name, percentage 
                   FROM holdings 
                   WHERE fund_id = ? AND month_year = ?''', 
                  (fund_id, latest_month))
        latest_holdings = {row['company_name']: row['percentage'] for row in c.fetchall()}
        
        # Get previous month holdings
        c.execute('''SELECT company_name, percentage 
                   FROM holdings 
                   WHERE fund_id = ? AND month_year = ?''', 
                  (fund_id, previous_month))
        previous_holdings = {row['company_name']: row['percentage'] for row in c.fetchall()}
        
        # Calculate changes
        all_companies = set(latest_holdings.keys()) | set(previous_holdings.keys())
        for company in all_companies:
            latest = latest_holdings.get(company, 0)
            previous = previous_holdings.get(company, 0)
            change = latest - previous
            
            if abs(change) > 0.1:  # Only show significant changes
                top_holdings_changes.append({
                    'company': company,
                    'previous': previous,
                    'latest': latest,
                    'change': change
                })
        
        # Sort by absolute change
        top_holdings_changes.sort(key=lambda x: abs(x['change']), reverse=True)
        top_holdings_changes = top_holdings_changes[:10]  # Show top 10
    
    conn.close()
    
    return render_template('fund_analysis.html', fund=fund, 
                          months=months, sector_data=sector_data,
                          top_holdings_changes=top_holdings_changes)
    
@app.route('/fund/<int:fund_id>/export', methods=['GET'])
def export_fund_holdings(fund_id):
    month = request.args.get('month')
    
    if not month:
        flash('Month is required for export', 'error')
        return redirect(url_for('view_fund', fund_id=fund_id))
    
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get fund details
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    fund = c.fetchone()
    
    if not fund:
        conn.close()
        flash('Fund not found', 'error')
        return redirect(url_for('index'))
    
    # Get holdings for the specified month
    c.execute('''SELECT * FROM holdings 
               WHERE fund_id = ? AND month_year = ? 
               ORDER BY percentage DESC''', (fund_id, month))
    holdings = c.fetchall()
    
    if not holdings:
        conn.close()
        flash(f'No holdings found for {month}', 'error')
        return redirect(url_for('view_fund', fund_id=fund_id))
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Fund Name', fund['fund_name']])
    writer.writerow(['Month', month])
    writer.writerow(['Export Date', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow([])  # Empty row
    writer.writerow(['Company Name', 'Sector', 'Percentage'])
    
    # Write data
    for holding in holdings:
        writer.writerow([
            holding['company_name'],
            holding['sector'],
            holding['percentage']
        ])
    
    # Prepare file for download
    output.seek(0)
    
    # Create response
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"{fund['fund_name'].replace(' ', '_')}_{month}.csv"
    )

@app.route('/import', methods=['POST'])
def import_data():
    if 'holdings_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('index'))
    
    file = request.files['holdings_file']
    fund_id = request.form.get('fund_id')
    month_year = request.form.get('month_year')
    
    if not fund_id or not month_year:
        flash('Fund ID and month/year are required', 'error')
        return redirect(url_for('index'))
        
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('index'))
    
    if file:
        try:
            # Determine file type and read
            if file.filename.endswith('.csv'):
                df = pd.read_csv(file)
            elif file.filename.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(file)
            else:
                flash('Unsupported file format. Please use CSV or Excel.', 'error')
                return redirect(url_for('index'))
            
            # Check if this is the standard format with month_year column
            if 'month_year' in df.columns:
                # Filter only the requested month if it's a multi-month file
                df = df[df['month_year'] == month_year]
                if len(df) == 0:
                    # If no entries for the month, check if we need to warn the user
                    available_months = df['month_year'].unique()
                    if len(available_months) > 0:
                        flash(f'No entries found for {month_year}. Available months in file: {", ".join(available_months)}', 'warning')
                        return redirect(url_for('index'))
            
            # Rename columns if they match the export format 
            if df.columns.tolist() == ['Company Name', 'Sector', 'Percentage']:
                df.columns = ['company_name', 'sector', 'percentage']
            
            # Check required columns
            required_columns = ['company_name', 'percentage']
            for col in required_columns:
                if col not in df.columns:
                    flash(f'Required column "{col}" not found in file. File must contain "company_name" and "percentage" columns', 'error')
                    return redirect(url_for('index'))
            
            # Ensure sector column exists
            if 'sector' not in df.columns:
                df['sector'] = 'Others'  # Default sector
            
            # Clean and convert data
            df['percentage'] = pd.to_numeric(df['percentage'], errors='coerce').fillna(0)
            
            # Check if there's any data to import
            if len(df) == 0:
                flash('No valid data found in the file to import', 'error')
                return redirect(url_for('index'))
            
            # Prepare data for database
            conn = sqlite3.connect('funds.db')
            c = conn.cursor()
            
            # Insert each holding
            for _, row in df.iterrows():
                c.execute('''INSERT INTO holdings 
                            (fund_id, month_year, company_name, sector, percentage)
                            VALUES (?, ?, ?, ?, ?)''',
                          (fund_id, month_year, 
                           str(row['company_name']), 
                           str(row.get('sector', 'Others')), 
                           float(row['percentage'])))
            
            conn.commit()
            conn.close()
            
            flash(f'Successfully imported {len(df)} holdings!', 'success')
            return redirect(url_for('view_fund', fund_id=fund_id, month=month_year))
        except Exception as e:
            flash(f'Error importing file: {str(e)}', 'error')
            import traceback
            print(traceback.format_exc())
    
    return redirect(url_for('index'))

@app.route('/fund/<int:fund_id>/compare')
def compare_months(fund_id):
    month1 = request.args.get('month1')
    month2 = request.args.get('month2')
    
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get fund details
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    fund = c.fetchone()
    
    if not fund:
        flash('Fund not found!', 'error')
        return redirect(url_for('index'))
    
    # Get all available months
    c.execute('''SELECT DISTINCT month_year FROM holdings 
                WHERE fund_id = ? ORDER BY month_year DESC''', (fund_id,))
    available_months = [row['month_year'] for row in c.fetchall()]
    
    # If months not specified, use the latest two months
    if not month1 and len(available_months) > 0:
        month1 = available_months[0]
    if not month2 and len(available_months) > 1:
        month2 = available_months[1]
    
    comparison_data = []
    
    if month1 and month2:
        # Get holdings for month1
        c.execute('''SELECT company_name, sector, percentage
                    FROM holdings 
                    WHERE fund_id = ? AND month_year = ?''', 
                  (fund_id, month1))
        month1_holdings = {row['company_name']: dict(row) for row in c.fetchall()}
        
        # Get holdings for month2
        c.execute('''SELECT company_name, sector, percentage
                    FROM holdings 
                    WHERE fund_id = ? AND month_year = ?''', 
                  (fund_id, month2))
        month2_holdings = {row['company_name']: dict(row) for row in c.fetchall()}
        
        # Combine unique companies from both months
        all_companies = set(month1_holdings.keys()) | set(month2_holdings.keys())
        
        # Create comparison data
        for company in all_companies:
            month1_data = month1_holdings.get(company, {'percentage': 0, 'sector': ''})
            month2_data = month2_holdings.get(company, {'percentage': 0, 'sector': month1_data['sector']})
            
            # If sector is empty in month1 but present in month2, use month2's sector
            sector = month1_data['sector'] or month2_data['sector']
            
            change = month1_data['percentage'] - month2_data['percentage']
            
            comparison_data.append({
                'company': company,
                'sector': sector,
                'month1_percentage': month1_data['percentage'],
                'month2_percentage': month2_data['percentage'],
                'change': change,
                'status': 'Added' if month2_data['percentage'] == 0 else 
                          'Removed' if month1_data['percentage'] == 0 else 
                          'Increased' if change > 0 else 
                          'Decreased' if change < 0 else 'Unchanged'
            })
        
        # Sort by absolute change
        comparison_data.sort(key=lambda x: abs(x['change']), reverse=True)
    
    # Get sector comparison data
    sector_comparison = {}
    
    if month1 and month2:
        # Get sector data for month1
        c.execute('''SELECT sector, SUM(percentage) as total
                    FROM holdings 
                    WHERE fund_id = ? AND month_year = ?
                    GROUP BY sector''', 
                  (fund_id, month1))
        month1_sectors = {row['sector']: row['total'] for row in c.fetchall()}
        
        # Get sector data for month2
        c.execute('''SELECT sector, SUM(percentage) as total
                    FROM holdings 
                    WHERE fund_id = ? AND month_year = ?
                    GROUP BY sector''', 
                  (fund_id, month2))
        month2_sectors = {row['sector']: row['total'] for row in c.fetchall()}
        
        # Combine unique sectors
        all_sectors = set(month1_sectors.keys()) | set(month2_sectors.keys())
        
        for sector in all_sectors:
            month1_total = month1_sectors.get(sector, 0)
            month2_total = month2_sectors.get(sector, 0)
            change = month1_total - month2_total
            
            sector_comparison[sector] = {
                'month1_total': month1_total,
                'month2_total': month2_total,
                'change': change
            }
    
    conn.close()
    
    return render_template('compare_months.html', 
                          fund=fund,
                          available_months=available_months,
                          month1=month1,
                          month2=month2,
                          comparison_data=comparison_data,
                          sector_comparison=sector_comparison)

@app.route('/fund/<int:fund_id>/copy_holdings', methods=['POST'])
def copy_holdings(fund_id):
    source_month = request.form.get('source_month')
    target_month = request.form.get('target_month')
    
    if not source_month or not target_month:
        flash('Source and target months are required', 'error')
        return redirect(url_for('view_fund', fund_id=fund_id))
    
    if source_month == target_month:
        flash('Source and target months must be different', 'error')
        return redirect(url_for('view_fund', fund_id=fund_id))
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Check if fund exists
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    if not c.fetchone():
        conn.close()
        flash('Fund not found!', 'error')
        return redirect(url_for('index'))
    
    # Check if target month already has holdings
    c.execute('SELECT COUNT(*) FROM holdings WHERE fund_id = ? AND month_year = ?', 
              (fund_id, target_month))
    if c.fetchone()[0] > 0:
        conn.close()
        flash(f'Holdings already exist for {target_month}. Please delete them first or choose a different month.', 'error')
        return redirect(url_for('view_fund', fund_id=fund_id))
    
    # Get holdings from source month
    c.execute('''SELECT company_name, sector, percentage 
                FROM holdings 
                WHERE fund_id = ? AND month_year = ?''', 
              (fund_id, source_month))
    source_holdings = c.fetchall()
    
    if not source_holdings:
        conn.close()
        flash(f'No holdings found for {source_month}', 'error')
        return redirect(url_for('view_fund', fund_id=fund_id))
    
    # Copy holdings to target month
    for holding in source_holdings:
        company_name, sector, percentage = holding
        c.execute('''INSERT INTO holdings 
                    (fund_id, month_year, company_name, sector, percentage)
                    VALUES (?, ?, ?, ?, ?)''',
                  (fund_id, target_month, company_name, sector, percentage))
    
    conn.commit()
    conn.close()
    
    flash(f'Successfully copied {len(source_holdings)} holdings from {source_month} to {target_month}', 'success')
    return redirect(url_for('view_fund', fund_id=fund_id, month=target_month))

@app.route('/fund/<int:fund_id>/edit_holdings', methods=['POST'])
def edit_holdings(fund_id):
    month_year = request.form.get('month_year')
    holdings_data = request.form.to_dict(flat=False)
    
    if not month_year:
        flash('Month is required', 'error')
        return redirect(url_for('view_fund', fund_id=fund_id))
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Check if fund exists
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    if not c.fetchone():
        conn.close()
        flash('Fund not found!', 'error')
        return redirect(url_for('index'))
    
    # Update each holding
    holding_ids = holdings_data.get('holding_id', [])
    percentages = holdings_data.get('percentage', [])
    
    for i in range(len(holding_ids)):
        holding_id = int(holding_ids[i])
        percentage = float(percentages[i])
        
        c.execute('''UPDATE holdings 
                   SET percentage = ? 
                   WHERE id = ? AND fund_id = ?''', 
                 (percentage, holding_id, fund_id))
    
    conn.commit()
    conn.close()
    
    flash(f'Successfully updated {len(holding_ids)} holdings!', 'success')
    return redirect(url_for('view_fund', fund_id=fund_id, month=month_year))

# Routes for Demat account management
@app.route('/demat_accounts')
def demat_accounts():
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get all demat accounts
    c.execute('SELECT * FROM demat_accounts ORDER BY account_name')
    accounts = c.fetchall()
    
    # Get summary data for each account
    account_summaries = []
    for account in accounts:
        c.execute('''SELECT COUNT(*) as holdings_count, 
                    SUM(quantity * current_price) as total_value 
                    FROM demat_holdings 
                    WHERE account_id = ?''', (account['id'],))
        summary = c.fetchone()
        
        account_summaries.append({
            'id': account['id'],
            'name': account['account_name'],
            'broker': account['broker'],
            'holdings_count': summary['holdings_count'] if summary else 0,
            'total_value': summary['total_value'] if summary and summary['total_value'] else 0
        })
    
    conn.close()
    
    return render_template('demat_accounts.html', accounts=account_summaries)

@app.route('/add_demat_account', methods=['POST'])
def add_demat_account():
    account_name = request.form.get('account_name')
    broker = request.form.get('broker')
    account_number = request.form.get('account_number')
    initial_investment = float(request.form.get('initial_investment', 0))
    
    if not account_name:
        flash('Account name is required', 'error')
        return redirect(url_for('demat_accounts'))
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    c.execute('''INSERT INTO demat_accounts 
                (account_name, broker, account_number, initial_investment) 
                VALUES (?, ?, ?, ?)''',
              (account_name, broker, account_number, initial_investment))
    
    conn.commit()
    conn.close()
    
    flash(f'Account "{account_name}" added successfully!', 'success')
    return redirect(url_for('demat_accounts'))

@app.route('/demat_account/<int:account_id>')
def view_demat_account(account_id):
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get account details
    c.execute('SELECT * FROM demat_accounts WHERE id = ?', (account_id,))
    account = c.fetchone()
    
    if not account:
        flash('Account not found!', 'error')
        return redirect(url_for('demat_accounts'))
    
    # Get holdings for this account
    c.execute('''SELECT * FROM demat_holdings 
                WHERE account_id = ? 
                ORDER BY company_name''', (account_id,))
    holdings = c.fetchall()
    
    # Calculate sector allocation
    c.execute('''SELECT sector, SUM(quantity * current_price) as total_value 
                FROM demat_holdings 
                WHERE account_id = ? 
                GROUP BY sector 
                ORDER BY total_value DESC''', (account_id,))
    sectors = c.fetchall()
    
    # Calculate total portfolio value
    c.execute('''SELECT SUM(quantity * current_price) as current_value,
                SUM(quantity * purchase_price) as invested_value
                FROM demat_holdings 
                WHERE account_id = ?''', (account_id,))
    result = c.fetchone()
    
    # Get total values
    current_value = result['current_value'] if result and result['current_value'] else 0
    invested_value = result['invested_value'] if result and result['invested_value'] else 0
    
    # Add initial investment from account - safely access the value
    initial_investment = 0
    if 'initial_investment' in account.keys():
        initial_investment = account['initial_investment']
    total_invested = invested_value + initial_investment
    
    # Calculate gains
    gain_value = current_value - total_invested
    gain_percent = (gain_value / total_invested * 100) if total_invested > 0 else 0
    
    # Convert sector totals to percentages
    sector_percentages = []
    if current_value > 0:
        for sector in sectors:
            sector_percentages.append({
                'sector': sector['sector'] or 'Unassigned',
                'value': sector['total_value'],
                'percentage': (sector['total_value'] / current_value) * 100
            })
    
    conn.close()
    
    return render_template('view_demat.html', 
                          account=account, 
                          holdings=holdings, 
                          sectors=sector_percentages,
                          total_value=current_value,
                          total_invested=total_invested,
                          gain_value=gain_value,
                          gain_percent=gain_percent)

@app.route('/demat_account/<int:account_id>/add_holding', methods=['POST'])
def add_demat_holding(account_id):
    company_name = request.form.get('company_name')
    symbol = request.form.get('symbol')
    quantity = int(request.form.get('quantity', 0))
    purchase_price = float(request.form.get('purchase_price', 0))
    current_price = float(request.form.get('current_price', 0))
    sector = request.form.get('sector')
    
    if not company_name or quantity <= 0:
        flash('Company name and quantity are required', 'error')
        return redirect(url_for('view_demat_account', account_id=account_id))
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Check if account exists
    c.execute('SELECT * FROM demat_accounts WHERE id = ?', (account_id,))
    if not c.fetchone():
        conn.close()
        flash('Account not found!', 'error')
        return redirect(url_for('demat_accounts'))
    
    # Insert the holding
    c.execute('''INSERT INTO demat_holdings 
                (account_id, company_name, symbol, quantity, purchase_price, current_price, sector)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (account_id, company_name, symbol, quantity, purchase_price, current_price, sector))
    
    conn.commit()
    conn.close()
    
    flash(f'Holding "{company_name}" added successfully!', 'success')
    return redirect(url_for('view_demat_account', account_id=account_id))

@app.route('/demat_holding/<int:holding_id>/delete')
def delete_demat_holding(holding_id):
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Get account_id before deleting
    c.execute('SELECT account_id FROM demat_holdings WHERE id = ?', (holding_id,))
    result = c.fetchone()
    
    if not result:
        conn.close()
        flash('Holding not found!', 'error')
        return redirect(url_for('demat_accounts'))
    
    account_id = result[0]
    
    # Delete the holding
    c.execute('DELETE FROM demat_holdings WHERE id = ?', (holding_id,))
    conn.commit()
    conn.close()
    
    flash('Holding deleted successfully!', 'success')
    return redirect(url_for('view_demat_account', account_id=account_id))

@app.route('/edit_demat_holding/<int:holding_id>', methods=['POST'])
def edit_demat_holding(holding_id):
    company_name = request.form.get('company_name')
    symbol = request.form.get('symbol')
    quantity = int(request.form.get('quantity', 0))
    purchase_price = float(request.form.get('purchase_price', 0))
    current_price = float(request.form.get('current_price', 0))
    sector = request.form.get('sector')
    
    if not company_name or quantity <= 0:
        flash('Company name and quantity are required', 'error')
        return redirect(url_for('demat_accounts'))
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Get account_id before updating
    c.execute('SELECT account_id FROM demat_holdings WHERE id = ?', (holding_id,))
    result = c.fetchone()
    
    if not result:
        conn.close()
        flash('Holding not found!', 'error')
        return redirect(url_for('demat_accounts'))
    
    account_id = result[0]
    
    # Update the holding
    c.execute('''UPDATE demat_holdings 
                SET company_name = ?, symbol = ?, quantity = ?, 
                purchase_price = ?, current_price = ?, sector = ?
                WHERE id = ?''',
              (company_name, symbol, quantity, purchase_price, current_price, sector, holding_id))
    
    conn.commit()
    conn.close()
    
    flash(f'Holding "{company_name}" updated successfully!', 'success')
    return redirect(url_for('view_demat_account', account_id=account_id))

@app.route('/demat_account/<int:account_id>/import_holdings', methods=['POST'])
def import_demat_holdings(account_id):
    if 'holdings_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('view_demat_account', account_id=account_id))
    
    file = request.files['holdings_file']
    
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('view_demat_account', account_id=account_id))
    
    if file:
        try:
            # Determine file type and read
            if file.filename.endswith('.csv'):
                # First try with basic CSV reading
                df = pd.read_csv(file)
            elif file.filename.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(file)
            else:
                flash('Unsupported file format. Please use CSV or Excel.', 'error')
                return redirect(url_for('view_demat_account', account_id=account_id))
            
            # Map different column name formats to our expected column names
            column_mapping = {
                # Our export format
                'Company Name': 'company_name',
                'Symbol': 'symbol',
                'Quantity': 'quantity',
                'Purchase Price': 'purchase_price',
                'Current Price': 'current_price',
                'Sector': 'sector',
                
                # Google Sheets format (lowercase)
                'company_name': 'company_name',
                'symbol': 'symbol',
                'quantity': 'quantity',
                'purchase_price': 'purchase_price',
                'current_price': 'current_price',
                'sector': 'sector',
                
                # Alternative formats
                'Company': 'company_name',
                'Name': 'company_name',
                'Stock': 'company_name',
                'Symbol/NSE': 'symbol',
                'Symbol/BSE': 'symbol',
                'NSE': 'symbol',
                'BSE': 'symbol',
                'Qty': 'quantity',
                'Shares': 'quantity',
                'No. of Shares': 'quantity',
                'Buy Price': 'purchase_price',
                'Buying Price': 'purchase_price',
                'Cost': 'purchase_price',
                'LTP': 'current_price',
                'Market Price': 'current_price',
                'Price': 'current_price',
                'Category': 'sector',
                'Type': 'sector',
                'Industry': 'sector'
            }
            
            # Rename columns based on the mapping
            renamed_columns = {}
            for col in df.columns:
                if col in column_mapping:
                    renamed_columns[col] = column_mapping[col]
            
            if renamed_columns:
                df = df.rename(columns=renamed_columns)
            
            # Check for required columns
            if 'company_name' not in df.columns:
                # Try to find a column that might contain company names
                possible_name_cols = [col for col in df.columns if 'company' in col.lower() or 'name' in col.lower()]
                if possible_name_cols:
                    df = df.rename(columns={possible_name_cols[0]: 'company_name'})
                else:
                    flash('File must contain a column for company names', 'error')
                    return redirect(url_for('view_demat_account', account_id=account_id))
            
            if 'quantity' not in df.columns:
                # Try to find a column that might contain quantities
                possible_qty_cols = [col for col in df.columns if 'qty' in col.lower() or 'quant' in col.lower() or 'shares' in col.lower()]
                if possible_qty_cols:
                    df = df.rename(columns={possible_qty_cols[0]: 'quantity'})
                else:
                    flash('File must contain a column for quantity', 'error')
                    return redirect(url_for('view_demat_account', account_id=account_id))
            
            # If purchase_price or current_price are missing, add them with defaults
            if 'purchase_price' not in df.columns:
                # Try to find a column that might contain purchase prices
                possible_price_cols = [col for col in df.columns if 'purchase' in col.lower() or 'buy' in col.lower() or 'cost' in col.lower()]
                if possible_price_cols:
                    df = df.rename(columns={possible_price_cols[0]: 'purchase_price'})
                else:
                    # Default to using current_price if available, otherwise use 0
                    if 'current_price' in df.columns:
                        df['purchase_price'] = df['current_price']
                    else:
                        df['purchase_price'] = 0
            
            if 'current_price' not in df.columns:
                # Try to find a column that might contain current prices
                possible_price_cols = [col for col in df.columns if 'current' in col.lower() or 'market' in col.lower() or 'price' in col.lower() or 'ltp' in col.lower()]
                if possible_price_cols:
                    df = df.rename(columns={possible_price_cols[0]: 'current_price'})
                else:
                    # Default to using purchase_price if available, otherwise use 0
                    if 'purchase_price' in df.columns:
                        df['current_price'] = df['purchase_price']
                    else:
                        df['current_price'] = 0
            
            if 'sector' not in df.columns:
                # Try to find a column that might contain sectors
                possible_sector_cols = [col for col in df.columns if 'sector' in col.lower() or 'category' in col.lower() or 'industry' in col.lower() or 'type' in col.lower()]
                if possible_sector_cols:
                    df = df.rename(columns={possible_sector_cols[0]: 'sector'})
                else:
                    df['sector'] = 'Others'  # Default sector
            
            if 'symbol' not in df.columns:
                df['symbol'] = ''  # Default empty symbol
            
            # Convert data types
            df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0).astype(int)
            df['purchase_price'] = pd.to_numeric(df['purchase_price'], errors='coerce').fillna(0).astype(float)
            df['current_price'] = pd.to_numeric(df['current_price'], errors='coerce').fillna(0).astype(float)
            
            # Skip rows with zero quantity or missing company name
            df = df[df['quantity'] > 0]
            df = df[df['company_name'].notna() & (df['company_name'] != '')]
            
            if len(df) == 0:
                flash('No valid holdings found in the file after filtering', 'error')
                return redirect(url_for('view_demat_account', account_id=account_id))
            
            # Prepare data for database
            conn = sqlite3.connect('funds.db')
            c = conn.cursor()
            
            # Check if account exists
            c.execute('SELECT * FROM demat_accounts WHERE id = ?', (account_id,))
            if not c.fetchone():
                conn.close()
                flash('Account not found!', 'error')
                return redirect(url_for('demat_accounts'))
            
            # Insert each holding
            for _, row in df.iterrows():
                c.execute('''INSERT INTO demat_holdings 
                            (account_id, company_name, symbol, quantity, purchase_price, current_price, sector)
                            VALUES (?, ?, ?, ?, ?, ?, ?)''',
                          (account_id, 
                           str(row['company_name']), 
                           str(row.get('symbol', '')),
                           int(row['quantity']),
                           float(row['purchase_price']),
                           float(row['current_price']),
                           str(row.get('sector', 'Others'))))
            
            conn.commit()
            conn.close()
            
            flash(f'Successfully imported {len(df)} holdings!', 'success')
        except Exception as e:
            flash(f'Error importing file: {str(e)}', 'error')
            import traceback
            print(traceback.format_exc())
    
    return redirect(url_for('view_demat_account', account_id=account_id))

@app.route('/portfolio_overview')
def portfolio_overview():
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get all demat accounts
    c.execute('SELECT * FROM demat_accounts ORDER BY account_name')
    accounts = c.fetchall()
    
    # Calculate total portfolio value and allocation
    total_portfolio = []
    total_value = 0
    
    # Only include demat accounts 
    for account in accounts:
        # Calculate account value
        c.execute('''SELECT SUM(quantity * current_price) as account_value 
                     FROM demat_holdings 
                     WHERE account_id = ?''', (account['id'],))
        result = c.fetchone()
        
        # Default to 0 if None
        account_value = 0
        if result and result['account_value']:
            account_value = result['account_value']
            
        # Add initial investment if present - safely access the value
        initial_investment = account['initial_investment'] if 'initial_investment' in account.keys() else 0
        if initial_investment:
            account_value += initial_investment
        
        # Add account to portfolio if it has value
        if account_value > 0:
            total_portfolio.append({
                'id': account['id'],
                'name': account['account_name'],
                'type': 'Demat Account',
                'value': account_value
            })
            total_value += account_value
    
    # Calculate percentage allocations
    for item in total_portfolio:
        item['percentage'] = (item['value'] / total_value * 100) if total_value > 0 else 0
    
    # Sort by value
    total_portfolio.sort(key=lambda x: x['value'], reverse=True)
    
    # Get sector allocation across all portfolios
    sector_allocation = {}
    
    # Get demat account sectors
    c.execute('''SELECT sector, SUM(quantity * current_price) as value 
                 FROM demat_holdings 
                 GROUP BY sector''')
    demat_sectors = c.fetchall()
    
    # Only process sectors if we have any demat_sectors with values
    if demat_sectors:
        for sector in demat_sectors:
            if sector['sector'] is not None and sector['value'] is not None:
                sector_name = sector['sector'] if sector['sector'] else 'Unassigned'
                sector_value = sector['value'] if sector['value'] else 0
                sector_allocation[sector_name] = sector_allocation.get(sector_name, 0) + sector_value
    
    # Convert sector totals to percentages
    sector_percentages = []
    if sector_allocation and total_value > 0:
        for sector, value in sector_allocation.items():
            sector_percentages.append({
                'sector': sector,
                'value': value,
                'percentage': (value / total_value * 100) if total_value > 0 else 0
            })
        
        # Sort by percentage
        sector_percentages.sort(key=lambda x: x['percentage'], reverse=True)
    
    conn.close()
    
    return render_template('portfolio_overview.html', 
                          total_portfolio=total_portfolio,
                          sector_allocation=sector_percentages,
                          total_value=total_value)

@app.route('/update_fund_value', methods=['POST'])
def update_fund_value():
    """Update the current value of a mutual fund"""
    fund_id = request.form.get('fund_id')
    value = float(request.form.get('fund_value', 0))
    date = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    if not fund_id or value <= 0:
        flash('Fund ID and value are required', 'error')
        return redirect(url_for('portfolio_overview'))
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Check if fund exists
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    if not c.fetchone():
        conn.close()
        flash('Fund not found!', 'error')
        return redirect(url_for('portfolio_overview'))
    
    # Create the fund_values table if it doesn't exist
    c.execute('''CREATE TABLE IF NOT EXISTS fund_values
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 fund_id INTEGER,
                 value REAL NOT NULL,
                 date TEXT NOT NULL,
                 added_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 FOREIGN KEY (fund_id) REFERENCES funds (id))''')
    
    # Insert the new value
    c.execute('''INSERT INTO fund_values 
                (fund_id, value, date) 
                VALUES (?, ?, ?)''',
              (fund_id, value, date))
    
    conn.commit()
    conn.close()
    
    flash(f'Fund value updated successfully!', 'success')
    return redirect(url_for('portfolio_overview'))

@app.route('/save_portfolio_snapshot', methods=['POST'])
def save_portfolio_snapshot():
    """Save the current portfolio values as a snapshot for historical tracking"""
    date = request.form.get('snapshot_date', datetime.now().strftime('%Y-%m-%d'))
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Create the portfolio_history table if it doesn't exist
    c.execute('''CREATE TABLE IF NOT EXISTS portfolio_history
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 item_id INTEGER,
                 item_type TEXT,
                 item_name TEXT,
                 value REAL NOT NULL,
                 date TEXT NOT NULL,
                 added_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Get all demat accounts values
    c.execute('SELECT * FROM demat_accounts ORDER BY account_name')
    accounts = c.fetchall()
    
    for account in accounts:
        c.execute('''SELECT SUM(quantity * current_price) as account_value 
                    FROM demat_holdings 
                    WHERE account_id = ?''', (account['id'],))
        result = c.fetchone()
        account_value = result['account_value']
        account_value += account['initial_investment'] or 0  # Add cash component
        
        # Save to history
        c.execute('''INSERT INTO portfolio_history 
                    (item_id, item_type, item_name, value, date) 
                    VALUES (?, ?, ?, ?, ?)''',
                  (account['id'], 'Demat Account', account['account_name'], account_value, date))
    
    # Get all funds with their values
    c.execute('SELECT * FROM funds ORDER BY fund_name')
    funds = c.fetchall()
    
    for fund in funds:
        # Get the latest value entry
        c.execute('''SELECT * FROM fund_values 
                   WHERE fund_id = ? 
                   ORDER BY date DESC LIMIT 1''', (fund['id'],))
        value_entry = c.fetchone()
        
        if value_entry:
            fund_value = value_entry['value']
            
            # Save to history
            c.execute('''INSERT INTO portfolio_history 
                        (item_id, item_type, item_name, value, date) 
                        VALUES (?, ?, ?, ?, ?)''',
                      (fund['id'], 'Mutual Fund', fund['fund_name'], fund_value, date))
    
    conn.commit()
    conn.close()
    
    flash(f'Portfolio snapshot saved for {date}!', 'success')
    return redirect(url_for('portfolio_overview'))

@app.route('/update_demat_prices', methods=['POST'])
def update_demat_prices():
    """Update current prices of demat holdings with random variations to simulate market changes"""
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Get all holdings
    c.execute('SELECT id, current_price FROM demat_holdings')
    holdings = c.fetchall()
    
    update_count = 0
    for holding_id, current_price in holdings:
        # Generate a random price change (-5% to +5%)
        change_percent = random.uniform(-5, 5)
        new_price = current_price * (1 + (change_percent / 100))
        new_price = round(new_price, 2)  # Round to 2 decimal places
        
        # Update the price
        c.execute('UPDATE demat_holdings SET current_price = ? WHERE id = ?', 
                  (new_price, holding_id))
        update_count += 1
    
    conn.commit()
    conn.close()
    
    flash(f'Updated prices for {update_count} holdings with simulated market changes', 'success')
    return redirect(url_for('demat_accounts'))

@app.route('/demat_account/<int:account_id>/update_prices', methods=['POST'])
def update_account_prices(account_id):
    """Update current prices for a specific demat account"""
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Get all holdings for this account
    c.execute('SELECT id, current_price FROM demat_holdings WHERE account_id = ?', (account_id,))
    holdings = c.fetchall()
    
    update_count = 0
    for holding_id, current_price in holdings:
        # Generate a random price change (-5% to +5%)
        change_percent = random.uniform(-5, 5)
        new_price = current_price * (1 + (change_percent / 100))
        new_price = round(new_price, 2)  # Round to 2 decimal places
        
        # Update the price
        c.execute('UPDATE demat_holdings SET current_price = ? WHERE id = ?', 
                  (new_price, holding_id))
        update_count += 1
    
    conn.commit()
    conn.close()
    
    flash(f'Updated prices for {update_count} holdings with simulated market changes', 'success')
    return redirect(url_for('view_demat_account', account_id=account_id))

@app.route('/demat_account/<int:account_id>/export', methods=['GET'])
def export_demat_holdings(account_id):
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get account details
    c.execute('SELECT * FROM demat_accounts WHERE id = ?', (account_id,))
    account = c.fetchone()
    
    if not account:
        conn.close()
        flash('Account not found', 'error')
        return redirect(url_for('demat_accounts'))
    
    # Get holdings
    c.execute('''SELECT * FROM demat_holdings 
               WHERE account_id = ? 
               ORDER BY current_price * quantity DESC''', (account_id,))
    holdings = c.fetchall()
    
    if not holdings:
        conn.close()
        flash('No holdings found for this account', 'error')
        return redirect(url_for('view_demat_account', account_id=account_id))
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Account Name', account['account_name']])
    writer.writerow(['Broker', account['broker'] or 'N/A'])
    writer.writerow(['Export Date', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow([])  # Empty row
    writer.writerow(['Company Name', 'Symbol', 'Quantity', 'Purchase Price', 'Current Price', 'Current Value', 'Profit/Loss', 'Sector'])
    
    # Write data
    for holding in holdings:
        current_value = holding['quantity'] * holding['current_price']
        purchase_value = holding['quantity'] * holding['purchase_price']
        profit_loss = current_value - purchase_value
        
        writer.writerow([
            holding['company_name'],
            holding['symbol'] or '',
            holding['quantity'],
            holding['purchase_price'],
            holding['current_price'],
            current_value,
            profit_loss,
            holding['sector'] or 'N/A'
        ])
    
    # Prepare file for download
    output.seek(0)
    
    # Create response
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"{account['account_name'].replace(' ', '_')}_holdings.csv"
    )

@app.route('/portfolio_export', methods=['GET'])
def export_portfolio():
    conn = sqlite3.connect('funds.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get all demat accounts
    c.execute('SELECT * FROM demat_accounts ORDER BY account_name')
    accounts = c.fetchall()
    
    # Get all funds
    c.execute('SELECT * FROM funds ORDER BY fund_name')
    funds = c.fetchall()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Portfolio Export'])
    writer.writerow(['Export Date', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow([])  # Empty row
    
    # Write demat account holdings
    writer.writerow(['DEMAT ACCOUNT HOLDINGS'])
    writer.writerow(['Account', 'Company', 'Symbol', 'Quantity', 'Purchase Price', 'Current Price', 'Current Value', 'Profit/Loss', 'Sector'])
    
    for account in accounts:
        c.execute('SELECT * FROM demat_holdings WHERE account_id = ? ORDER BY company_name', (account['id'],))
        holdings = c.fetchall()
        
        for holding in holdings:
            current_value = holding['quantity'] * holding['current_price']
            purchase_value = holding['quantity'] * holding['purchase_price']
            profit_loss = current_value - purchase_value
            
            writer.writerow([
                account['account_name'],
                holding['company_name'],
                holding['symbol'] or '',
                holding['quantity'],
                holding['purchase_price'],
                holding['current_price'],
                current_value,
                profit_loss,
                holding['sector'] or 'N/A'
            ])
    
    writer.writerow([])  # Empty row
    
    # Write mutual fund holdings
    writer.writerow(['MUTUAL FUND HOLDINGS'])
    writer.writerow(['Fund', 'Month', 'Company', 'Sector', 'Percentage'])
    
    for fund in funds:
        # Get the latest month
        c.execute('''SELECT month_year FROM holdings 
                   WHERE fund_id = ? 
                   ORDER BY month_year DESC LIMIT 1''', (fund['id'],))
        month_result = c.fetchone()
        
        if month_result:
            latest_month = month_result[0]
            
            # Get holdings for this month
            c.execute('''SELECT * FROM holdings 
                       WHERE fund_id = ? AND month_year = ? 
                       ORDER BY percentage DESC''', (fund['id'], latest_month))
            holdings = c.fetchall()
            
            for holding in holdings:
                writer.writerow([
                    fund['fund_name'],
                    latest_month,
                    holding['company_name'],
                    holding['sector'],
                    holding['percentage']
                ])
    
    # Prepare file for download
    output.seek(0)
    
    # Create response
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"Complete_Portfolio_Export_{datetime.now().strftime('%Y%m%d')}.csv"
    )

@app.route('/download_sample_demat')
def download_sample_demat():
    """Provide a sample file for demat holdings import"""
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['company_name', 'symbol', 'quantity', 'purchase_price', 'current_price', 'sector'])
    
    # Write example data
    writer.writerow(['HDFC Bank', 'HDFCBANK', 50, 1500, 1650, 'Financials'])
    writer.writerow(['Infosys', 'INFY', 100, 1200, 1350, 'Information Technology'])
    writer.writerow(['Reliance Industries', 'RELIANCE', 20, 2400, 2500, 'Energy'])
    writer.writerow(['Tata Motors', 'TATAMOTORS', 150, 350, 400, 'Consumer Discretionary'])
    writer.writerow(['Sun Pharmaceuticals', 'SUNPHARMA', 75, 800, 850, 'Healthcare'])
    
    # Prepare file for download
    output.seek(0)
    
    # Create response
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"sample_demat_import.csv"
    )

@app.route('/demat_account/<int:account_id>/edit', methods=['POST'])
def edit_demat_account(account_id):
    account_name = request.form.get('account_name')
    broker = request.form.get('broker')
    account_number = request.form.get('account_number')
    initial_investment = float(request.form.get('initial_investment', 0))
    
    if not account_name:
        flash('Account name is required', 'error')
        return redirect(url_for('view_demat_account', account_id=account_id))
    
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    c.execute('''UPDATE demat_accounts 
                SET account_name = ?, broker = ?, account_number = ?, initial_investment = ?
                WHERE id = ?''',
              (account_name, broker, account_number, initial_investment, account_id))
    
    conn.commit()
    conn.close()
    
    flash(f'Account "{account_name}" updated successfully!', 'success')
    return redirect(url_for('view_demat_account', account_id=account_id))

@app.route('/download_sample_mutual_fund')
def download_sample_mutual_fund():
    """Provide a sample file for mutual fund holdings import"""
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['month_year', 'company_name', 'sector', 'percentage'])
    
    # List of companies with their sectors
    companies = [
        ('HDFC Bank Ltd.', 'Financials'),
        ('Infosys Ltd.', 'Information Technology'),
        ('Reliance Industries Ltd.', 'Energy'),
        ('ICICI Bank Ltd.', 'Financials'),
        ('Tata Consultancy Services Ltd.', 'Information Technology'),
        ('Hindustan Unilever Ltd.', 'Consumer Goods'),
        ('Bharti Airtel Ltd.', 'Telecom'),
        ('Axis Bank Ltd.', 'Financials'),
        ('Larsen & Toubro Ltd.', 'Industrials'),
        ('Kotak Mahindra Bank Ltd.', 'Financials'),
        ('ITC Ltd.', 'Consumer Goods'),
        ('State Bank of India', 'Financials'),
        ('Maruti Suzuki India Ltd.', 'Consumer Discretionary'),
        ('Asian Paints Ltd.', 'Materials'),
        ('Bajaj Finance Ltd.', 'Financials')
    ]
    
    # Months for which we want to generate data
    months = ['2024-06', '2024-09', '2024-12']
    
    # Generate data for each month with small variations in percentages
    for month in months:
        for company, sector in companies:
            # Base percentage
            base_percentage = random.uniform(1.5, 9.0)
            
            # Add a small variation per month (±0.5%)
            month_index = months.index(month)
            variation = random.uniform(-0.5, 0.5) * (1 + month_index * 0.2)
            
            # Calculate final percentage
            percentage = round(base_percentage + variation, 2)
            
            # Write row
            writer.writerow([month, company, sector, percentage])
    
    # Prepare file for download
    output.seek(0)
    
    # Create response
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"mutual_fund_holdings_sample.csv"
    )

@app.route('/download_historical_mutual_fund_sample')
def download_historical_mutual_fund_sample():
    """Provide a sample file for historical mutual fund holdings import (last 4 quarters)"""
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['month_year', 'company_name', 'sector', 'percentage'])
    
    # Get the current quarter and the last 3 quarters
    current_date = datetime.now()
    quarters = []
    
    for i in range(4):
        # Calculate quarter month (going backward)
        month = current_date.month - (i * 3)
        year = current_date.year
        
        # Adjust year if we go to previous year
        while month <= 0:
            month += 12
            year -= 1
            
        quarters.append(f"{year}-{month:02d}")
    
    # List of companies with their sectors
    companies = [
        ('HDFC Bank Ltd.', 'Financials'),
        ('Infosys Ltd.', 'Information Technology'),
        ('Reliance Industries Ltd.', 'Energy'),
        ('ICICI Bank Ltd.', 'Financials'),
        ('Tata Consultancy Services Ltd.', 'Information Technology'),
        ('Hindustan Unilever Ltd.', 'Consumer Goods'),
        ('Bharti Airtel Ltd.', 'Telecom'),
        ('Axis Bank Ltd.', 'Financials'),
        ('Larsen & Toubro Ltd.', 'Industrials'),
        ('Kotak Mahindra Bank Ltd.', 'Financials'),
        ('ITC Ltd.', 'Consumer Goods'),
        ('State Bank of India', 'Financials'),
        ('Maruti Suzuki India Ltd.', 'Consumer Discretionary'),
        ('Asian Paints Ltd.', 'Materials'),
        ('Bajaj Finance Ltd.', 'Financials')
    ]
    
    # Generate data for each quarter with small variations in percentages
    for quarter in quarters:
        for company, sector in companies:
            # Base percentage
            base_percentage = random.uniform(1.5, 9.0)
            
            # Add a small variation per quarter (±0.5%)
            quarter_index = quarters.index(quarter)
            variation = random.uniform(-0.5, 0.5) * (1 + quarter_index * 0.2)
            
            # Calculate final percentage
            percentage = round(base_percentage + variation, 2)
            
            # Write row
            writer.writerow([quarter, company, sector, percentage])
    
    # Prepare file for download
    output.seek(0)
    
    # Create response
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"historical_mutual_fund_sample.csv"
    )

@app.route('/fund/<int:fund_id>/delete_month/<month_year>')
def delete_month_holdings(fund_id, month_year):
    """Delete all holdings for a specific month and year"""
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Check if fund exists
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    fund = c.fetchone()
    
    if not fund:
        conn.close()
        flash('Fund not found!', 'error')
        return redirect(url_for('index'))
    
    # Count holdings to be deleted
    c.execute('SELECT COUNT(*) FROM holdings WHERE fund_id = ? AND month_year = ?', (fund_id, month_year))
    count = c.fetchone()[0]
    
    if count == 0:
        conn.close()
        flash(f'No holdings found for {month_year}', 'info')
        return redirect(url_for('view_fund', fund_id=fund_id))
    
    # Delete all holdings for this month and year
    c.execute('DELETE FROM holdings WHERE fund_id = ? AND month_year = ?', (fund_id, month_year))
    
    conn.commit()
    conn.close()
    
    flash(f'Successfully deleted all holdings for {month_year}!', 'success')
    return redirect(url_for('view_fund', fund_id=fund_id))

@app.route('/fund/<int:fund_id>/delete')
def delete_fund(fund_id):
    """Delete an entire fund and all its holdings"""
    conn = sqlite3.connect('funds.db')
    c = conn.cursor()
    
    # Check if fund exists
    c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
    fund = c.fetchone()
    
    if not fund:
        conn.close()
        flash('Fund not found!', 'error')
        return redirect(url_for('index'))
    
    # Delete all holdings for this fund
    c.execute('DELETE FROM holdings WHERE fund_id = ?', (fund_id,))
    
    # Delete the fund itself
    c.execute('DELETE FROM funds WHERE id = ?', (fund_id,))
    
    conn.commit()
    conn.close()
    
    flash('Fund deleted successfully!', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    upgrade_db()
    app.run(debug=True, port=5000) 