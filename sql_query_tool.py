#!/usr/bin/env python3
"""
SQL Query Tool for LLM Integration
Safe, constrained SQL execution for financial data queries.
"""

import sqlite3
import re
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import json

class SQLQueryTool:
    """Safe SQL query execution tool for LLM integration."""
    
    def __init__(self, db_path: str = None):
        """Initialize with database connection."""
        if db_path is None:
            # Auto-detect database path - try multiple locations for submission
            import os
            current_dir = os.path.dirname(os.path.abspath(__file__))
            
            db_paths = [
                os.path.join(current_dir, "transactions.db"),  # Same directory
                os.path.join(current_dir, "..", "data", "transactions.db"),  # Submission data folder
                os.path.join(current_dir, "..", "transactions.db"),  # Parent directory
            ]
            
            db_path = None
            for path in db_paths:
                if os.path.exists(path):
                    db_path = path
                    break
            
            if db_path is None:
                raise FileNotFoundError("Could not find transactions.db in expected locations")
        self.db_path = db_path
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Database not found: {db_path}")
        
        # Define allowed SQL patterns for security
        self.allowed_patterns = [
            r'^SELECT\s+',
            r'\s+FROM\s+transactions\s*',
            r'\s+FROM\s+client_summary\s*',
            r'\s+WHERE\s+',
            r'\s+GROUP\s+BY\s+',
            r'\s+ORDER\s+BY\s+',
            r'\s+LIMIT\s+\d+',
            r'\s+COUNT\s*\(',
            r'\s+SUM\s*\(',
            r'\s+AVG\s*\(',
            r'\s+MIN\s*\(',
            r'\s+MAX\s*\(',
        ]
        
        # Forbidden patterns
        self.forbidden_patterns = [
            r'DROP\s+',
            r'DELETE\s+',
            r'INSERT\s+',
            r'UPDATE\s+',
            r'ALTER\s+',
            r'CREATE\s+',
            r'EXEC\s+',
            r'UNION\s+',
            r'--',
            r'/\*',
            r'xp_',
            r'sp_',
        ]
        
        self.max_results = 1000  # Limit result size
        
    def validate_sql(self, sql: str) -> Tuple[bool, str]:
        """Validate SQL query for security and constraints."""
        sql_upper = sql.upper().strip()
        
        # Must start with SELECT
        if not sql_upper.startswith('SELECT'):
            return False, "Only SELECT queries are allowed"
        
        # Check forbidden patterns
        for pattern in self.forbidden_patterns:
            if re.search(pattern, sql_upper):
                return False, f"Forbidden SQL pattern detected: {pattern}"
        
        # Must query allowed tables only
        allowed_tables = ['transactions', 'client_summary']
        if not any(f'FROM {table}' in sql_upper for table in ['TRANSACTIONS', 'CLIENT_SUMMARY']):
            return False, "Query must use 'transactions' or 'client_summary' table"
        
        # Check for potential injection attempts
        suspicious_chars = [';', '"', "'"]
        quote_count = sql.count("'")
        if quote_count % 2 != 0:  # Unmatched quotes
            return False, "Unmatched quotes detected"
        
        return True, "Query validated successfully"
    
    def execute_query(self, sql: str) -> Dict[str, Any]:
        """Execute SQL query safely and return results."""
        
        # Validate query
        is_valid, validation_msg = self.validate_sql(sql)
        if not is_valid:
            return {
                "success": False,
                "error": f"SQL Validation Failed: {validation_msg}",
                "query": sql,
                "results": []
            }
        
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Enable column access by name
            cursor = conn.cursor()
            
            # Execute query with result limit if not already present
            sql_clean = sql.rstrip(';').strip()
            if 'LIMIT' not in sql_clean.upper():
                limited_sql = f"{sql_clean} LIMIT {self.max_results}"
            else:
                limited_sql = sql_clean
            cursor.execute(limited_sql)
            
            # Fetch results
            rows = cursor.fetchall()
            
            # Convert to list of dictionaries
            results = []
            for row in rows:
                results.append(dict(row))
            
            # Get column names
            column_names = [description[0] for description in cursor.description] if rows else []
            
            conn.close()
            
            return {
                "success": True,
                "query": sql,
                "results": results,
                "column_names": column_names,
                "row_count": len(results),
                "limited": len(results) == self.max_results
            }
            
        except sqlite3.Error as e:
            return {
                "success": False,
                "error": f"SQL Execution Error: {str(e)}",
                "query": sql,
                "results": []
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected Error: {str(e)}",
                "query": sql,
                "results": []
            }
    
    def get_schema_info(self) -> Dict[str, Any]:
        """Get database schema information for LLM context."""
        schema_info = {
            "tables": {
                "transactions": {
                    "description": "Main transaction table with all financial data",
                    "columns": {
                        "clnt_id": "INTEGER - Client/customer ID",
                        "bank_id": "INTEGER - Bank identifier", 
                        "acc_id": "INTEGER - Account identifier",
                        "txn_id": "INTEGER - Transaction ID",
                        "txn_date": "TEXT - Transaction date (YYYY-MM-DD HH:MM:SS format)",
                        "desc": "TEXT - Transaction description",
                        "amt": "REAL - Transaction amount (negative for debits, positive for credits)",
                        "cat": "TEXT - Transaction category (Restaurants, Loans, etc.)",
                        "merchant": "TEXT - Merchant name (Unknown if not available)"
                    },
                    "primary_key": "(clnt_id, txn_id)",
                    "indexes": ["idx_client_date", "idx_client_cat", "idx_client_merchant", "idx_date"]
                },
                "client_summary": {
                    "description": "Pre-computed client summary statistics",
                    "columns": {
                        "clnt_id": "INTEGER - Client ID",
                        "transaction_count": "INTEGER - Total number of transactions",
                        "total_spending": "REAL - Sum of absolute amounts (total spending)",
                        "first_transaction": "TEXT - Date of first transaction",
                        "last_transaction": "TEXT - Date of last transaction",
                        "categories_used": "INTEGER - Number of different categories used",
                        "merchants_used": "INTEGER - Number of different merchants used"
                    }
                }
            },
            "sample_queries": [
                "SELECT SUM(ABS(amt)) as total_spent FROM transactions WHERE clnt_id = 2",
                "SELECT cat, SUM(ABS(amt)) as spent FROM transactions WHERE clnt_id = 2 GROUP BY cat ORDER BY spent DESC",
                "SELECT COUNT(*), SUM(ABS(amt)) FROM transactions WHERE clnt_id = 2 AND txn_date >= '2023-09-01' AND txn_date < '2023-10-01'",
                "SELECT * FROM client_summary WHERE clnt_id = 2"
            ],
            "important_notes": [
                "Use ABS(amt) for spending calculations as amounts can be negative",
                "Date format is 'YYYY-MM-DD HH:MM:SS' - use >= and < for date ranges",
                "September 2023 range: txn_date >= '2023-09-01' AND txn_date < '2023-10-01'",
                "Client IDs range from 1 to 875",
                "Data covers June 1, 2023 to September 30, 2023"
            ]
        }
        
        return schema_info
    
    def test_queries(self) -> None:
        """Test the SQL query tool with sample queries."""
        print("🧪 Testing SQL Query Tool...")
        
        test_queries = [
            "SELECT COUNT(*) as total_transactions FROM transactions",
            "SELECT COUNT(DISTINCT clnt_id) as total_clients FROM transactions", 
            "SELECT clnt_id, SUM(ABS(amt)) as total_spent FROM transactions WHERE clnt_id = 2",
            "SELECT cat, COUNT(*) as transaction_count, SUM(ABS(amt)) as total_spent FROM transactions WHERE clnt_id = 2 GROUP BY cat ORDER BY total_spent DESC LIMIT 5"
        ]
        
        for i, query in enumerate(test_queries, 1):
            print(f"\n{i}. Testing: {query}")
            result = self.execute_query(query)
            
            if result["success"]:
                print(f"   ✅ Success: {result['row_count']} rows returned")
                if result["results"]:
                    print(f"   📊 Sample: {result['results'][0]}")
            else:
                print(f"   ❌ Error: {result['error']}")

def main():
    """Test the SQL Query Tool."""
    tool = SQLQueryTool()
    
    # Test basic functionality
    tool.test_queries()
    
    # Display schema info
    print(f"\n📋 Database Schema Information:")
    schema = tool.get_schema_info()
    print(json.dumps(schema, indent=2))

if __name__ == "__main__":
    main()