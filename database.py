import sqlite3
from datetime import datetime
import pandas as pd

class Database:
    def __init__(self, db_file='mutual_funds.db'):
        self.db_file = db_file
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_file)

    def init_db(self):
        conn = self.get_connection()
        c = conn.cursor()

        # Funds table
        c.execute('''CREATE TABLE IF NOT EXISTS funds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_name TEXT NOT NULL,
            fund_category TEXT,
            fund_house TEXT,
            fund_manager TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Holdings Monthly table
        c.execute('''CREATE TABLE IF NOT EXISTS holdings_monthly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER,
            month_year TEXT,
            company_name TEXT NOT NULL,
            sector TEXT NOT NULL,
            percentage REAL NOT NULL,
            previous_percentage REAL,
            change_value REAL,
            entry_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fund_id) REFERENCES funds (id)
        )''')

        # Sector Analysis table
        c.execute('''CREATE TABLE IF NOT EXISTS sector_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER,
            month_year TEXT,
            sector TEXT NOT NULL,
            total_percentage REAL NOT NULL,
            previous_percentage REAL,
            change REAL,
            FOREIGN KEY (fund_id) REFERENCES funds (id)
        )''')

        # Tracking History table
        c.execute('''CREATE TABLE IF NOT EXISTS tracking_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER,
            change_type TEXT NOT NULL,
            company_name TEXT NOT NULL,
            old_value REAL,
            new_value REAL,
            change_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fund_id) REFERENCES funds (id)
        )''')

        conn.commit()
        conn.close()

    def get_all_funds(self):
        """Get all funds from the database"""
        conn = self.get_connection()
        c = conn.cursor()
        
        c.execute('''SELECT * FROM funds ORDER BY fund_name''')
        funds = [dict(zip(['id', 'fund_name', 'fund_category', 'fund_house',
                         'fund_manager', 'created_at', 'last_updated'], row))
                for row in c.fetchall()]
        
        conn.close()
        return funds

    def get_fund(self, fund_id):
        """Get a single fund by ID"""
        conn = self.get_connection()
        c = conn.cursor()
        
        c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
        row = c.fetchone()
        if row:
            fund = dict(zip(['id', 'fund_name', 'fund_category', 'fund_house',
                           'fund_manager', 'created_at', 'last_updated'], row))
        else:
            fund = None
        
        conn.close()
        return fund

    def get_available_months(self, fund_id):
        """Get all available months for a fund's holdings"""
        conn = self.get_connection()
        c = conn.cursor()
        
        c.execute('''SELECT DISTINCT month_year 
                    FROM holdings_monthly 
                    WHERE fund_id = ?
                    ORDER BY month_year DESC''', (fund_id,))
        
        months = [row[0] for row in c.fetchall()]
        conn.close()
        return months

    def add_fund(self, fund_name, category=None, house=None, manager=None):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO funds 
                    (fund_name, fund_category, fund_house, fund_manager) 
                    VALUES (?, ?, ?, ?)''', 
                    (fund_name, category, house, manager))
        fund_id = c.lastrowid
        conn.commit()
        conn.close()
        return fund_id

    def update_fund(self, fund_id, **kwargs):
        conn = self.get_connection()
        c = conn.cursor()
        
        updates = []
        values = []
        for key, value in kwargs.items():
            if value is not None:
                updates.append(f"{key} = ?")
                values.append(value)
        
        if updates:
            values.append(datetime.now())
            values.append(fund_id)
            query = f'''UPDATE funds SET {", ".join(updates)}, last_updated = ? 
                       WHERE id = ?'''
            c.execute(query, values)
            conn.commit()
        conn.close()

    def add_holdings(self, fund_id, month_year, holdings_data):
        conn = self.get_connection()
        c = conn.cursor()
        
        # Get previous month's holdings
        prev_month = self.get_previous_month_holdings(fund_id, month_year)
        prev_holdings = {h['company_name']: h['percentage'] for h in prev_month} if prev_month else {}
        
        # Process each holding
        for holding in holdings_data:
            company = holding['company']
            percentage = holding['percentage']
            sector = holding['sector']
            
            # Calculate change from previous month
            prev_percentage = prev_holdings.get(company, 0)
            change = percentage - prev_percentage
            
            # Insert holding
            c.execute('''INSERT INTO holdings_monthly 
                        (fund_id, month_year, company_name, sector, percentage, 
                         previous_percentage, change_value)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (fund_id, month_year, company, sector, percentage,
                         prev_percentage, change))
            
            # Track changes
            if company not in prev_holdings:
                change_type = 'New Entry'
            elif percentage != prev_percentage:
                change_type = 'Change'
            
            if change_type:
                c.execute('''INSERT INTO tracking_history 
                            (fund_id, change_type, company_name, old_value, new_value)
                            VALUES (?, ?, ?, ?, ?)''',
                            (fund_id, change_type, company, prev_percentage, percentage))
        
        # Update sector analysis
        self.update_sector_analysis(fund_id, month_year, c)
        
        conn.commit()
        conn.close()

    def get_previous_month_holdings(self, fund_id, month_year):
        conn = self.get_connection()
        c = conn.cursor()
        
        # Convert month_year (2024-03) to previous month (2024-02)
        year, month = map(int, month_year.split('-'))
        if month == 1:
            prev_month_year = f"{year-1}-12"
        else:
            prev_month_year = f"{year}-{month-1:02d}"
            
        c.execute('''SELECT * FROM holdings_monthly 
                    WHERE fund_id = ? AND month_year = ?''',
                    (fund_id, prev_month_year))
        
        holdings = [dict(zip(['id', 'fund_id', 'month_year', 'company_name', 
                            'sector', 'percentage', 'previous_percentage',
                            'change_value', 'entry_date'], row))
                   for row in c.fetchall()]
        
        conn.close()
        return holdings

    def update_sector_analysis(self, fund_id, month_year, cursor):
        # Get all holdings for the month grouped by sector
        cursor.execute('''SELECT sector, SUM(percentage) as total
                         FROM holdings_monthly
                         WHERE fund_id = ? AND month_year = ?
                         GROUP BY sector''',
                         (fund_id, month_year))
        
        current_sectors = dict(cursor.fetchall())
        
        # Get previous month's sector data
        year, month = map(int, month_year.split('-'))
        if month == 1:
            prev_month_year = f"{year-1}-12"
        else:
            prev_month_year = f"{year}-{month-1:02d}"
            
        cursor.execute('''SELECT sector, total_percentage
                         FROM sector_analysis
                         WHERE fund_id = ? AND month_year = ?''',
                         (fund_id, prev_month_year))
        
        prev_sectors = dict(cursor.fetchall())
        
        # Update sector analysis
        for sector, total in current_sectors.items():
            prev_total = prev_sectors.get(sector, 0)
            change = total - prev_total
            
            cursor.execute('''INSERT INTO sector_analysis
                            (fund_id, month_year, sector, total_percentage,
                             previous_percentage, change)
                            VALUES (?, ?, ?, ?, ?, ?)''',
                            (fund_id, month_year, sector, total,
                             prev_total, change))

    def get_fund_analysis(self, fund_id, month_year):
        """Get comprehensive analysis for a fund in a specific month"""
        conn = self.get_connection()
        c = conn.cursor()
        
        # Get fund details
        c.execute('SELECT * FROM funds WHERE id = ?', (fund_id,))
        fund = dict(zip(['id', 'fund_name', 'fund_category', 'fund_house',
                        'fund_manager', 'created_at', 'last_updated'],
                       c.fetchone()))
        
        # Get holdings
        c.execute('''SELECT * FROM holdings_monthly 
                    WHERE fund_id = ? AND month_year = ?
                    ORDER BY percentage DESC''',
                    (fund_id, month_year))
        holdings = [dict(zip(['id', 'fund_id', 'month_year', 'company_name',
                            'sector', 'percentage', 'previous_percentage',
                            'change_value', 'entry_date'], row))
                   for row in c.fetchall()]
        
        # Get sector analysis
        c.execute('''SELECT * FROM sector_analysis
                    WHERE fund_id = ? AND month_year = ?
                    ORDER BY total_percentage DESC''',
                    (fund_id, month_year))
        sectors = [dict(zip(['id', 'fund_id', 'month_year', 'sector',
                           'total_percentage', 'previous_percentage', 'change'],
                          row))
                  for row in c.fetchall()]
        
        # Get changes
        c.execute('''SELECT * FROM tracking_history
                    WHERE fund_id = ? AND strftime('%Y-%m', change_date) = ?
                    ORDER BY change_date DESC''',
                    (fund_id, month_year))
        changes = [dict(zip(['id', 'fund_id', 'change_type', 'company_name',
                           'old_value', 'new_value', 'change_date'], row))
                  for row in c.fetchall()]
        
        conn.close()
        
        return {
            'fund': fund,
            'holdings': holdings,
            'sectors': sectors,
            'changes': changes
        }

    def get_comparison_data(self, fund_id, month_year1, month_year2):
        """Compare fund data between two months"""
        analysis1 = self.get_fund_analysis(fund_id, month_year1)
        analysis2 = self.get_fund_analysis(fund_id, month_year2)
        
        # Create comparison summary
        holdings_comparison = []
        all_companies = set()
        
        # Get all companies from both periods
        holdings1 = {h['company_name']: h for h in analysis1['holdings']}
        holdings2 = {h['company_name']: h for h in analysis2['holdings']}
        all_companies.update(holdings1.keys(), holdings2.keys())
        
        for company in all_companies:
            holding1 = holdings1.get(company, {'percentage': 0})
            holding2 = holdings2.get(company, {'percentage': 0})
            
            holdings_comparison.append({
                'company_name': company,
                'sector': holding1.get('sector') or holding2.get('sector'),
                'percentage1': holding1['percentage'],
                'percentage2': holding2['percentage'],
                'change': holding2['percentage'] - holding1['percentage']
            })
        
        return {
            'fund': analysis1['fund'],
            'holdings_comparison': sorted(holdings_comparison,
                                       key=lambda x: abs(x['change']),
                                       reverse=True),
            'month1': month_year1,
            'month2': month_year2
        } 